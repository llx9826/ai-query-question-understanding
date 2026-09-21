"""Explicit composition root for the platform and AgentScope session shell."""

import asyncio
from contextlib import asynccontextmanager

from agentscope.app import create_app as create_agentscope_app
from agentscope.app.deps import get_current_user_id
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.workspace_manager import IsolationPolicy, LocalWorkspaceManager
from fastapi import Header, HTTPException

from app.contracts.base import AppError
from app.infrastructure.auth import load_identity_provider
from app.infrastructure.duckdb_conversation import DuckDBConversationStore
from app.infrastructure.query_audit.store import ThreadedDuckDBTraceStore
from app.infrastructure.wren_http import (
    WrenAdminSettings,
    WrenPublicationClient,
    WrenQuestionGateway,
    WrenQuestionGatewaySettings,
)
from app.modules.datasets import DatasetPublicationService
from app.orchestration.query_agent import QueryAgent, QueryBinding
from app.settings import Settings


def create_app(
    settings: Settings,
    *,
    storage=None,
    dataset_publisher=None,
    publication_client=None,
    question_gateway=None,
):
    identities = load_identity_provider(settings)
    _validate_production_tokens(settings, identities)

    control_database = settings.control_database.resolve()
    storage = storage or DuckDBConversationStore(control_database)
    audit = ThreadedDuckDBTraceStore(control_database)
    publisher = dataset_publisher or DatasetPublicationService(
        settings.dataset_root,
        control_database=control_database,
        max_upload_bytes=settings.dataset_max_upload_bytes,
    )
    publication_client = publication_client or _build_publication_client(settings)
    question_gateway = question_gateway or _build_question_gateway(settings)
    message_bus = InMemoryMessageBus()

    async def bind(user_id, agent_id, session_id, workspace):
        del workspace
        principal = identities.principal_for_user(user_id)
        session = await storage.get_session(user_id, agent_id, session_id)
        session_workspace = (
            session.state.middle_context.get("workspace_id")
            if session is not None
            else None
        )
        workspace_id = session_workspace or settings.workspace_id
        identities.require_workspace(principal, workspace_id)

        async def checkpoint(state):
            async with asyncio.timeout(settings.checkpoint_timeout_seconds):
                await storage.update_session_state(
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    state=state,
                )

        return [
            QueryBinding(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                workspace_id=workspace_id,
                publisher=publisher,
                wren=question_gateway,
                checkpoint=checkpoint,
                audit=audit,
            )
        ]

    async def current_user(authorization: str = Header(default="")):
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(401, "需要API Bearer Token")
        try:
            return identities.authenticate(token).user_id
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    app = create_agentscope_app(
        storage=storage,
        message_bus=message_bus,
        workspace_manager=LocalWorkspaceManager(
            basedir=str(settings.session_workspace),
            isolation=IsolationPolicy.PER_SESSION,
        ),
        custom_agent_cls=QueryAgent,
        extra_agent_middlewares=bind,
        enable_channel_worker=False,
        enable_scheduler=False,
        enable_index_worker=False,
        title="AI问数 · AgentScope会话 + Wren引擎",
    )
    app.dependency_overrides[get_current_user_id] = current_user
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original_lifespan(app) as state:
                yield state
        finally:
            await asyncio.to_thread(audit.close)

    app.router.lifespan_context = lifespan
    app.state.query_audit = audit

    from app.web.routes import install_web

    install_web(
        app,
        settings,
        current_user,
        dataset_publisher=publisher,
        publication_client=publication_client,
        question_gateway=question_gateway,
        storage=storage,
        identities=identities,
    )
    return app


def _validate_production_tokens(settings, identities) -> None:
    if not settings.demo_mode and any(
        user.api_token.get_secret_value() == "demo-local-key" for user in identities.users
    ):
        raise ValueError("非演示模式需配置独立API凭证")


def _build_publication_client(settings):
    if settings.wren_http_admin_token is None:
        return None
    return WrenPublicationClient(
        WrenAdminSettings(
            base_url=settings.wren_http_base_url,
            admin_token=settings.wren_http_admin_token,
            timeout_seconds=settings.wren_http_timeout_seconds,
        )
    )


def _build_question_gateway(settings):
    if settings.wren_workspace_token is None:
        return None
    return WrenQuestionGateway(
        WrenQuestionGatewaySettings(
            base_url=settings.wren_http_base_url,
            service_token=settings.wren_workspace_token,
            timeout_seconds=settings.wren_http_timeout_seconds,
        )
    )
