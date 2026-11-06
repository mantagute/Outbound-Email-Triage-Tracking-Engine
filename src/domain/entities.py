"""
Domain entities and value objects (RFC-0001 Section 3.4).

Implemented exclusively with the Python standard library to keep the core domain
completely decoupled from external serialization or validation frameworks.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

from src.domain.enums import ALLOWED_INTENTS_BY_STATUS, ReplyIntent, ThreadStatus
from src.domain.exceptions import ContractViolationError, InvalidThreadStateError

EMAIL_FORMAT_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RFC5322_ANGLE_ADDR_REGEX = re.compile(r"<([^<>@\s]+@[^<>@\s]+\.[^<>@\s]+)>")


def normalize_email_address(raw_header: str) -> str:
    """
    Extract and normalize an email address from an RFC 5322 header string.
    Example: 'João Silva <Joao.Silva@Empresa.com.br>' -> 'joao.silva@empresa.com.br'
    """
    if not raw_header or not raw_header.strip():
        return ""

    angle_match = RFC5322_ANGLE_ADDR_REGEX.search(raw_header)
    if angle_match:
        return angle_match.group(1).strip().lower()

    cleaned = raw_header.strip().strip('"').strip("'").lower()
    if " " not in cleaned and "@" in cleaned:
        return cleaned

    for token in cleaned.split():
        token_clean = token.strip("<>\"'(),;")
        if "@" in token_clean:
            return token_clean

    return cleaned


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Entity representing a single RFC 5322 email message within a thread."""

    message_id: str
    sender: str
    recipient: str
    subject: str
    sent_at: datetime
    content_type: str = "text/plain"
    auto_submitted: str | None = None
    body_text: str = ""

    def __post_init__(self) -> None:
        if not self.message_id or not self.message_id.strip():
            raise InvalidThreadStateError("EmailMessage.message_id cannot be empty.")
        if not self.sender or not self.sender.strip():
            raise InvalidThreadStateError("EmailMessage.sender cannot be empty.")

    @property
    def sender_email(self) -> str:
        """Normalized email address of the sender."""
        return normalize_email_address(self.sender)

    @property
    def recipient_email(self) -> str:
        """Normalized email address of the primary recipient."""
        return normalize_email_address(self.recipient)

    def is_sent_by(self, account_email: str) -> bool:
        """Check whether this message was authored by the given email account."""
        return self.sender_email == normalize_email_address(account_email)

    def is_auto_replied(self) -> bool:
        """Check RFC 3834 Auto-Submitted header for automated responses."""
        if not self.auto_submitted:
            return False
        return self.auto_submitted.strip().lower() != "no"


@dataclass(frozen=True, slots=True)
class EmailThread:
    """
    Aggregate root representing a conversation thread initiated by the outbound team.
    Enforces chronological message ordering and provides rich domain query methods.
    """

    thread_id: str
    messages: tuple[EmailMessage, ...]

    def __init__(
        self,
        thread_id: str,
        messages: list[EmailMessage] | tuple[EmailMessage, ...],
    ) -> None:
        if not thread_id or not thread_id.strip():
            raise InvalidThreadStateError("EmailThread.thread_id cannot be empty.")
        if not messages:
            raise InvalidThreadStateError(
                f"EmailThread '{thread_id}' must contain at least one message."
            )
        sorted_messages = tuple(sorted(messages, key=lambda m: m.sent_at))
        object.__setattr__(self, "thread_id", thread_id.strip())
        object.__setattr__(self, "messages", sorted_messages)

    @property
    def initial_message(self) -> EmailMessage:
        """Return the outbound message that originated the thread."""
        return self.messages[0]

    @property
    def latest_message(self) -> EmailMessage:
        """Return the most recent message in the thread."""
        return self.messages[-1]

    @property
    def last_message_id(self) -> str:
        """Cursor identifier used for idempotent delta synchronization."""
        return self.latest_message.message_id

    def external_messages(self, outbound_account_email: str) -> tuple[EmailMessage, ...]:
        """Return all messages in the thread not sent by the outbound account."""
        return tuple(
            msg for msg in self.messages if not msg.is_sent_by(outbound_account_email)
        )

    def has_external_interaction(self, outbound_account_email: str) -> bool:
        """Return True if at least one message was sent by an external address."""
        return len(self.external_messages(outbound_account_email)) > 0

    def days_elapsed_since_dispatch(
        self,
        current_status: ThreadStatus,
        reference_date: date | None = None,
    ) -> int:
        """
        Calculate elapsed calendar days without a reply since the initial outbound email.
        Returns 0 whenever the thread has already received a human response (`RESPONDIDO`).
        """
        if current_status == ThreadStatus.REPLIED:
            return 0

        today = reference_date or date.today()
        delta = (today - self.initial_message.sent_at.date()).days
        return max(0, delta)


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """
    Value object representing the outcome of the triage analysis.
    Enforces the RFC-0001 status-to-intent transition matrix and business invariants in-house.
    """

    status: ThreadStatus
    intent: ReplyIntent
    summary_context: str
    alternative_email: str | None = None

    MAX_SUMMARY_LENGTH = 120

    def __post_init__(self) -> None:
        # 1. Validate status & intent compatibility against the RFC transition matrix
        allowed_intents = ALLOWED_INTENTS_BY_STATUS.get(self.status, frozenset())
        if self.intent not in allowed_intents:
            raise ContractViolationError(
                f"Incompatible transition: status '{self.status}' cannot be paired with "
                f"intent '{self.intent}'. Allowed: {[i.value for i in allowed_intents]}"
            )

        # 2. Validate summary constraints
        cleaned_summary = self.summary_context.strip() if self.summary_context else ""
        if not cleaned_summary:
            raise ContractViolationError("TriageDecision.summary_context cannot be empty.")
        if len(cleaned_summary) > self.MAX_SUMMARY_LENGTH:
            raise ContractViolationError(
                f"TriageDecision.summary_context exceeds {self.MAX_SUMMARY_LENGTH} chars "
                f"(got {len(cleaned_summary)})."
            )
        object.__setattr__(self, "summary_context", cleaned_summary)

        # 3. Validate alternative email when status is PIVOT_REDIRECTED
        if self.alternative_email is not None:
            norm_alt = normalize_email_address(self.alternative_email)
            if not EMAIL_FORMAT_REGEX.match(norm_alt):
                raise ContractViolationError(
                    f"Invalid alternative_email format: '{self.alternative_email}'."
                )
            object.__setattr__(self, "alternative_email", norm_alt)

        if self.status == ThreadStatus.PIVOT_REDIRECTED and not self.alternative_email:
            raise ContractViolationError(
                "status 'PIVOTAR_REDIRECIONADO' requires a valid 'alternative_email'."
            )

    @classmethod
    def from_raw_dict(cls, payload: dict[str, object]) -> "TriageDecision":
        """
        Parse and validate a raw dictionary (e.g. decoded JSON from Gemini API)
        into a strongly-typed TriageDecision without external validation libraries.
        """
        try:
            raw_status = str(payload.get("status", "")).strip()
            raw_intent = str(payload.get("intent", "")).strip()
            status = ThreadStatus(raw_status)
            intent = ReplyIntent(raw_intent)
        except ValueError as exc:
            raise ContractViolationError(
                f"Unknown enum value in triage payload: {exc}"
            ) from exc

        raw_alt = payload.get("alternative_email")
        alt_email = str(raw_alt).strip() if raw_alt not in (None, "") else None
        raw_summary = str(payload.get("summary_context", "")).strip()

        return cls(
            status=status,
            intent=intent,
            summary_context=raw_summary,
            alternative_email=alt_email,
        )


@dataclass(frozen=True, slots=True)
class TrackingRow:
    """
    Domain representation of a row in the operational tracking spreadsheet
    (Columns A through J, plus cursor Column M).
    """

    thread_id: str
    recipient: str
    subject: str
    sent_date: date
    days_without_reply: int
    status: ThreadStatus
    intent: ReplyIntent
    alternative_email: str
    summary_context: str
    direct_link: str
    last_message_id: str

    def to_automation_columns(self) -> list[str | int]:
        """Return serialized values for Columns A through J."""
        return [
            self.thread_id,
            self.recipient,
            self.subject,
            self.sent_date.isoformat(),
            self.days_without_reply,
            self.status.value,
            self.intent.value,
            self.alternative_email,
            self.summary_context,
            self.direct_link,
        ]
