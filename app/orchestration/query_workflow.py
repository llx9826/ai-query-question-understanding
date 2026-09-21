"""Linear AgentScope flow: load, bind publication, call Wren, save, reply."""

import asyncio
import base64
from uuid import uuid4

from agentscope.event import (
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    ReplyEndEvent,
    ReplyFinishedReason,
    ReplyStartEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import AssistantMsg, Msg

from app.contracts.base import AppError
from app.contracts.tracing import async_trace_request, trace_stage
from app.infrastructure.wren_http import wren_session_properties

from .session_state import (
    STATE_KEY,
    CompletedTurn,
    InflightTurn,
    SessionEnvelope,
    SessionReply,
    WorkflowFailure,
    load_session_envelope,
    wren_history,
)


class QueryWorkflow:
    def __init__(self, agent, binding) -> None:
        self.agent = agent
        self.binding = binding

    async def reply_stream(self, inputs=None, structured_schema=None, yield_final_msg=False):
        del structured_schema
        question, turn_id = _read_question(inputs)
        reply_id = uuid4().hex
        self.agent.state.reply_id = reply_id
        binding = self.binding

        async with async_trace_request(
            binding.audit,
            entrypoint="agentscope_wren_query",
            user_id=binding.user_id,
            session_id=binding.session_id,
            source_id=binding.workspace_id,
            question=question,
        ) as trace:
            yield ReplyStartEvent(
                session_id=binding.session_id,
                reply_id=reply_id,
                name=self.agent.name,
            )
            envelope = self._load_envelope()
            try:
                envelope = await self._recover_inflight(envelope)
                previous = envelope.find(turn_id)
                if previous is not None:
                    payload = _replay(previous, question, trace.trace_id)
                    trace.status = "replayed"
                else:
                    publication = await self._active_publication()
                    envelope = envelope.model_copy(
                        update={
                            "inflight": InflightTurn(
                                turn_id=turn_id,
                                question=question,
                                reply_id=reply_id,
                                trace_id=trace.trace_id,
                                workspace_id=binding.workspace_id,
                                publication_id=publication.publication_id,
                            )
                        }
                    )
                    await self._checkpoint(envelope, "begin_turn")
                    result = await self._ask_wren(
                        publication.publication_id,
                        turn_id,
                        question,
                        wren_history(envelope),
                    )
                    payload = SessionReply(
                        trace_id=trace.trace_id,
                        turn_id=turn_id,
                        workspace_id=binding.workspace_id,
                        publication_id=publication.publication_id,
                        context_saved=True,
                        result=result,
                    )
                    envelope = envelope.append(
                        CompletedTurn(turn_id=turn_id, question=question, reply=payload)
                    )
                    await self._checkpoint(envelope, "finish_turn")
                    trace.status = result.status
                trace.output = payload
                text = _reply_text(payload)
                for event in _events(binding.session_id, reply_id, text, payload):
                    yield event
                if yield_final_msg:
                    yield AssistantMsg(
                        id=reply_id,
                        name=self.agent.name,
                        content=text,
                        metadata={"trace_id": trace.trace_id},
                    )
            except asyncio.CancelledError:
                payload = await self._finish_interrupted(envelope, trace.trace_id, turn_id)
                trace.status = "cancelled"
                trace.output = payload
                for event in _events(
                    binding.session_id,
                    reply_id,
                    payload.failure.message,
                    payload,
                    ReplyFinishedReason.INTERRUPTED,
                ):
                    yield event
                raise
            except AppError as exc:
                payload = await self._finish_failed(
                    envelope,
                    trace.trace_id,
                    turn_id,
                    exc.code,
                    exc.message,
                )
                trace.status = "error"
                trace.output = payload
                trace.failed_module = trace.failed_module or "wren_query"
                trace.failed_stage = trace.failed_stage or "call_wren"
                for event in _events(
                    binding.session_id,
                    reply_id,
                    payload.failure.message,
                    payload,
                    ReplyFinishedReason.ERROR,
                ):
                    yield event
            except Exception:
                payload = await self._finish_failed(
                    envelope,
                    trace.trace_id,
                    turn_id,
                    "SESSION_RUN_FAILED",
                    "本轮处理或会话保存失败，请稍后重试。",
                )
                trace.status = "error"
                trace.output = payload
                trace.failed_module = trace.failed_module or "orchestration"
                trace.failed_stage = trace.failed_stage or "session_lifecycle"
                for event in _events(
                    binding.session_id,
                    reply_id,
                    payload.failure.message,
                    payload,
                    ReplyFinishedReason.ERROR,
                ):
                    yield event

    def _load_envelope(self) -> SessionEnvelope:
        with trace_stage("orchestration", "load_session") as span:
            envelope = load_session_envelope(
                self.agent.state.middle_context.get(STATE_KEY),
                self.binding.workspace_id,
            )
            span.output = envelope
            return envelope

    async def _recover_inflight(self, envelope: SessionEnvelope) -> SessionEnvelope:
        if envelope.inflight is None:
            return envelope
        failure = WorkflowFailure(
            node="recover_inflight",
            code="UNFINISHED_TURN",
            message="检测到上次请求未完成，本次将作为新的完整问题处理。",
        )
        recovered = envelope.model_copy(
            update={"inflight": None, "last_interruption": failure}
        )
        await self._checkpoint(recovered, "recover_inflight")
        return recovered

    async def _active_publication(self):
        with trace_stage(
            "orchestration",
            "resolve_publication",
            {"workspace_id": self.binding.workspace_id},
        ) as span:
            publication = await asyncio.to_thread(
                self.binding.publisher.active,
                self.binding.workspace_id,
            )
            if publication is None:
                raise AppError(
                    "PUBLICATION_NOT_FOUND",
                    "当前数据空间还没有可查询的发布版本。",
                    409,
                )
            span.output = {"publication_id": publication.publication_id}
            return publication

    async def _ask_wren(self, publication_id, request_id, question, history):
        if self.binding.wren is None:
            raise AppError("WREN_NOT_CONFIGURED", "Wren 问数服务尚未配置。", 503)
        with trace_stage(
            "wren_query",
            "call_wren",
            {
                "workspace_id": self.binding.workspace_id,
                "publication_id": publication_id,
                "request_id": request_id,
                "history_messages": len(history),
            },
        ) as span:
            result = await self.binding.wren.ask(
                workspace_id=self.binding.workspace_id,
                publication_id=publication_id,
                request_id=request_id,
                question=question,
                history=history,
                limit=200,
                session_properties=wren_session_properties(
                    self.binding.user_id,
                    self.binding.workspace_id,
                ),
            )
            span.output = {
                "status": result.status,
                "wren_trace_id": result.trace_id,
                "model_calls": result.model_calls,
            }
            return result

    async def _checkpoint(self, envelope: SessionEnvelope, stage: str) -> None:
        self.agent.state.middle_context[STATE_KEY] = envelope.model_dump(mode="json")
        with trace_stage("orchestration", stage, envelope) as span:
            await self.binding.checkpoint(self.agent.state)
            span.output = {"context_saved": True}

    async def _finish_interrupted(self, envelope, trace_id, turn_id):
        failure = WorkflowFailure(
            node="call_wren",
            code="TURN_INTERRUPTED",
            message="本轮已停止；未完成的 Wren 请求不会加入对话历史。",
        )
        saved = await self._save_terminal_state(envelope, failure, "finish_interrupted")
        return SessionReply(
            trace_id=trace_id,
            turn_id=turn_id,
            workspace_id=self.binding.workspace_id,
            publication_id=envelope.inflight.publication_id if envelope.inflight else None,
            context_saved=saved,
            failure=failure,
        )

    async def _finish_failed(self, envelope, trace_id, turn_id, code, message):
        failure = WorkflowFailure(node="call_wren", code=code, message=message)
        saved = await self._save_terminal_state(envelope, failure, "finish_failed")
        return SessionReply(
            trace_id=trace_id,
            turn_id=turn_id,
            workspace_id=self.binding.workspace_id,
            publication_id=envelope.inflight.publication_id if envelope.inflight else None,
            context_saved=saved,
            failure=failure,
        )

    async def _save_terminal_state(self, envelope, failure, stage):
        cleaned = envelope.model_copy(
            update={"inflight": None, "last_interruption": failure}
        )
        try:
            await self._checkpoint(cleaned, stage)
            return True
        except Exception:
            return False


def _read_question(inputs):
    incoming = [inputs] if isinstance(inputs, Msg) else inputs
    if (
        not incoming
        or not isinstance(incoming, list)
        or any(not isinstance(message, Msg) or message.role != "user" for message in incoming)
    ):
        raise ValueError("此入口只接受用户文本提问")
    question = "\n".join(message.get_text_content() or "" for message in incoming).strip()
    if not question or len(question) > 4000:
        raise ValueError("问题需为1至4000字符的文本")
    metadata = incoming[-1].metadata or {}
    if metadata.get("action") not in {None, "query"}:
        raise ValueError("此入口只支持提交问题")
    return question, incoming[-1].id


def _replay(turn: CompletedTurn, question: str, trace_id: str) -> SessionReply:
    if turn.question != question:
        return SessionReply(
            trace_id=trace_id,
            turn_id=turn.turn_id,
            workspace_id=turn.reply.workspace_id,
            publication_id=turn.reply.publication_id,
            context_saved=True,
            failure=WorkflowFailure(
                node="deduplicate",
                code="MESSAGE_ID_CONFLICT",
                message="同一消息ID不能用于不同问题，请生成新的消息ID。",
            ),
        )
    return turn.reply.model_copy(update={"trace_id": trace_id, "context_saved": True})


def _reply_text(payload: SessionReply) -> str:
    if payload.failure is not None:
        return payload.failure.message
    return payload.result.answer


def _events(session_id, reply_id, text, payload, reason=ReplyFinishedReason.COMPLETED):
    block_id = uuid4().hex
    yield TextBlockStartEvent(reply_id=reply_id, block_id=block_id)
    yield TextBlockDeltaEvent(reply_id=reply_id, block_id=block_id, delta=text)
    yield TextBlockEndEvent(reply_id=reply_id, block_id=block_id)
    block_id = uuid4().hex
    yield DataBlockStartEvent(
        reply_id=reply_id,
        block_id=block_id,
        media_type="application/json",
        name="wren-turn.json",
    )
    yield DataBlockDeltaEvent(
        reply_id=reply_id,
        block_id=block_id,
        media_type="application/json",
        data=base64.b64encode(payload.model_dump_json().encode()).decode(),
    )
    yield DataBlockEndEvent(reply_id=reply_id, block_id=block_id)
    yield ReplyEndEvent(
        session_id=session_id,
        reply_id=reply_id,
        finished_reason=reason,
        metadata={"trace_id": payload.trace_id},
    )
