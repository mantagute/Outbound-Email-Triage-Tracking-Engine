"""
RFC 5322 & SMTP Protocol Triage Inspector (RFC-0001 Section 3.3).

Encapsulates deterministic header inspection, DSN (Delivery Status Notification) detection,
and SMTP error severity analysis in a pure, dependency-free domain service.
"""

import re

from src.domain.entities import (
    EmailMessage,
    EmailThread,
    TriageDecision,
    normalize_email_address,
)
from src.domain.enums import ReplyIntent, ThreadStatus


class ProtocolTriageInspector:
    """
    Domain service that inspects email protocol metadata (RFC 5322 / RFC 3464 / SMTP).

    Resolves technical bounces (`INVALIDO_BOUNCE`) and unanswered threads (`SEM_RESPOSTA`)
    deterministically before any semantic LLM inference is considered.
    """

    BOUNCE_SENDER_IDENTIFIERS: tuple[str, ...] = (
        "mailer-daemon",
        "postmaster",
        "mail delivery subsystem",
        "mail delivery system",
    )

    BOUNCE_SUBJECT_PATTERNS: tuple[str, ...] = (
        "delivery status notification",
        "undelivered mail",
        "failure notice",
        "returned mail",
        "delivery failure",
        "não foi possível entregar",
        "falha na entrega",
    )

    SMTP_5XX_REGEX = re.compile(r"\b(?:5\d{2}|5\.\d+\.\d+)\b")
    SMTP_4XX_REGEX = re.compile(r"\b(?:4\d{2}|4\.\d+\.\d+)\b")

    def __init__(self, outbound_account_email: str) -> None:
        normalized = normalize_email_address(outbound_account_email)
        if not normalized or "@" not in normalized:
            raise ValueError(
                f"Invalid outbound_account_email provided to inspector: '{outbound_account_email}'"
            )
        self._outbound_email = normalized

    @property
    def outbound_email(self) -> str:
        """Normalized email address of the monitored outbound account."""
        return self._outbound_email

    def inspect(self, thread: EmailThread) -> TriageDecision | None:
        """
        Inspect an EmailThread and return a deterministic TriageDecision if applicable.

        Returns:
            - `TriageDecision` when the thread is a technical bounce or has no external reply.
            - `None` when the thread contains third-party messages requiring semantic analysis.
        """
        for message in thread.messages:
            if self._is_delivery_failure_notice(message):
                return self._build_bounce_decision(message)

        if not thread.has_external_interaction(self._outbound_email):
            return TriageDecision(
                status=ThreadStatus.NO_REPLY,
                intent=ReplyIntent.NOT_APPLICABLE,
                summary_context="Nenhuma resposta recebida até o momento.",
                alternative_email=None,
            )

        return None

    def _is_delivery_failure_notice(self, message: EmailMessage) -> bool:
        """Detect RFC 3464 Delivery Status Notifications (DSN) and mailer-daemon bounces."""
        sender_lower = message.sender.lower()
        subject_lower = message.subject.lower()
        content_type_lower = message.content_type.lower()

        if any(identifier in sender_lower for identifier in self.BOUNCE_SENDER_IDENTIFIERS):
            return True

        if "report-type=delivery-status" in content_type_lower:
            return True

        if any(pattern in subject_lower for pattern in self.BOUNCE_SUBJECT_PATTERNS):
            if (
                "no-reply" in sender_lower
                or "noreply" in sender_lower
                or message.is_auto_replied()
            ):
                return True

        return False

    def _build_bounce_decision(self, bounce_message: EmailMessage) -> TriageDecision:
        """Distinguish permanent (5xx) from temporary (4xx) SMTP delivery failures."""
        diagnostic_text = f"{bounce_message.subject}\n{bounce_message.body_text}"

        match_5xx = self.SMTP_5XX_REGEX.search(diagnostic_text)
        if match_5xx:
            smtp_code = match_5xx.group(0)
            return TriageDecision(
                status=ThreadStatus.INVALID_BOUNCE,
                intent=ReplyIntent.HARD_BOUNCE,
                summary_context=f"Falha permanente de entrega (código SMTP {smtp_code}).",
            )

        match_4xx = self.SMTP_4XX_REGEX.search(diagnostic_text)
        if match_4xx:
            smtp_code = match_4xx.group(0)
            return TriageDecision(
                status=ThreadStatus.INVALID_BOUNCE,
                intent=ReplyIntent.SOFT_BOUNCE,
                summary_context=f"Falha temporária de entrega (código SMTP {smtp_code}).",
            )

        return TriageDecision(
            status=ThreadStatus.INVALID_BOUNCE,
            intent=ReplyIntent.HARD_BOUNCE,
            summary_context="Falha de entrega reportada pelo servidor de destino (Bounce).",
        )
