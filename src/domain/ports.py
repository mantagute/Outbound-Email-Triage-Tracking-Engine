"""
Architectural Ports (Interfaces) for Hexagonal Architecture (RFC-0001 Section 6.1).

Defines the contracts that external infrastructure adapters (Gmail, Gemini, Google Sheets)
must implement to interact with the core domain and application pipeline.
"""

from typing import Protocol

from src.domain.entities import EmailThread, TrackingRow, TriageDecision


class MailboxReaderPort(Protocol):
    """Port for fetching outbound email threads from an email provider (e.g., Gmail API)."""

    def get_authenticated_address(self) -> str:
        """Return the email address of the authenticated outbound mailbox."""
        ...

    def fetch_recent_outbound_threads(self, lookback_days: int) -> list[EmailThread]:
        """Fetch outbound threads initiated within the specified lookback window."""
        ...


class SemanticClassifierPort(Protocol):
    """Port for semantic natural-language analysis of third-party email replies (e.g., Gemini)."""

    def classify_thread(
        self,
        thread: EmailThread,
        outbound_account_email: str,
    ) -> TriageDecision:
        """Analyze conversation history and return a validated TriageDecision."""
        ...


class TrackingRepositoryPort(Protocol):
    """Port for reading state cursors and persisting triage rows (e.g., Google Sheets)."""

    def load_processed_cursors(self) -> dict[str, str]:
        """Return a mapping of {thread_id: last_message_id} currently stored in the state store."""
        ...

    def save_tracking_rows(self, rows: list[TrackingRow]) -> None:
        """Persist new and updated tracking rows in batch while preserving manual team columns."""
        ...
