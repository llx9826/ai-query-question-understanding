from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Protocol

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import SecretStr

from app.contracts.base import AppError

from .schemas import (
    PublicationCandidate,
    PublicationResult,
    PublicationSummary,
    RelationshipInput,
    WorkbookUpload,
)
from .service import DatasetPublicationService


class PublicationRegistrar(Protocol):
    async def register_duckdb(
        self,
        *,
        workspace_id: str,
        publication_id: str,
        workspace_token: SecretStr,
        project_relative_path: str,
        sources: tuple[dict[str, str], ...],
    ) -> None: ...


def build_dataset_router(
    settings,
    current_user,
    publisher: DatasetPublicationService,
    registrar: PublicationRegistrar | None,
    identities,
) -> APIRouter:
    router = APIRouter(tags=["数据集管理"])
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def check_workspace(user_id: str, workspace_id: str):
        try:
            identities.require_workspace(
                identities.principal_for_user(user_id), workspace_id
            )
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    async def publish(candidate: PublicationCandidate) -> PublicationResult:
        if registrar is None or settings.wren_workspace_token is None:
            raise HTTPException(503, "Wren 发布服务尚未配置。")
        await registrar.register_duckdb(
            workspace_id=candidate.workspace_id,
            publication_id=candidate.publication_id,
            workspace_token=settings.wren_workspace_token,
            project_relative_path=candidate.project_relative_path.as_posix(),
            sources=tuple(
                {
                    "model": table["model"],
                    "dataset_id": dataset.dataset_id,
                    "source_name": dataset.source_name,
                    "content_hash": dataset.content_hash,
                    "sheet": table["sheet"],
                }
                for dataset in candidate.datasets
                for table in dataset.tables
            ),
        )
        return await asyncio.to_thread(publisher.activate, candidate)

    @router.get(
        "/workspaces/{workspace_id}/datasets",
        response_model=PublicationResult | None,
    )
    async def active(workspace_id: str, user_id=Depends(current_user)):
        check_workspace(user_id, workspace_id)
        return await asyncio.to_thread(publisher.active, workspace_id)

    @router.post(
        "/workspaces/{workspace_id}/uploads",
        response_model=PublicationResult,
    )
    async def upload(
        workspace_id: str,
        files: list[UploadFile] = File(...),
        dataset_ids: list[str] | None = Form(default=None),
        user_id=Depends(current_user),
    ):
        check_workspace(user_id, workspace_id)
        if not files or len(files) > 20:
            raise HTTPException(422, "每批需要上传 1 到 20 个 Excel 文件。")
        if dataset_ids is not None and len(dataset_ids) != len(files):
            raise HTTPException(422, "dataset_ids 数量必须与文件数量一致。")
        uploads = []
        for index, file in enumerate(files):
            content = await file.read(settings.dataset_max_upload_bytes + 1)
            if len(content) > settings.dataset_max_upload_bytes:
                raise HTTPException(413, "Excel 文件超过允许大小。")
            uploads.append(
                WorkbookUpload(
                    filename=file.filename or "",
                    content=content,
                    dataset_id=dataset_ids[index] if dataset_ids else None,
                )
            )
        try:
            async with locks[workspace_id]:
                candidate = await asyncio.to_thread(
                    publisher.prepare, workspace_id, tuple(uploads)
                )
                return await publish(candidate)
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    @router.post(
        "/workspaces/{workspace_id}/relationships",
        response_model=PublicationResult,
    )
    async def add_relationship(
        workspace_id: str,
        body: RelationshipInput,
        user_id=Depends(current_user),
    ):
        check_workspace(user_id, workspace_id)
        try:
            async with locks[workspace_id]:
                candidate = await asyncio.to_thread(
                    publisher.prepare_relationship, workspace_id, body
                )
                return await publish(candidate)
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    @router.delete(
        "/workspaces/{workspace_id}/datasets/{dataset_id}",
        response_model=PublicationResult,
    )
    async def remove(
        workspace_id: str,
        dataset_id: str,
        user_id=Depends(current_user),
    ):
        check_workspace(user_id, workspace_id)
        try:
            async with locks[workspace_id]:
                candidate = await asyncio.to_thread(
                    publisher.prepare_removal, workspace_id, dataset_id
                )
                return await publish(candidate)
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    @router.get(
        "/workspaces/{workspace_id}/publications",
        response_model=tuple[PublicationSummary, ...],
    )
    async def publications(workspace_id: str, user_id=Depends(current_user)):
        check_workspace(user_id, workspace_id)
        try:
            return await asyncio.to_thread(publisher.publications, workspace_id)
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    @router.post(
        "/workspaces/{workspace_id}/publications/{publication_id}/activate",
        response_model=PublicationResult,
    )
    async def rollback(
        workspace_id: str,
        publication_id: str,
        user_id=Depends(current_user),
    ):
        check_workspace(user_id, workspace_id)
        try:
            async with locks[workspace_id]:
                return await asyncio.to_thread(
                    publisher.rollback, workspace_id, publication_id
                )
        except AppError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    return router
