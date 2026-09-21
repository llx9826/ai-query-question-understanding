"""网页适配接口：仅装配凭证、投影原生会话和审计，不调用模型。"""

import asyncio
import base64
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.base import AppError
from app.orchestration.session_state import SessionReply

AGENT_NAME = "峰会问数 · 网页"


class NewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="新的问数", min_length=1, max_length=80)
    workspace_id: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"
    )


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)


def project_message(message):
    """保留消息ID和业务结果契约；原生状态、凭证和附件不传入页面。"""
    text, reply = [], None
    for block in message.get("content", []):
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "data" and block.get("name") == "wren-turn.json":
            try:
                raw = base64.b64decode(block["source"]["data"], validate=True)
                reply = SessionReply.model_validate_json(raw).model_dump(mode="json")
            except (KeyError, ValueError):
                # 非本应用数据块不作为查询结果；仍保留原始文本供用户阅读。
                pass
    return {
        "id": message["id"],
        "role": message["role"],
        "text": "\n".join(text),
        "finished_reason": message.get("finished_reason"),
        "reply": reply,
    }


def install_web(
    app,
    settings,
    current_user,
    *,
    dataset_publisher,
    publication_client,
    question_gateway,
    storage,
    identities,
):
    """内部 ASGI 请求仍走框架鉴权/锁/存储，不依赖 AgentScope 私有服务。"""
    router = APIRouter(prefix="/ui-api", tags=["网页接入"])
    bootstrap_lock = asyncio.Lock()

    async def native(request, method, path, **kwargs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agentscope.internal",
            headers={"Authorization": request.headers.get("authorization", "")},
            timeout=15,
        ) as client:
            result = await client.request(method, path, **kwargs)
        if result.is_error:
            # 不回传底层异常正文，避免提供商/凭证信息进入浏览器。
            messages = {
                401: "访问凭证无效，请重新连接。",
                403: "无法访问这个会话。",
                404: "会话不存在，请新建会话。",
                409: "当前会话仍在处理，请等待完成或先停止。",
            }
            raise HTTPException(
                result.status_code, messages.get(result.status_code, "请求失败，请检查服务日志。")
            )
        return result.json() if result.content else {}

    async def credential_config(request):
        # AgentScope 2 requires a model object when it constructs an Agent.
        # QueryAgent never calls it: every business model call happens in Wren HTTP.
        result = await native(
            request,
            "POST",
            "/credential/",
            json={
                "data": {
                    "type": "openai_credential",
                    "name": "Wren session shell (never called)",
                    "api_key": "unused-session-shell-key",
                    "base_url": "http://127.0.0.1:1/v1",
                }
            },
        )
        return {
            "type": "openai_credential",
            "credential_id": result["credential_id"],
            "model": "unused-session-shell-model",
            "parameters": {},
        }

    async def session_view(request, agent_id, session_id):
        data = await native(request, "GET", "/sessions/", params={"agent_id": agent_id})
        view = next((v for v in data["sessions"] if v["session"]["id"] == session_id), None)
        if view is None:
            raise HTTPException(404, "会话不存在或无法访问。")
        return view

    def require_workspace(user_id: str, workspace_id: str) -> None:
        try:
            identities.require_workspace(
                identities.principal_for_user(user_id), workspace_id
            )
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    @router.get("/health")
    async def health():
        return {"status": "ok"}

    @router.post("/bootstrap")
    async def bootstrap(request: Request, user_id=Depends(current_user)):
        principal = identities.principal_for_user(user_id)
        default_workspace = (
            settings.workspace_id
            if settings.workspace_id in principal.workspace_ids
            else principal.workspace_ids[0]
        )
        async with bootstrap_lock:
            data = await native(request, "GET", "/agent/")
            agent = next(
                (
                    a
                    for a in data["agents"]
                    if a["user_id"] == user_id and a["data"]["name"] == AGENT_NAME
                ),
                None,
            )
            agent_id = (
                agent["id"]
                if agent
                else (await native(request, "POST", "/agent/", json={"name": AGENT_NAME}))[
                    "agent_id"
                ]
            )
        return {
            "agent_id": agent_id,
            "workspace_id": default_workspace,
            "workspaces": [
                {"workspace_id": item, "name": item}
                for item in principal.workspace_ids
            ],
            "source_name": default_workspace,
            "source_id": default_workspace,
            "wren_configured": question_gateway is not None,
        }

    @router.get("/sessions")
    async def list_sessions(request: Request, agent_id: str, user_id=Depends(current_user)):
        data = await native(request, "GET", "/sessions/", params={"agent_id": agent_id})
        return {
            "sessions": [
                {
                    "id": v["session"]["id"],
                    "name": v["session"]["config"]["name"],
                    "updated_at": v["session"]["updated_at"],
                    "is_running": v["is_running"],
                    "workspace_id": v["session"]
                    .get("state", {})
                    .get("middle_context", {})
                    .get("workspace_id", settings.workspace_id),
                }
                for v in data["sessions"]
            ]
        }

    @router.post("/sessions", status_code=201)
    async def create_session(body: NewSession, request: Request, user_id=Depends(current_user)):
        workspace_id = body.workspace_id or settings.workspace_id
        require_workspace(user_id, workspace_id)
        cfg = await credential_config(request)
        created = await native(
            request,
            "POST",
            "/sessions/",
            json={
                "agent_id": body.agent_id,
                "name": body.name,
                "chat_model_config": cfg,
            },
        )
        session = await storage.get_session(
            user_id, body.agent_id, created["session_id"]
        )
        if session is None:
            raise HTTPException(500, "会话创建后无法绑定数据空间。")
        session.state.middle_context["workspace_id"] = workspace_id
        await storage.update_session_state(
            user_id, body.agent_id, created["session_id"], session.state
        )
        return created

    @router.patch("/sessions/{session_id}")
    async def rename_session(
        session_id: str, body: NewSession, request: Request, user_id=Depends(current_user)
    ):
        return await native(
            request,
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": body.agent_id},
            json={"name": body.name},
        )

    @router.post("/sessions/{session_id}/chat")
    async def chat(
        session_id: str, body: ChatInput, request: Request, user_id=Depends(current_user)
    ):
        # 原生 /chat 是异步接收；网页入口先核验会话归属，立即反馈拒绝。
        await session_view(request, body.agent_id, session_id)
        if not body.question.strip():
            raise HTTPException(422, "问题不能为空。")
        # 每次投递由框架处理；不自动重发，保留前端生成的幂等消息ID。
        message = {
            "id": body.message_id,
            "name": "user",
            "role": "user",
            "content": [{"type": "text", "text": body.question}],
        }
        return await native(
            request,
            "POST",
            "/chat/",
            json={
                "agent_id": body.agent_id,
                "session_id": session_id,
                "input": message,
            },
        )

    @router.post("/sessions/{session_id}/interrupt")
    async def interrupt(
        session_id: str, request: Request, agent_id: str, user_id=Depends(current_user)
    ):
        return await native(
            request, "POST", f"/sessions/{session_id}/interrupt", params={"agent_id": agent_id}
        )

    @router.get("/sessions/{session_id}/snapshot")
    async def snapshot(
        session_id: str,
        request: Request,
        agent_id: str,
        before: str | None = None,
        limit: int = Query(default=40, ge=1, le=100),
        user_id=Depends(current_user),
    ):
        # 先通过框架验证访问，再查询该用户该会话的审计摘要。
        view = await session_view(request, agent_id, session_id)
        params = {"agent_id": agent_id, "limit": limit}
        if before:
            params["before"] = before
        data = await native(request, "GET", f"/sessions/{session_id}/messages", params=params)
        envelope = view["session"].get("state", {}).get("middle_context", {}).get("ai_query", {})
        inflight = envelope.get("inflight")
        # 进度必须对应当前轮次；本轮审计行缺失时不能拿上一轮成功记录充数。
        projected_messages = [project_message(m) for m in data["messages"]]
        replies = [m["reply"] for m in projected_messages if m.get("reply")]
        expected_trace = (
            (inflight or {}).get("trace_id")
            or (replies[-1].get("trace_id") if replies and not before else None)
        )

        progress = await asyncio.to_thread(
            app.state.query_audit.read_progress,
            session_id,
            user_id,
            expected_trace,
            active=data["is_running"],
        )
        return {
            "messages": projected_messages,
            "is_running": data["is_running"],
            "has_more": data["has_more"],
            "progress": progress,
            "active_publication_id": (inflight or {}).get("publication_id"),
        }

    from app.modules.datasets.api import build_dataset_router

    app.include_router(router)
    from app.modules.wren_query import build_wren_query_router

    app.include_router(
        build_dataset_router(
            settings,
            current_user,
            dataset_publisher,
            publication_client,
            identities,
        ),
        prefix="/api/v1",
    )
    app.include_router(
        build_wren_query_router(
            settings,
            current_user,
            dataset_publisher,
            question_gateway,
            identities,
        ),
        prefix="/api/v1",
    )
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="web-assets")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
