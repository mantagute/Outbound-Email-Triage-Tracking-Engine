"""Testes unitários do GeminiConnector e da tradução para TriageDecision."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from google.genai import types

from src.connectors import GeminiConnector, GeminiConnectorError
from src.domain import (
    ContractViolationError,
    EmailMessage,
    EmailThread,
    ReplyIntent,
    ThreadStatus,
    TriageDecision,
)

OUR_SENDER = "Equipe Operacional <operacoes@organizacao.org.br>"


@dataclass
class FakeGenAIResponse:
    """Resposta simulada do SDK google-genai."""

    text: str | None


class FakeGenAIModelsClient:
    """Stub em memória para testar o GeminiConnector sem chamada de rede."""

    def __init__(
        self,
        response_payload: dict[str, Any] | str | None = None,
        should_raise: Exception | None = None,
    ) -> None:
        self.response_payload = response_payload
        self.should_raise = should_raise
        self.calls: list[dict[str, Any]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> FakeGenAIResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.should_raise is not None:
            raise self.should_raise

        if isinstance(self.response_payload, dict):
            return FakeGenAIResponse(text=json.dumps(self.response_payload, ensure_ascii=False))
        return FakeGenAIResponse(text=self.response_payload)


def _build_sample_thread(external_body: str, auto_submitted: str | None = None) -> EmailThread:
    msg1 = EmailMessage(
        message_id="msg-1",
        sender=OUR_SENDER,
        recipient="diretoria@empresa.com.br",
        subject="[Convite] Participação na Banca 2026",
        sent_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
        body_text="Olá, gostaríamos de convidar você para nossa banca avaliadora.",
    )
    msg2 = EmailMessage(
        message_id="msg-2",
        sender="Diretoria <diretoria@empresa.com.br>",
        recipient=OUR_SENDER,
        subject="Re: [Convite] Participação na Banca 2026",
        sent_at=datetime(2026, 11, 2, 14, 15, tzinfo=UTC),
        auto_submitted=auto_submitted,
        body_text=external_body,
    )
    return EmailThread(thread_id="thread-100", messages=[msg1, msg2])


class TestGeminiConnector:
    """Garante que o connector apenas fala lá fora, respeita timeout e desembrulha o JSON."""

    def test_defaults_to_flash_and_supports_custom_pro_model(self) -> None:
        fake_client = FakeGenAIModelsClient()

        default_conn = GeminiConnector(models_client=fake_client)
        assert default_conn.model_name == "gemini-2.5-flash"
        assert default_conn.TIMEOUT_SECONDS == 15

        pro_conn = GeminiConnector(model_name="gemini-2.5-pro", models_client=fake_client)
        assert pro_conn.model_name == "gemini-2.5-pro"

    def test_unwraps_positive_human_reply_and_domain_validates(self) -> None:
        fake_client = FakeGenAIModelsClient(
            response_payload={
                "status": "RESPONDIDO",
                "intent": "POSITIVO_CONFIRMADO",
                "alternative_email": None,
                "summary_context": "Confirmou presença na banca avaliadora no horário proposto.",
            }
        )
        connector = GeminiConnector(model_name="gemini-2.5-pro", models_client=fake_client)
        thread = _build_sample_thread("Com certeza! Confirmo minha participação.")

        transcript = thread.format_transcript(OUR_SENDER)
        raw_dict = connector.analyze_transcript(transcript)
        decision = TriageDecision.from_raw_dict(raw_dict)

        assert decision.status == ThreadStatus.REPLIED
        assert decision.intent == ReplyIntent.POSITIVE_CONFIRMED
        assert decision.alternative_email is None

        assert len(fake_client.calls) == 1
        call = fake_client.calls[0]
        assert call["model"] == "gemini-2.5-pro"
        assert "NOSSA_EQUIPE" in call["contents"]
        assert "EXTERNO" in call["contents"]
        assert call["config"].temperature == 0.0

    def test_unwraps_out_of_office_with_alternative_contact_as_pivot(self) -> None:
        fake_client = FakeGenAIModelsClient(
            response_payload={
                "status": "PIVOTAR_REDIRECIONADO",
                "intent": "INDICOU_OUTRO_CONTATO",
                "alternative_email": "Suporte Eventos <eventos@empresa.com.br>",
                "summary_context": "Em férias até 20/11; indicou eventos@empresa.com.br.",
            }
        )
        connector = GeminiConnector(models_client=fake_client)
        thread = _build_sample_thread(
            "Estou de férias. Favor contatar eventos@empresa.com.br.",
            auto_submitted="auto-replied",
        )

        transcript = thread.format_transcript(OUR_SENDER)
        raw_dict = connector.analyze_transcript(transcript)
        decision = TriageDecision.from_raw_dict(raw_dict)

        assert decision.status == ThreadStatus.PIVOT_REDIRECTED
        assert decision.intent == ReplyIntent.REDIRECTED_CONTACT
        assert decision.alternative_email == "eventos@empresa.com.br"
        assert "[AUTO-SUBMITTED]" in fake_client.calls[0]["contents"]

    def test_domain_truncates_slightly_long_summary_from_connector_dict(self) -> None:
        fake_client = FakeGenAIModelsClient(
            response_payload={
                "status": "RESPONDIDO",
                "intent": "DUVIDA_OU_REAGENDAR",
                "alternative_email": None,
                "summary_context": "R" * 135,
            }
        )
        connector = GeminiConnector(models_client=fake_client)
        raw_dict = connector.analyze_transcript("Transcrição teste")
        decision = TriageDecision.from_raw_dict(raw_dict)

        assert len(decision.summary_context) == 120
        assert decision.summary_context.endswith("...")

    def test_domain_rejects_invalid_transition_returned_by_connector(self) -> None:
        fake_client = FakeGenAIModelsClient(
            response_payload={
                "status": "PIVOTAR_REDIRECIONADO",
                "intent": "INDICOU_OUTRO_CONTATO",
                "alternative_email": None,
                "summary_context": "Redirecionou mas esqueceu de extrair o e-mail.",
            }
        )
        connector = GeminiConnector(models_client=fake_client)
        raw_dict = connector.analyze_transcript("Transcrição teste")

        with pytest.raises(ContractViolationError, match="requires a valid 'alternative_email'"):
            TriageDecision.from_raw_dict(raw_dict)

    def test_raises_connector_error_on_timeout_or_network_failure(self) -> None:
        fake_client = FakeGenAIModelsClient(
            should_raise=TimeoutError("Request timed out after 15s")
        )
        connector = GeminiConnector(models_client=fake_client)

        with pytest.raises(GeminiConnectorError, match="Request timed out"):
            connector.analyze_transcript("Transcrição teste")
