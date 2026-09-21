"""Real DuckDB transactions, queued writes, restart, and failure reporting."""

import asyncio
import json
from datetime import datetime, timezone

import duckdb

from app.contracts.tracing import async_trace_request, trace_request, trace_stage
from app.infrastructure.query_audit.store import (
    DuckDBTraceStore,
    ThreadedDuckDBTraceStore,
    audit_completion,
)


def records(path, trace_id):
    with duckdb.connect(str(path)) as connection:
        cursor = connection.execute(
            "SELECT * FROM query_trace_requests WHERE trace_id=?", (trace_id,)
        )
        request = dict(zip((item[0] for item in cursor.description), cursor.fetchone(), strict=True))
        cursor = connection.execute(
            "SELECT * FROM query_trace_stages WHERE trace_id=? ORDER BY started_at", (trace_id,)
        )
        names = [item[0] for item in cursor.description]
        entries = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        failures = connection.execute(
            "SELECT operation,error_type FROM query_trace_write_failures WHERE trace_id=?",
            (trace_id,),
        ).fetchall()
    for item in (request, *entries):
        for name in ("metadata_json", "input_json", "output_json", "details_json", "error_json"):
            if item.get(name):
                item[name] = json.loads(item[name])
    return request, entries, failures


def test_threaded_trace_is_complete_and_survives_restart(tmp_path):
    path = tmp_path / "control.duckdb"
    audit = ThreadedDuckDBTraceStore(path)
    value = {"before": [1]}
    with trace_request(audit, question="快照") as trace:
        with trace_stage("probe", "snapshot", value) as stage:
            stage.output = value
        value["before"].append(2)
    audit.close()
    request, entries, failures = records(path, trace.trace_id)
    assert entries[0]["input_json"] == entries[0]["output_json"] == {"before": [1]}
    assert audit_completion(request, entries)["audit_complete"]
    assert not failures


def test_write_fault_keeps_truthful_incomplete_status(tmp_path, monkeypatch, caplog):
    path = tmp_path / "control.duckdb"
    audit = DuckDBTraceStore(path)
    original = audit._upsert
    fired = False

    def fail_once(table, key, columns, values):
        nonlocal fired
        if table == "query_trace_stages" and values.get("finished_at") and not fired:
            fired = True
            raise duckdb.IOException("never-log-private-query-or-key")
        return original(table, key, columns, values)

    monkeypatch.setattr(audit, "_upsert", fail_once)
    with trace_request(audit, question="固定业务输入") as trace:
        with trace_stage("module", "first", {"required": "first"}) as span:
            span.output = {"result": 1}
        with trace_stage("module", "second", {"required": "second"}) as span:
            span.output = {"result": 2}
    request, entries, failures = records(path, trace.trace_id)
    assert fired and request["logging_failed"]
    assert any(entry["stage"] == "second" and entry["finished_at"] for entry in entries)
    assert not audit.is_complete(trace.trace_id)
    assert failures == [("finish_stage", "IOException")]
    assert "never-log-private" not in caplog.text


def test_incomplete_request_and_missing_stage_never_look_complete():
    now = datetime.now(timezone.utc)
    request = {
        "finished_at": None,
        "logging_failed": False,
        "metadata_json": {"audit_expected_stages": 2},
    }
    assert audit_completion(request, [{"finished_at": now}] * 2)["audit_status"] == "incomplete"
    request["finished_at"] = now
    assert not audit_completion(request, [{"finished_at": now}])["audit_complete"]
    assert not audit_completion(request, [{"finished_at": now}, {"finished_at": None}])[
        "audit_complete"
    ]
    assert audit_completion(request, [{"finished_at": now}] * 2)["audit_complete"]


def test_flush_failure_does_not_retry_business_work(tmp_path):
    class BrokenFlush(DuckDBTraceStore):
        async def flush(self, trace_id):
            raise RuntimeError("audit-only-fault")

    audit = BrokenFlush(tmp_path / "control.duckdb")
    calls = []

    async def run():
        async with async_trace_request(audit, question="收尾故障"):
            calls.append(1)

    asyncio.run(run())
    assert calls == [1]
