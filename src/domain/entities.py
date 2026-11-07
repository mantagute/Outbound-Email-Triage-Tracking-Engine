"""Entidades e objetos de valor do domínio.

Escrito apenas com biblioteca padrão do Python: sem ORM e sem libs externas de validação.
Cada classe garante suas próprias invariantes antes de existir em memória.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

from src.domain.enums import ALLOWED_INTENTS_BY_STATUS, ReplyIntent, ThreadStatus
from src.domain.exceptions import ContractViolationError, InvalidThreadStateError

EMAIL_FORMAT_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RFC5322_ANGLE_ADDR_REGEX = re.compile(r"<([^<>@\s]+@[^<>@\s]+\.[^<>@\s]+)>")


def normalize_email_address(raw_header: str) -> str:
    """Extrai apenas o endereço de e-mail em minúsculas de um cabeçalho RFC 5322.

    Exemplo: 'João Silva <Joao.Silva@Empresa.com.br>' vira 'joao.silva@empresa.com.br'.
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
    """Uma mensagem individual dentro de uma conversa de e-mail (RFC 5322)."""

    message_id: str
    sender: str
    recipient: str
    subject: str
    sent_at: datetime
    content_type: str = "text/plain"
    auto_submitted: str | None = None
    body_text: str = ""

    def __post_init__(self) -> None:
        """Recusa mensagem sem identificador ou sem remetente logo na criação."""
        if not self.message_id or not self.message_id.strip():
            raise InvalidThreadStateError("EmailMessage.message_id cannot be empty.")
        if not self.sender or not self.sender.strip():
            raise InvalidThreadStateError("EmailMessage.sender cannot be empty.")

    @property
    def sender_email(self) -> str:
        """Devolve o endereço do remetente limpo, sem nome de exibição."""
        return normalize_email_address(self.sender)

    @property
    def recipient_email(self) -> str:
        """Devolve o endereço do destinatário principal limpo."""
        return normalize_email_address(self.recipient)

    def is_sent_by(self, account_email: str) -> bool:
        """Confere se quem escreveu esta mensagem foi a nossa própria conta de disparo."""
        return self.sender_email == normalize_email_address(account_email)

    def is_auto_replied(self) -> bool:
        """Olha o cabeçalho RFC 3834 Auto-Submitted para saber se é resposta automática."""
        if not self.auto_submitted:
            return False
        return self.auto_submitted.strip().lower() != "no"


@dataclass(frozen=True, slots=True)
class EmailThread:
    """A conversa inteira iniciada por um disparo da equipe.

    Ordena as mensagens por data ao nascer para garantir que `initial_message` seja sempre
    o disparo original e `latest_message` carregue o cursor atual (`last_message_id`).
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
        """Primeira mensagem da conversa (o e-mail enviado pela nossa equipe)."""
        return self.messages[0]

    @property
    def latest_message(self) -> EmailMessage:
        """Última mensagem recebida ou enviada na conversa."""
        return self.messages[-1]

    @property
    def last_message_id(self) -> str:
        """Cursor gravado na coluna M da planilha para não reprocessar thread sem novidade."""
        return self.latest_message.message_id

    def external_messages(self, outbound_account_email: str) -> tuple[EmailMessage, ...]:
        """Filtra apenas mensagens que vieram de fora (exclui nosso envio e follow-ups)."""
        return tuple(
            msg for msg in self.messages if not msg.is_sent_by(outbound_account_email)
        )

    def has_external_interaction(self, outbound_account_email: str) -> bool:
        """Diz se alguém de fora já interagiu nesta conversa."""
        return len(self.external_messages(outbound_account_email)) > 0

    def days_elapsed_since_dispatch(
        self,
        current_status: ThreadStatus,
        reference_date: date | None = None,
    ) -> int:
        """Calcula há quantos dias o destinatário está sem responder.

        Se o status já é `RESPONDIDO`, o contador zera na hora.
        """
        if current_status == ThreadStatus.REPLIED:
            return 0

        today = reference_date or date.today()
        delta = (today - self.initial_message.sent_at.date()).days
        return max(0, delta)

    def format_transcript(
        self,
        outbound_account_email: str,
        max_body_chars: int = 2000,
    ) -> str:
        """Monta o texto cronológico da conversa para enviar ao classificador semântico.

        Marca cada mensagem como NOSSA_EQUIPE ou EXTERNO e sinaliza cabeçalho AUTO-SUBMITTED.
        """
        normalized_owner = normalize_email_address(outbound_account_email)
        blocks: list[str] = []

        for idx, msg in enumerate(self.messages, start=1):
            role = "NOSSA_EQUIPE" if msg.is_sent_by(normalized_owner) else "EXTERNO"
            auto_flag = " [AUTO-SUBMITTED]" if msg.is_auto_replied() else ""
            sent_str = msg.sent_at.strftime("%Y-%m-%d %H:%M")

            body = msg.body_text.strip()
            if len(body) > max_body_chars:
                body = body[:max_body_chars] + "... [truncado]"

            blocks.append(
                f"[{idx}] ({role}{auto_flag}) Data: {sent_str}\n"
                f"De: {msg.sender}\n"
                f"Para: {msg.recipient}\n"
                f"Assunto: {msg.subject}\n"
                f"Corpo:\n{body}"
            )

        joined = "\n---\n".join(blocks)
        return (
            f"Conta remetente da nossa equipe: {normalized_owner}\n"
            f"Assunto da Thread: {self.initial_message.subject}\n"
            f"Total de mensagens: {len(self.messages)}\n\n"
            f"Histórico Cronológico:\n{joined}"
        )


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """Decisão fechada da triagem.

    Aqui mora a validação de contrato da regra de negócio: barra combinação proibida entre
    status e intenção, exige e-mail válido quando há redirecionamento e trava o resumo em 120 chars.
    """

    status: ThreadStatus
    intent: ReplyIntent
    summary_context: str
    alternative_email: str | None = None

    MAX_SUMMARY_LENGTH = 120

    def __post_init__(self) -> None:
        allowed_intents = ALLOWED_INTENTS_BY_STATUS.get(self.status, frozenset())
        if self.intent not in allowed_intents:
            raise ContractViolationError(
                f"Incompatible transition: status '{self.status}' cannot be paired with "
                f"intent '{self.intent}'. Allowed: {[i.value for i in allowed_intents]}"
            )

        cleaned_summary = self.summary_context.strip() if self.summary_context else ""
        if not cleaned_summary:
            raise ContractViolationError("TriageDecision.summary_context cannot be empty.")
        if len(cleaned_summary) > self.MAX_SUMMARY_LENGTH:
            raise ContractViolationError(
                f"TriageDecision.summary_context exceeds {self.MAX_SUMMARY_LENGTH} chars "
                f"(got {len(cleaned_summary)})."
            )
        object.__setattr__(self, "summary_context", cleaned_summary)

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
        """Traduz o dicionário cru vindo do connector em uma decisão validada pelo domínio.

        Se o resumo vier do LLM ligeiramente acima de 120 caracteres, apara com reticências
        antes de validar para não perder uma classificação inteira por excesso de texto.
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
        if len(raw_summary) > cls.MAX_SUMMARY_LENGTH:
            raw_summary = raw_summary[: cls.MAX_SUMMARY_LENGTH - 3].rstrip() + "..."

        return cls(
            status=status,
            intent=intent,
            summary_context=raw_summary,
            alternative_email=alt_email,
        )


@dataclass(frozen=True, slots=True)
class TrackingRow:
    """Representa uma linha da aba `Rastreamento` (colunas automáticas A:J e cursor M)."""

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
        """Devolve a lista ordenada das colunas A até J para o batch_update da planilha."""
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
