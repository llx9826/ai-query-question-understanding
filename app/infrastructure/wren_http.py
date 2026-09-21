"""问数平台到 Wren 通用服务的唯一 HTTP 边界。"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.contracts.base import AppError


class WrenHttpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    service_token: SecretStr
    workspace_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    publication_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class WrenAdminSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    admin_token: SecretStr
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class WrenQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    publication_id: str
    backend: Literal["duckdb", "postgres"]
    dialect_sql: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool


class WrenQuestionGatewaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    service_token: SecretStr
    timeout_seconds: float = Field(default=90, gt=0, le=180)


class WrenQuestionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    dataset_id: str | None = None
    source_name: str | None = None
    content_hash: str | None = None
    sheet: str | None = None
    description: str | None = None


class WrenToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arguments: dict[str, Any]
    status: Literal["pending", "succeeded", "failed"]
    summary: str | None = None
    error: str | None = None


class WrenQuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    publication_id: str
    request_id: str
    trace_id: str
    status: Literal["answered", "needs_clarification", "unsupported"]
    answer: str
    logical_sql: str | None = None
    dialect_sql: str | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    truncated: bool = False
    sources: tuple[WrenQuestionSource, ...] = ()
    tool_trace: tuple[WrenToolCallTrace, ...] = ()
    model_name: str
    model_calls: int = 0
    provider_request_ids: tuple[str, ...] = ()


class WrenHttpClient:
    def __init__(self, settings: WrenHttpSettings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def query(
        self,
        sql: str,
        *,
        limit: int = 500,
        session_properties: dict[str, str] | None = None,
    ) -> WrenQueryResult:
        payload = {
            "workspace_id": self.settings.workspace_id,
            "publication_id": self.settings.publication_id,
            "sql": sql,
            "limit": limit,
            "session_properties": session_properties or {},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url.rstrip("/"),
                headers={
                    "Authorization": "Bearer "
                    + self.settings.service_token.get_secret_value()
                },
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post("/v1/sql-queries", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AppError("WREN_UNAVAILABLE", "问数引擎暂时不可用。", 503) from exc
        if response.status_code == 401:
            raise AppError("WREN_UNAUTHORIZED", "问数引擎服务鉴权失败。", 503)
        if response.status_code == 404:
            raise AppError("WREN_PUBLICATION_NOT_FOUND", "当前数据发布版本不可用。", 409)
        if response.is_error:
            raise AppError("WREN_QUERY_FAILED", "问数引擎未能完成查询。", 422)
        try:
            result = WrenQueryResult.model_validate_json(response.content)
        except ValueError as exc:
            raise AppError("WREN_INVALID_RESPONSE", "问数引擎返回了无效结果。", 502) from exc
        if (
            result.workspace_id != self.settings.workspace_id
            or result.publication_id != self.settings.publication_id
        ):
            raise AppError("WREN_CONTEXT_MISMATCH", "问数引擎返回的数据空间不一致。", 502)
        return result


class WrenPublicationClient:
    def __init__(self, settings: WrenAdminSettings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def register_duckdb(
        self,
        *,
        workspace_id: str,
        publication_id: str,
        workspace_token: SecretStr,
        project_relative_path: str,
        sources: tuple[dict[str, str], ...] = (),
    ) -> None:
        payload = {
            "workspace_id": workspace_id,
            "publication_id": publication_id,
            "access_token": workspace_token.get_secret_value(),
            "project_path": project_relative_path,
            "backend": {"type": "duckdb"},
            "sources": sources,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url.rstrip("/"),
                headers={
                    "Authorization": "Bearer " + self.settings.admin_token.get_secret_value()
                },
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post("/v1/admin/publications", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AppError("WREN_UNAVAILABLE", "问数引擎暂时不可用，数据未发布。", 503) from exc
        if response.status_code == 401:
            raise AppError("WREN_ADMIN_UNAUTHORIZED", "问数引擎发布鉴权失败。", 503)
        if response.status_code == 409:
            raise AppError("WREN_PUBLICATION_CONFLICT", "问数引擎发布版本冲突。", 409)
        if response.is_error:
            raise AppError("WREN_PUBLICATION_FAILED", "问数引擎未接受数据发布。", 422)


class WrenQuestionGateway:
    def __init__(self, settings: WrenQuestionGatewaySettings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def ask(
        self,
        *,
        workspace_id: str,
        publication_id: str,
        request_id: str,
        question: str,
        history: tuple[dict[str, str], ...] = (),
        limit: int = 200,
        session_properties: dict[str, str] | None = None,
    ) -> WrenQuestionResult:
        payload = {
            "workspace_id": workspace_id,
            "publication_id": publication_id,
            "request_id": request_id,
            "question": question,
            "history": history,
            "limit": limit,
            "session_properties": session_properties or {},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url.rstrip("/"),
                headers={
                    "Authorization": "Bearer "
                    + self.settings.service_token.get_secret_value()
                },
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post("/v1/questions", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AppError("WREN_UNAVAILABLE", "问数引擎暂时不可用。", 503) from exc
        errors = {
            401: ("WREN_UNAUTHORIZED", "问数引擎服务鉴权失败。", 503),
            404: ("WREN_PUBLICATION_NOT_FOUND", "当前数据发布版本不可用。", 409),
            502: ("WREN_MODEL_INVALID", "问数模型返回了无效结果。", 502),
            503: ("WREN_UNAVAILABLE", "问数引擎或模型暂时不可用。", 503),
        }
        if response.status_code in errors:
            raise AppError(*errors[response.status_code])
        if response.is_error:
            raise AppError("WREN_QUESTION_FAILED", "问数引擎未能完成问题。", 422)
        try:
            result = WrenQuestionResult.model_validate_json(response.content)
        except ValueError as exc:
            raise AppError("WREN_INVALID_RESPONSE", "问数引擎返回了无效结果。", 502) from exc
        if result.workspace_id != workspace_id or result.publication_id != publication_id:
            raise AppError("WREN_CONTEXT_MISMATCH", "问数引擎返回的数据空间不一致。", 502)
        return result


def wren_session_properties(user_id: str, workspace_id: str) -> dict[str, str]:
    return {
        "session_user_id": _sql_string(user_id),
        "session_workspace_id": _sql_string(workspace_id),
    }


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
