import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import create_app
from app.contracts.base import AppError
from app.infrastructure.wren_http import WrenQuestionResult, WrenQuestionSource
from app.settings import Settings

ALICE = {"Authorization": "Bearer alice-session-test"}
BOB = {"Authorization": "Bearer bob-session-test"}


class ActivePublication:
    def __init__(self, publication_id="publication-v1"):
        self.publication_id = publication_id

    def active(self, workspace_id):
        return SimpleNamespace(
            workspace_id=workspace_id,
            publication_id=self.publication_id,
        )


class FakeWren:
    def __init__(self):
        self.calls = []
        self.block_questions = set()
        self.failures = {}

    async def ask(self, **request):
        self.calls.append(request)
        question = request["question"]
        if question in self.block_questions:
            await asyncio.Event().wait()
        if question in self.failures:
            raise self.failures[question]
        count = len(self.calls)
        return WrenQuestionResult(
            workspace_id=request["workspace_id"],
            publication_id=request["publication_id"],
            request_id=request["request_id"],
            trace_id=f"wren-{count}",
            status="answered",
            answer=f"Wren回答：{question}",
            logical_sql="SELECT COUNT(*) AS total FROM guests",
            dialect_sql="SELECT COUNT(*) AS total FROM main.guests",
            columns=("total",),
            rows=({"total": count},),
            sources=(
                WrenQuestionSource(
                    model="guests",
                    dataset_id="guest-list",
                    source_name="guests.xlsx",
                    sheet="Guests",
                ),
            ),
            model_name="wren-test-model",
            model_calls=1,
        )


@pytest.fixture
def session_settings(tmp_path):
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps(
            [
                {
                    "user_id": "alice",
                    "api_token": "alice-session-test",
                    "workspace_ids": ["conference-test", "conference-other"],
                },
                {
                    "user_id": "bob",
                    "api_token": "bob-session-test",
                    "workspace_ids": ["conference-test"],
                },
            ]
        ),
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        api_users_path=users,
        workspace_id="conference-test",
        session_workspace=tmp_path / "workspaces",
        control_database=tmp_path / "control.duckdb",
        dataset_root=tmp_path / "datasets",
    )


def make_client(settings, publisher, wren, **kwargs):
    return TestClient(
        create_app(
            settings,
            dataset_publisher=publisher,
            question_gateway=wren,
            **kwargs,
        ),
        headers=ALICE,
    )


def create_session(client):
    agent = client.post("/agent/", json={"name": "Wren问数测试"})
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["agent_id"]
    credential = client.post(
        "/credential/",
        json={
            "data": {
                "type": "openai_credential",
                "name": "unused test shell",
                "api_key": "unused-test-shell-key",
                "base_url": "http://127.0.0.1:1/v1",
            }
        },
    )
    assert credential.status_code == 201, credential.text
    config = {
        "type": "openai_credential",
        "credential_id": credential.json()["credential_id"],
        "model": "unused-test-shell-model",
        "parameters": {},
    }
    session = client.post(
        "/sessions/",
        json={"agent_id": agent_id, "name": "测试会话", "chat_model_config": config},
    )
    assert session.status_code == 201, session.text
    return agent_id, session.json()["session_id"]


def messages(client, agent_id, session_id):
    response = client.get(
        f"/sessions/{session_id}/messages",
        params={"agent_id": agent_id, "limit": 100},
    )
    assert response.status_code == 200, response.text
    return response.json()


def send(client, agent_id, session_id, question, message_id):
    payload = {
        "agent_id": agent_id,
        "session_id": session_id,
        "input": {
            "id": message_id,
            "name": "user",
            "role": "user",
            "content": [{"type": "text", "text": question}],
        },
    }
    return client.post("/chat/", json=payload)


def wait_reply(client, agent_id, session_id, expected_messages, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = messages(client, agent_id, session_id)
        if not data["is_running"] and len(data["messages"]) >= expected_messages:
            reply = data["messages"][-1]
            if reply["role"] == "assistant":
                block = next(
                    item
                    for item in reply["content"]
                    if item["type"] == "data" and item["name"] == "wren-turn.json"
                )
                return json.loads(base64.b64decode(block["source"]["data"])), reply
        time.sleep(0.03)
    pytest.fail("AgentScope did not persist the Wren reply in time")


def ask(client, agent_id, session_id, question, message_id):
    before = len(messages(client, agent_id, session_id)["messages"])
    response = send(client, agent_id, session_id, question, message_id)
    assert response.status_code == 200, response.text
    return wait_reply(client, agent_id, session_id, before + 2)


def envelope(client, agent_id, session_id):
    records = client.get("/sessions/", params={"agent_id": agent_id}).json()["sessions"]
    session = next(item["session"] for item in records if item["session"]["id"] == session_id)
    return session["state"]["middle_context"].get("ai_query")


def wait_inflight(client, agent_id, session_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = envelope(client, agent_id, session_id)
        if value and value.get("inflight"):
            return value
        time.sleep(0.03)
    pytest.fail("begin_turn checkpoint was not persisted")


def test_two_turns_restart_and_publication_update(session_settings):
    publisher = ActivePublication("publication-v1")
    first_wren = FakeWren()
    with make_client(session_settings, publisher, first_wren) as client:
        agent_id, session_id = create_session(client)
        first, _ = ask(client, agent_id, session_id, "共有多少人？", "message-1")
        assert first["result"]["publication_id"] == "publication-v1"
        assert first_wren.calls[0]["history"] == ()
        assert first_wren.calls[0]["session_properties"] == {
            "session_user_id": "'alice'",
            "session_workspace_id": "'conference-test'",
        }

    publisher.publication_id = "publication-v2"
    second_wren = FakeWren()
    with make_client(session_settings, publisher, second_wren) as client:
        second, _ = ask(client, agent_id, session_id, "其中来自中国的呢？", "message-2")
        assert second["result"]["publication_id"] == "publication-v2"
        assert second_wren.calls[0]["history"] == (
            {"role": "user", "content": "共有多少人？"},
            {"role": "assistant", "content": "Wren回答：共有多少人？"},
        )
        saved = envelope(client, agent_id, session_id)
        assert saved["inflight"] is None
        assert [turn["reply"]["publication_id"] for turn in saved["completed"]] == [
            "publication-v1",
            "publication-v2",
        ]


def test_duplicate_message_replays_without_second_wren_call_and_is_owner_isolated(
    session_settings,
):
    publisher, wren = ActivePublication(), FakeWren()
    with make_client(session_settings, publisher, wren) as client:
        agent_id, session_id = create_session(client)
        first, _ = ask(client, agent_id, session_id, "统计人数", "stable-message")
        before = messages(client, agent_id, session_id)["messages"]
        assert send(client, agent_id, session_id, "统计人数", "stable-message").status_code == 200
        repeated, _ = wait_reply(client, agent_id, session_id, len(before) + 1)
        assert repeated["result"] == first["result"]
        assert len(wren.calls) == 1
        before = messages(client, agent_id, session_id)["messages"]
        assert send(client, agent_id, session_id, "换一个问题", "stable-message").status_code == 200
        conflict, _ = wait_reply(client, agent_id, session_id, len(before) + 1)
        assert conflict["failure"]["code"] == "MESSAGE_ID_CONFLICT"
        assert len(wren.calls) == 1
        assert client.get(
            f"/sessions/{session_id}/messages",
            params={"agent_id": agent_id},
            headers=BOB,
        ).status_code == 404


def test_interrupt_clears_inflight_and_does_not_add_history(session_settings):
    publisher, wren = ActivePublication(), FakeWren()
    wren.block_questions.add("等待中的问题")
    with make_client(session_settings, publisher, wren) as client:
        agent_id, session_id = create_session(client)
        assert send(client, agent_id, session_id, "等待中的问题", "blocked-message").status_code == 200
        wait_inflight(client, agent_id, session_id)
        response = client.post(
            f"/sessions/{session_id}/interrupt",
            params={"agent_id": agent_id},
        )
        assert response.status_code == 202
        payload, reply = wait_reply(client, agent_id, session_id, 2)
        assert reply["finished_reason"] == "interrupted"
        assert payload["failure"]["code"] == "TURN_INTERRUPTED"
        saved = envelope(client, agent_id, session_id)
        assert saved["inflight"] is None and saved["completed"] == []


def test_wren_failure_is_saved_without_fallback(session_settings):
    publisher, wren = ActivePublication(), FakeWren()
    wren.failures["失败问题"] = AppError("WREN_UNAVAILABLE", "问数引擎暂时不可用。", 503)
    with make_client(session_settings, publisher, wren) as client:
        agent_id, session_id = create_session(client)
        payload, reply = ask(client, agent_id, session_id, "失败问题", "failed-message")
        assert reply["finished_reason"] == "error"
        assert payload["failure"]["code"] == "WREN_UNAVAILABLE"
        assert envelope(client, agent_id, session_id)["completed"] == []
        assert len(wren.calls) == 1
