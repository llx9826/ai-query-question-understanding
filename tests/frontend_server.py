"""Real platform HTTP server for frontend integration tests.

Only the external Wren boundary is deterministic here. The web routes,
AgentScope runtime, DuckDB session store and polling behavior are production code.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import create_app
from app.infrastructure.wren_http import WrenQuestionResult, WrenQuestionSource
from app.settings import Settings


class TestPublication:
    def active(self, workspace_id: str):
        return SimpleNamespace(
            workspace_id=workspace_id,
            publication_id="publication-v1",
        )


class TestWren:
    async def ask(self, **request) -> WrenQuestionResult:
        question = request["question"]
        if question == "停止测试":
            await asyncio.Event().wait()
        if "邀请国家" in question:
            columns = ("country", "total")
            rows = tuple(
                {"country": f"国家{i:02d}", "total": 20 - i}
                for i in range(1, 16)
            )
            sql = "SELECT country, COUNT(*) AS total FROM main.guests GROUP BY country"
        else:
            total = 656 if "主题大会" in question else 775
            columns = ("total",)
            rows = ({"total": total},)
            sql = "SELECT COUNT(*) AS total FROM main.guests"
        return WrenQuestionResult(
            workspace_id=request["workspace_id"],
            publication_id=request["publication_id"],
            request_id=request["request_id"],
            trace_id=f"frontend-{request['request_id']}",
            status="answered",
            answer=f"Wren 已完成：{question}",
            logical_sql=sql,
            dialect_sql=sql,
            columns=columns,
            rows=rows,
            sources=(WrenQuestionSource(
                model="guests",
                dataset_id="guest-list",
                source_name="guests.xlsx",
                sheet="Guests",
            ),),
            model_name="frontend-test-wren",
            model_calls=1,
        )


root = Path(__file__).resolve().parents[1] / ".local" / "frontend-server"
settings = Settings(
    _env_file=None,
    workspace_id="conference-test",
    session_workspace=root / "workspaces",
    control_database=root / "control.duckdb",
    dataset_root=root / "datasets",
    wren_workspace_token="frontend-test-service-token",
)
app = create_app(
    settings,
    dataset_publisher=TestPublication(),
    question_gateway=TestWren(),
)
