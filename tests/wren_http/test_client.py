import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.contracts.base import AppError
from app.infrastructure.wren_http import WrenHttpClient, WrenHttpSettings


def settings():
    return WrenHttpSettings(
        base_url="http://wren-http.internal",
        service_token=SecretStr("test-service-token"),
        workspace_id="conference-a",
        publication_id="v1",
    )


def test_query_binds_server_selected_workspace_and_hides_token():
    async def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer test-service-token"
        assert request.url.path == "/v1/sql-queries"
        body = json.loads(request.content)
        assert body["workspace_id"] == "conference-a"
        assert body["publication_id"] == "v1"
        return httpx.Response(
            200,
            json={
                **{key: body[key] for key in ("workspace_id", "publication_id")},
                "backend": "duckdb",
                "dialect_sql": "SELECT COUNT(*) AS n FROM main.guests",
                "columns": ["n"],
                "rows": [{"n": 4}],
                "truncated": False,
            },
        )

    client = WrenHttpClient(settings(), transport=httpx.MockTransport(handler))
    result = asyncio.run(client.query("SELECT COUNT(*) AS n FROM guests"))
    assert result.rows == ({"n": 4},)
    assert "test-service-token" not in repr(client.settings)


@pytest.mark.parametrize(
    "status,code",
    [(401, "WREN_UNAUTHORIZED"), (404, "WREN_PUBLICATION_NOT_FOUND"), (422, "WREN_QUERY_FAILED")],
)
def test_remote_failures_are_typed_without_forwarding_body(status, code):
    async def handler(_request):
        return httpx.Response(status, json={"detail": "remote secret or database detail"})

    client = WrenHttpClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AppError) as caught:
        asyncio.run(client.query("SELECT 1"))
    assert caught.value.code == code
    assert "remote secret" not in caught.value.message


def test_mismatched_workspace_response_is_rejected():
    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "workspace_id": "conference-b",
                "publication_id": "v1",
                "backend": "duckdb",
                "dialect_sql": "SELECT 1",
                "columns": ["n"],
                "rows": [{"n": 1}],
                "truncated": False,
            },
        )

    client = WrenHttpClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AppError) as caught:
        asyncio.run(client.query("SELECT 1"))
    assert caught.value.code == "WREN_CONTEXT_MISMATCH"
