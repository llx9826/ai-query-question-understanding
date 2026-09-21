from __future__ import annotations

import asyncio
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException

from app.contracts.base import AppError
from app.infrastructure.wren_http import WrenQuestionResult, wren_session_properties
from app.modules.datasets import DatasetPublicationService

from .schemas import QuestionInput


class QuestionGateway(Protocol):
    async def ask(
        self,
        *,
        workspace_id: str,
        publication_id: str,
        request_id: str,
        question: str,
        history: tuple[dict[str, str], ...],
        limit: int,
        session_properties: dict[str, str],
    ) -> WrenQuestionResult: ...


def build_wren_query_router(
    settings,
    current_user,
    publisher: DatasetPublicationService,
    gateway: QuestionGateway | None,
    identities,
) -> APIRouter:
    router = APIRouter(tags=["Wren 问数"])

    @router.post(
        "/workspaces/{workspace_id}/questions",
        response_model=WrenQuestionResult,
    )
    async def ask(
        workspace_id: str,
        body: QuestionInput,
        user_id=Depends(current_user),
    ):
        try:
            identities.require_workspace(
                identities.principal_for_user(user_id), workspace_id
            )
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        if gateway is None:
            raise HTTPException(503, "Wren 问数服务尚未配置。")
        active = await asyncio.to_thread(publisher.active, workspace_id)
        if active is None:
            raise HTTPException(409, "当前数据空间还没有可查询的发布版本。")
        try:
            return await gateway.ask(
                workspace_id=workspace_id,
                publication_id=active.publication_id,
                request_id=body.request_id,
                question=body.question,
                history=tuple(turn.model_dump() for turn in body.history),
                limit=body.limit,
                session_properties=wren_session_properties(user_id, workspace_id),
            )
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    return router
