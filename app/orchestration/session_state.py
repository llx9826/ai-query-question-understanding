"""Persisted AgentScope state for the thin Wren conversation workflow."""

from typing import Literal

from app.contracts.base import DTO
from app.infrastructure.wren_http import WrenQuestionResult

STATE_KEY = "ai_query"
MAX_COMPLETED_TURNS = 20


class InflightTurn(DTO):
    turn_id: str
    question: str
    reply_id: str
    trace_id: str
    workspace_id: str
    publication_id: str


class WorkflowFailure(DTO):
    module: Literal["orchestration"] = "orchestration"
    node: str
    code: str
    message: str


class SessionReply(DTO):
    contract_version: Literal["wren-session-reply-v2"] = "wren-session-reply-v2"
    trace_id: str
    turn_id: str
    workspace_id: str
    publication_id: str | None = None
    context_saved: bool
    result: WrenQuestionResult | None = None
    failure: WorkflowFailure | None = None


class CompletedTurn(DTO):
    turn_id: str
    question: str
    reply: SessionReply


class SessionEnvelope(DTO):
    contract_version: Literal["wren-agentscope-session-v2"] = (
        "wren-agentscope-session-v2"
    )
    workspace_id: str
    inflight: InflightTurn | None = None
    completed: tuple[CompletedTurn, ...] = ()
    last_interruption: WorkflowFailure | None = None

    def find(self, turn_id: str) -> CompletedTurn | None:
        return next((turn for turn in self.completed if turn.turn_id == turn_id), None)

    def append(self, turn: CompletedTurn) -> "SessionEnvelope":
        completed = (*self.completed, turn)[-MAX_COMPLETED_TURNS:]
        return self.model_copy(
            update={"inflight": None, "completed": completed, "last_interruption": None}
        )


def load_session_envelope(raw: object, workspace_id: str) -> SessionEnvelope:
    """Load v2 state; pre-Wren workflow state is deliberately discarded."""
    if isinstance(raw, dict) and raw.get("contract_version") == "wren-agentscope-session-v2":
        value = SessionEnvelope.model_validate(raw)
        if value.workspace_id == workspace_id:
            return value
    return SessionEnvelope(workspace_id=workspace_id)


def wren_history(envelope: SessionEnvelope, limit: int = 12) -> tuple[dict[str, str], ...]:
    turns = envelope.completed[-max(1, limit // 2) :]
    history: list[dict[str, str]] = []
    for turn in turns:
        history.append({"role": "user", "content": turn.question})
        if turn.reply.result is not None:
            history.append({"role": "assistant", "content": turn.reply.result.answer})
    return tuple(history[-limit:])
