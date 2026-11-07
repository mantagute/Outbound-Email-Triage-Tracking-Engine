"""Connectors para serviços externos. O connector só fala lá fora e desembrulha."""

from src.connectors.gemini_connector import GeminiConnector, GeminiConnectorError

__all__ = [
    "GeminiConnector",
    "GeminiConnectorError",
]
