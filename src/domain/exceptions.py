"""Domain-specific exceptions for business rule and contract violations."""


class DomainError(Exception):
    """Base exception for all domain layer errors."""


class InvalidThreadStateError(DomainError):
    """Raised when an EmailThread or EmailMessage violates structural invariants."""


class ContractViolationError(DomainError):
    """
    Raised when a TriageDecision violates the RFC-0001 status/intent transition matrix
    or field constraints (e.g., missing alternative email on pivot, summary length).
    """
