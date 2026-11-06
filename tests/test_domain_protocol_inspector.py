"""Unit tests for domain entities, transition invariants, and ProtocolTriageInspector."""

from datetime import UTC, date, datetime

import pytest

from src.domain import (
    ContractViolationError,
    EmailMessage,
    EmailThread,
    InvalidThreadStateError,
    ProtocolTriageInspector,
    ReplyIntent,
    ThreadStatus,
    TriageDecision,
    normalize_email_address,
)

OUR_SENDER = "Equipe Operacional <operacoes@organizacao.org.br>"


def _make_message(
    msg_id: str,
    sender: str,
    recipient: str = "contato@empresa.com",
    subject: str = "Convite Institucional",
    body: str = "Olá, gostaríamos de convidar sua empresa.",
    content_type: str = "text/plain",
    auto_submitted: str | None = None,
    sent_day: int = 1,
) -> EmailMessage:
    return EmailMessage(
        message_id=msg_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        sent_at=datetime(2026, 11, sent_day, 10, 0, tzinfo=UTC),
        content_type=content_type,
        auto_submitted=auto_submitted,
        body_text=body,
    )


class TestDomainEntitiesAndInvariants:
    """Tests for in-house domain entity behaviors and RFC-0001 contract enforcement."""

    def test_normalize_email_address_extracts_from_angle_brackets_and_quotes(self) -> None:
        raw = "João Silva <Joao.Silva@Empresa.com.br>"
        assert normalize_email_address(raw) == "joao.silva@empresa.com.br"
        assert normalize_email_address("  'CANDIDATO@EMAIL.COM' ") == "candidato@email.com"

    def test_email_thread_automatically_orders_messages_chronologically(self) -> None:
        msg_day_5 = _make_message("msg-2", sender=OUR_SENDER, sent_day=5)
        msg_day_1 = _make_message("msg-1", sender=OUR_SENDER, sent_day=1)

        thread = EmailThread(thread_id="thread-order", messages=[msg_day_5, msg_day_1])

        assert thread.initial_message.message_id == "msg-1"
        assert thread.latest_message.message_id == "msg-2"
        assert thread.last_message_id == "msg-2"

    def test_email_thread_rejects_empty_messages_list(self) -> None:
        with pytest.raises(InvalidThreadStateError):
            EmailThread(thread_id="thread-empty", messages=[])

    def test_days_elapsed_since_dispatch_zeros_out_when_replied(self) -> None:
        thread = EmailThread(
            thread_id="thread-days",
            messages=[_make_message("msg-1", sender=OUR_SENDER, sent_day=1)],
        )
        ref_date = date(2026, 11, 6)

        assert thread.days_elapsed_since_dispatch(ThreadStatus.NO_REPLY, ref_date) == 5
        assert thread.days_elapsed_since_dispatch(ThreadStatus.AUTO_REPLY_OOO, ref_date) == 5
        assert thread.days_elapsed_since_dispatch(ThreadStatus.REPLIED, ref_date) == 0

    def test_triage_decision_enforces_status_intent_transition_matrix(self) -> None:
        with pytest.raises(ContractViolationError, match="Incompatible transition"):
            TriageDecision(
                status=ThreadStatus.REPLIED,
                intent=ReplyIntent.HARD_BOUNCE,
                summary_context="Resumo inválido para o status.",
            )

    def test_triage_decision_requires_valid_alternative_email_on_pivot(self) -> None:
        with pytest.raises(ContractViolationError, match="requires a valid 'alternative_email'"):
            TriageDecision(
                status=ThreadStatus.PIVOT_REDIRECTED,
                intent=ReplyIntent.REDIRECTED_CONTACT,
                summary_context="Indicou falar com o financeiro.",
                alternative_email=None,
            )

        decision = TriageDecision(
            status=ThreadStatus.PIVOT_REDIRECTED,
            intent=ReplyIntent.REDIRECTED_CONTACT,
            summary_context="Indicou falar com o financeiro.",
            alternative_email="Financeiro <FINANCEIRO@empresa.com.br>",
        )
        assert decision.alternative_email == "financeiro@empresa.com.br"

    def test_triage_decision_enforces_max_summary_length(self) -> None:
        with pytest.raises(ContractViolationError, match="exceeds 120 chars"):
            TriageDecision(
                status=ThreadStatus.REPLIED,
                intent=ReplyIntent.POSITIVE_CONFIRMED,
                summary_context="A" * 125,
            )

    def test_triage_decision_from_raw_dict_parses_and_validates_payload(self) -> None:
        raw_payload: dict[str, object] = {
            "status": "RESPONDIDO",
            "intent": "DUVIDA_OU_REAGENDAR",
            "alternative_email": None,
            "summary_context": "Pediu para reagendar a entrevista para sexta-feira às 15h.",
        }
        decision = TriageDecision.from_raw_dict(raw_payload)
        assert decision.status == ThreadStatus.REPLIED
        assert decision.intent == ReplyIntent.QUESTION_OR_RESCHEDULE


class TestProtocolTriageInspector:
    """Tests for the deterministic RFC 5322 & SMTP protocol inspector."""

    def setup_method(self) -> None:
        self.inspector = ProtocolTriageInspector(outbound_account_email=OUR_SENDER)

    def test_single_outbound_message_is_classified_as_no_reply(self) -> None:
        thread = EmailThread(
            thread_id="thread-001",
            messages=[_make_message("msg-1", sender=OUR_SENDER)],
        )

        decision = self.inspector.inspect(thread)

        assert decision is not None
        assert decision.status == ThreadStatus.NO_REPLY
        assert decision.intent == ReplyIntent.NOT_APPLICABLE

    def test_outbound_with_internal_followups_still_classified_as_no_reply(self) -> None:
        thread = EmailThread(
            thread_id="thread-002",
            messages=[
                _make_message("msg-1", sender=OUR_SENDER, sent_day=1),
                _make_message(
                    "msg-2",
                    sender="operacoes@organizacao.org.br",
                    body="Olá, apenas acompanhando nosso último e-mail.",
                    sent_day=4,
                ),
            ],
        )

        decision = self.inspector.inspect(thread)

        assert decision is not None
        assert decision.status == ThreadStatus.NO_REPLY
        assert decision.intent == ReplyIntent.NOT_APPLICABLE

    def test_hard_bounce_5xx_from_mailer_daemon_is_caught_by_inspector(self) -> None:
        thread = EmailThread(
            thread_id="thread-003",
            messages=[
                _make_message("msg-1", sender=OUR_SENDER),
                _make_message(
                    "msg-2",
                    sender="Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                    recipient="operacoes@organizacao.org.br",
                    subject="Delivery Status Notification (Failure)",
                    content_type="multipart/report; report-type=delivery-status",
                    body="550 5.1.1 The email account that you tried to reach does not exist.",
                ),
            ],
        )

        decision = self.inspector.inspect(thread)

        assert decision is not None
        assert decision.status == ThreadStatus.INVALID_BOUNCE
        assert decision.intent == ReplyIntent.HARD_BOUNCE
        assert "550" in decision.summary_context

    def test_soft_bounce_4xx_mailbox_full_is_classified_as_temporary_error(self) -> None:
        thread = EmailThread(
            thread_id="thread-004",
            messages=[
                _make_message("msg-1", sender=OUR_SENDER),
                _make_message(
                    "msg-2",
                    sender="postmaster@outlook.com",
                    recipient="operacoes@organizacao.org.br",
                    subject="Undelivered Mail Returned to Sender",
                    body="Remote server returned '452 4.2.2 The email account is over quota'.",
                ),
            ],
        )

        decision = self.inspector.inspect(thread)

        assert decision is not None
        assert decision.status == ThreadStatus.INVALID_BOUNCE
        assert decision.intent == ReplyIntent.SOFT_BOUNCE
        assert "452" in decision.summary_context

    def test_external_human_reply_returns_none_to_delegate_to_semantic_classifier(self) -> None:
        thread = EmailThread(
            thread_id="thread-005",
            messages=[
                _make_message("msg-1", sender=OUR_SENDER),
                _make_message(
                    "msg-2",
                    sender="Maria Diretora <maria@empresa.com>",
                    recipient="operacoes@organizacao.org.br",
                    subject="Re: Convite Institucional",
                    body="Olá! Podemos agendar uma conversa na próxima quinta-feira às 14h?",
                ),
            ],
        )

        decision = self.inspector.inspect(thread)

        assert decision is None

    def test_external_auto_reply_ooo_returns_none_to_delegate_to_semantic_classifier(self) -> None:
        thread = EmailThread(
            thread_id="thread-006",
            messages=[
                _make_message("msg-1", sender=OUR_SENDER),
                _make_message(
                    "msg-2",
                    sender="Carlos Gerente <carlos@empresa.com>",
                    recipient="operacoes@organizacao.org.br",
                    subject="Ausência temporária: Convite Institucional",
                    auto_submitted="auto-replied",
                    body="Estou em férias até 20/11. Para urgências, contate ana@empresa.com.",
                ),
            ],
        )

        decision = self.inspector.inspect(thread)

        assert decision is None
