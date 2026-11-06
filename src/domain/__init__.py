"""Core domain layer: entities, enums, ports, exceptions, and protocol triage inspector."""

from src.domain.entities import (
    EmailMessage,
    EmailThread,
    TrackingRow,
    TriageDecision,
    normalize_email_address,
)
from src.domain.enums import (
    ALLOWED_INTENTS_BY_STATUS,
    ReplyIntent,
    ThreadStatus,
)
from src.domain.exceptions import (
    ContractViolationError,
    DomainError,
    InvalidThreadStateError,
)
from src.domain.ports import (
    MailboxReaderPort,
    SemanticClassifierPort,
    TrackingRepositoryPort,
)
from src.domain.protocol_inspector import ProtocolTriageInspector

__all__ = [
    "ALLOWED_INTENTS_BY_STATUS",
    "ContractViolationError",
    "DomainError",
    "EmailMessage",
    "EmailThread",
    "InvalidThreadStateError",
    "MailboxReaderPort",
    "ProtocolTriageInspector",
    "ReplyIntent",
    "SemanticClassifierPort",
    "ThreadStatus",
    "TrackingRepositoryPort",
    "TrackingRow",
    "TriageDecision",
    "normalize_email_address",
]
