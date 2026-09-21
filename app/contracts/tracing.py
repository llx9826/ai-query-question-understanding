"""调用追踪技术契约；不保存会话，也不改变业务节点的入参和返回值。"""

import asyncio
import logging
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, SecretStr

logger = logging.getLogger(__name__)


def json_value(value):
    """仅序列化显式业务数据，禁止对模型/客户端对象做 repr。"""
    if isinstance(value, SecretStr):
        return "[REDACTED]"
    if isinstance(value, BaseModel):
        return json_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if str(k).lower() in {"api_key", "password", "authorization", "api_token", "secret"}
            else json_value(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return {"type": type(value).__name__}


def exception_info(exc):
    # 保留异常因果类型及业务错误码，不记录可能含凭证的底层异常文本。
    chain, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append({"type": type(current).__name__, "code": getattr(current, "code", None)})
        current = current.__cause__ or current.__context__
    return {"chain": chain}


class TraceStore(Protocol):
    def start_request(self, values: dict): ...
    def finish_request(self, trace_id: str, values: dict): ...
    def start_stage(self, values: dict): ...
    def finish_stage(self, stage_id: str, values: dict): ...
    async def flush(self, trace_id: str) -> bool: ...


@dataclass
class Trace:
    trace_id: str
    store: TraceStore | None
    output: object = None
    status: str = "ok"
    failed_module: str | None = None
    failed_stage: str | None = None
    logging_failed: bool = False
    stage_count: int = 0

    def write(self, method, *args):
        if self.store is None:
            return
        try:
            if getattr(self.store, method)(*args) is False:
                self.logging_failed = True
        except Exception as exc:
            self.logging_failed = True
            logger.error(
                "audit_write_failed trace_id=%s operation=%s type=%s",
                self.trace_id,
                method,
                type(exc).__name__,
            )


@dataclass
class Stage:
    output: object = None
    status: str = "ok"
    details: dict = field(default_factory=dict)


_trace: ContextVar[Trace | None] = ContextVar("query_trace", default=None)
_stage: ContextVar[str | None] = ContextVar("query_stage", default=None)


def current_trace():
    return _trace.get()


@contextmanager
def trace_request(store, **metadata):
    """每个业务请求一条记录；线程池和模型异步任务继承 ContextVar。"""
    existing = current_trace()
    if existing is not None:
        yield existing
        return
    trace = Trace(uuid4().hex, store)
    token = _trace.set(trace)
    parent = _stage.set(None)
    started = monotonic()
    start_values = {
        "trace_id": trace.trace_id,
        "started_at": datetime.now(timezone.utc),
        "status": "running",
        "metadata_json": json_value(metadata),
        "session_id": metadata.get("session_id"),
        "user_id": metadata.get("user_id"),
        "source_id": metadata.get("source_id"),
        "question": metadata.get("question", ""),
    }
    trace.write("start_request", start_values)
    error = None
    try:
        yield trace
    except BaseException as exc:
        trace.status = "error" if isinstance(exc, Exception) else "cancelled"
        error = exception_info(exc)
        raise
    finally:
        trace.write(
            "finish_request",
            trace.trace_id,
            {
                **start_values,
                "metadata_json": {
                    **start_values["metadata_json"],
                    "audit_expected_stages": trace.stage_count,
                },
                "status": trace.status,
                "finished_at": datetime.now(timezone.utc),
                "duration_ms": round((monotonic() - started) * 1000),
                "output_json": json_value(trace.output),
                "error_json": error,
                "failed_module": trace.failed_module,
                "failed_stage": trace.failed_stage,
                "logging_failed": trace.logging_failed,
            },
        )
        _stage.reset(parent)
        _trace.reset(token)


@asynccontextmanager
async def async_trace_request(store, **metadata):
    """异步入口等待审计收尾；节点仍用同一同步追踪契约，不承担持久化调度。"""
    existing = current_trace()
    trace = None
    try:
        with trace_request(store, **metadata) as trace:
            yield trace
    finally:
        if store is not None and trace is not None and existing is None:
            task = asyncio.create_task(store.flush(trace.trace_id))
            try:
                complete = await asyncio.shield(task)
            except asyncio.CancelledError:
                try:
                    await task
                except Exception as exc:
                    logger.error(
                        "audit_flush_failed trace_id=%s type=%s", trace.trace_id, type(exc).__name__
                    )
                raise
            except Exception as exc:
                trace.logging_failed = True
                logger.error(
                    "audit_flush_failed trace_id=%s type=%s", trace.trace_id, type(exc).__name__
                )
            else:
                trace.logging_failed = trace.logging_failed or not complete


@contextmanager
def trace_stage(module, name, inputs=None):
    span = Stage()
    trace = current_trace()
    if trace is None:
        yield span
        return
    stage_id = uuid4().hex
    trace.stage_count += 1
    parent_id = _stage.get()
    token = _stage.set(stage_id)
    started = monotonic()
    start_values = {
        "stage_id": stage_id,
        "trace_id": trace.trace_id,
        "parent_stage_id": parent_id,
        "module": module,
        "stage": name,
        "status": "running",
        "started_at": datetime.now(timezone.utc),
        "input_json": json_value(inputs),
    }
    trace.write("start_stage", start_values)
    error = None
    try:
        yield span
    except BaseException as exc:
        span.status = "error" if isinstance(exc, Exception) else "cancelled"
        error = exception_info(exc)
        # 最内层失败是首先观察到的故障点，不让上层覆盖归属。
        if trace.failed_module is None:
            trace.failed_module, trace.failed_stage = module, name
        raise
    finally:
        trace.write(
            "finish_stage",
            stage_id,
            {
                **start_values,
                "status": span.status,
                "finished_at": datetime.now(timezone.utc),
                "duration_ms": round((monotonic() - started) * 1000),
                "output_json": json_value(span.output),
                "details_json": json_value(span.details),
                "error_json": error,
            },
        )
        _stage.reset(token)
