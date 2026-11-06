"""Domain taxonomies and state transition matrix (RFC-0001 Section 3.4)."""

from enum import StrEnum


class ThreadStatus(StrEnum):
    """Macro operational state of an email thread."""

    NO_REPLY = "SEM_RESPOSTA"
    REPLIED = "RESPONDIDO"
    PIVOT_REDIRECTED = "PIVOTAR_REDIRECIONADO"
    AUTO_REPLY_OOO = "AUSENTE_AUTO_REPLY"
    INVALID_BOUNCE = "INVALIDO_BOUNCE"


class ReplyIntent(StrEnum):
    """Granular semantic intent or protocol failure classification."""

    POSITIVE_CONFIRMED = "POSITIVO_CONFIRMADO"
    QUESTION_OR_RESCHEDULE = "DUVIDA_OU_REAGENDAR"
    DECLINED = "RECUSADO"
    REDIRECTED_CONTACT = "INDICOU_OUTRO_CONTATO"
    OUT_OF_OFFICE_NO_ALT = "AUSENTE_SEM_SUBSTITUTO"
    HARD_BOUNCE = "ERRO_PERMANENTE_5XX"
    SOFT_BOUNCE = "ERRO_TEMPORARIO_4XX"
    NOT_APPLICABLE = "N/A"


ALLOWED_INTENTS_BY_STATUS: dict[ThreadStatus, frozenset[ReplyIntent]] = {
    ThreadStatus.NO_REPLY: frozenset({ReplyIntent.NOT_APPLICABLE}),
    ThreadStatus.REPLIED: frozenset(
        {
            ReplyIntent.POSITIVE_CONFIRMED,
            ReplyIntent.QUESTION_OR_RESCHEDULE,
            ReplyIntent.DECLINED,
        }
    ),
    ThreadStatus.PIVOT_REDIRECTED: frozenset({ReplyIntent.REDIRECTED_CONTACT}),
    ThreadStatus.AUTO_REPLY_OOO: frozenset({ReplyIntent.OUT_OF_OFFICE_NO_ALT}),
    ThreadStatus.INVALID_BOUNCE: frozenset(
        {
            ReplyIntent.HARD_BOUNCE,
            ReplyIntent.SOFT_BOUNCE,
        }
    ),
}
