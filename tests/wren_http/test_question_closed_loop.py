from io import BytesIO
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import SecretStr
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from wren_http.bootstrap import create_app as create_wren_app
from wren_http.settings import ServiceSettings

from app.infrastructure.auth import IdentityProvider, UserCredential
from app.infrastructure.wren_http import (
    WrenAdminSettings,
    WrenPublicationClient,
    WrenQuestionGateway,
    WrenQuestionGatewaySettings,
)
from app.modules.datasets import DatasetPublicationService, WorkbookUpload
from app.modules.wren_query import build_wren_query_router


def count_agent_model(call_log):
    def respond(messages, info):
        call_log.append(messages)
        returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(
                parts=[ToolCallPart("wren_list_models", {}, "list-models")]
            )
        if returns[-1].tool_name == "wren_list_models":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "wren_query",
                        {
                            "sql": 'SELECT COUNT(*) AS total FROM "ds_test_sheet_1"',
                            "limit": 100,
                        },
                        "run-query",
                    )
                ]
            )
        output_tool = info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    {"status": "answered", "answer": "共有 2 条记录。"},
                    "final-answer",
                )
            ]
        )

    return FunctionModel(respond, model_name="test-wren-agent")


def workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["guest_id", "name"])
    sheet.append(["Q001", "One"])
    sheet.append(["Q002", "Two"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def question_app(settings, publisher, transport, token):
    gateway = WrenQuestionGateway(
        WrenQuestionGatewaySettings(
            base_url="http://wren.test", service_token=token
        ),
        transport=transport,
    )

    async def current_user():
        return "tester"

    app = FastAPI()
    app.include_router(
        build_wren_query_router(
            settings,
            current_user,
            publisher,
            gateway,
            IdentityProvider(
                settings.workspace_id,
                (
                    UserCredential(
                        user_id="tester",
                        api_token=SecretStr("question-test-user-token"),
                        workspace_ids=(settings.workspace_id,),
                    ),
                ),
            ),
        ),
        prefix="/api/v1",
    )
    return app


def test_question_http_uses_active_publication_sources_and_survives_restart(tmp_path):
    workspace = "question-space"
    admin_token = SecretStr("question-admin-token")
    query_token = SecretStr("question-query-token")
    publisher = DatasetPublicationService(tmp_path / "datasets")
    candidate = publisher.prepare(
        workspace,
        (
            WorkbookUpload(
                filename="guests.xlsx",
                dataset_id="test",
                content=workbook_bytes(),
            ),
        ),
    )
    service_settings = ServiceSettings(
        admin_token=admin_token,
        workspaces_file=tmp_path / "wren" / "workspaces.json",
        duckdb_root=publisher.published_root,
        memory_enabled=False,
    )
    first_calls = []
    wren_app = create_wren_app(
        service_settings,
        model_factory=lambda _: count_agent_model(first_calls),
    )
    wren_transport = httpx.ASGITransport(app=wren_app)
    registrar = WrenPublicationClient(
        WrenAdminSettings(base_url="http://wren.test", admin_token=admin_token),
        transport=wren_transport,
    )
    sources = tuple(
        {
            "model": table["model"],
            "dataset_id": dataset.dataset_id,
            "source_name": dataset.source_name,
            "content_hash": dataset.content_hash,
            "sheet": table["sheet"],
        }
        for dataset in candidate.datasets
        for table in dataset.tables
    )
    import asyncio

    asyncio.run(
        registrar.register_duckdb(
            workspace_id=workspace,
            publication_id=candidate.publication_id,
            workspace_token=query_token,
            project_relative_path=candidate.project_relative_path.as_posix(),
            sources=sources,
        )
    )
    publisher.activate(candidate)
    settings = SimpleNamespace(workspace_id=workspace)
    request = {
        "request_id": "question-request-1",
        "question": "一共有多少条记录？",
        "history": [{"role": "user", "content": "请查看来宾数据。"}],
    }
    with TestClient(
        question_app(settings, publisher, wren_transport, query_token)
    ) as client:
        response = client.post(
            f"/api/v1/workspaces/{workspace}/questions", json=request
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == [{"total": 2}]
    assert body["answer"] == "共有 2 条记录。"
    assert [item["name"] for item in body["tool_trace"]] == [
        "wren_list_models",
        "wren_query",
    ]
    assert body["model_name"] == "test-wren-agent"
    assert body["publication_id"] == candidate.publication_id
    assert body["sources"][0]["source_name"] == "guests.xlsx"
    assert body["sources"][0]["dataset_id"] == "test"
    assert len(first_calls) == 3

    restarted_calls = []
    restarted_wren = create_wren_app(
        service_settings,
        model_factory=lambda _: count_agent_model(restarted_calls),
    )
    restarted_transport = httpx.ASGITransport(app=restarted_wren)
    with TestClient(
        question_app(settings, publisher, restarted_transport, query_token)
    ) as client:
        repeated = client.post(
            f"/api/v1/workspaces/{workspace}/questions", json=request
        ).json()
    assert repeated["rows"] == [{"total": 2}]
    assert len(restarted_calls) == 3
