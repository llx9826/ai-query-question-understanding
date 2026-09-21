import time

from tests.test_sessions import (
    ALICE,
    BOB,
    ActivePublication,
    FakeWren,
    make_client,
)
from tests.test_sessions import session_settings as session_settings


def test_web_uses_wren_result_and_restores_session(session_settings):
    publisher, wren = ActivePublication(), FakeWren()
    with make_client(session_settings, publisher, wren) as client:
        assert client.get("/ui-api/health").status_code == 200
        assert client.post("/ui-api/bootstrap", headers={"Authorization": ""}).status_code == 401
        info = client.post("/ui-api/bootstrap").json()
        assert info["wren_configured"]
        agent_id = info["agent_id"]
        created = client.post(
            "/ui-api/sessions",
            json={"agent_id": agent_id, "name": "网页会话"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        body = {
            "agent_id": agent_id,
            "message_id": "web-message-1",
            "question": "共有多少人？",
        }
        assert client.post(f"/ui-api/sessions/{session_id}/chat", json=body).status_code == 200
        for _ in range(150):
            snapshot = client.get(
                f"/ui-api/sessions/{session_id}/snapshot",
                params={"agent_id": agent_id},
            ).json()
            if not snapshot["is_running"] and len(snapshot["messages"]) >= 2:
                break
            time.sleep(0.03)
        reply = snapshot["messages"][-1]["reply"]
        assert reply["result"]["answer"] == "Wren回答：共有多少人？"
        assert reply["result"]["rows"] == [{"total": 1}]
        assert reply["publication_id"] == "publication-v1"
        assert any(stage["stage"] == "call_wren" for stage in snapshot["progress"]["stages"])
        assert "input_json" not in str(snapshot["progress"])
        assert client.get(
            f"/ui-api/sessions/{session_id}/snapshot",
            params={"agent_id": agent_id},
            headers=BOB,
        ).status_code in (403, 404)
        assert client.patch(
            f"/ui-api/sessions/{session_id}",
            json={"agent_id": agent_id, "name": "已重命名"},
            headers=ALICE,
        ).status_code == 200

    with make_client(session_settings, publisher, FakeWren()) as client:
        rows = client.get("/ui-api/sessions", params={"agent_id": agent_id}).json()["sessions"]
        assert rows[0]["name"] == "已重命名"
        restored = client.get(
            f"/ui-api/sessions/{session_id}/snapshot",
            params={"agent_id": agent_id},
        ).json()
        assert restored["messages"][-1]["reply"]["result"]["publication_id"] == "publication-v1"


def test_web_binds_each_session_to_an_authorized_workspace(session_settings):
    publisher, wren = ActivePublication(), FakeWren()
    with make_client(session_settings, publisher, wren) as client:
        info = client.post("/ui-api/bootstrap").json()
        assert [item["workspace_id"] for item in info["workspaces"]] == [
            "conference-test",
            "conference-other",
        ]
        created = client.post(
            "/ui-api/sessions",
            json={
                "agent_id": info["agent_id"],
                "name": "另一个大会",
                "workspace_id": "conference-other",
            },
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        response = client.post(
            f"/ui-api/sessions/{session_id}/chat",
            json={
                "agent_id": info["agent_id"],
                "message_id": "other-workspace-message",
                "question": "这个大会有多少人？",
            },
        )
        assert response.status_code == 200, response.text
        for _ in range(150):
            snapshot = client.get(
                f"/ui-api/sessions/{session_id}/snapshot",
                params={"agent_id": info["agent_id"]},
            ).json()
            if not snapshot["is_running"] and len(snapshot["messages"]) >= 2:
                break
            time.sleep(0.03)
        assert wren.calls[0]["workspace_id"] == "conference-other"
        sessions = client.get(
            "/ui-api/sessions", params={"agent_id": info["agent_id"]}
        ).json()["sessions"]
        assert sessions[0]["workspace_id"] == "conference-other"
        forbidden = client.post(
            "/ui-api/sessions",
            json={
                "agent_id": info["agent_id"],
                "name": "越权",
                "workspace_id": "conference-other",
            },
            headers=BOB,
        )
        assert forbidden.status_code == 404
