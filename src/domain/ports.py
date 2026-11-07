"""Contratos internos (Protocols) para desacoplar o controller dos connectors e do repository."""

from typing import Any, Protocol

from src.domain.entities import EmailThread, TrackingRow


class MailboxConnectorPort(Protocol):
    """Contrato do connector que busca conversas enviadas no provedor de e-mail (Gmail API)."""

    def get_authenticated_address(self) -> str:
        """Devolve o e-mail da conta autenticada."""
        ...

    def fetch_recent_outbound_threads(self, lookback_days: int) -> list[EmailThread]:
        """Busca as conversas iniciadas pela conta dentro da janela de dias informada."""
        ...


class SemanticConnectorPort(Protocol):
    """Contrato do connector que consulta o serviço externo de IA (Gemini API)."""

    def analyze_transcript(self, transcript: str) -> dict[str, Any]:
        """Envia a transcrição da conversa e devolve o JSON desembrulhado em dict."""
        ...


class TrackingRepositoryPort(Protocol):
    """Contrato do repository que lê cursores e grava as linhas de triagem no Google Sheets."""

    def load_processed_cursors(self) -> dict[str, str]:
        """Devolve o mapa {thread_id: last_message_id} salvo atualmente na planilha."""
        ...

    def save_tracking_rows(self, rows: list[TrackingRow]) -> None:
        """Grava as linhas novas e atualizadas em lote sem tocar nas colunas manuais K e L."""
        ...
