"""DuckDB query audit storage with one explicit write queue."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.infrastructure.duckdb_control import (
    control_database_connection,
    release_control_database,
    retain_control_database,
)

logger = logging.getLogger(__name__)


def audit_completion(row, entries, *, active=False):
    """A trace is complete only when its request and every expected stage finished."""
    expected = (row.get("metadata_json") or {}).get("audit_expected_stages") if row else None
    complete = bool(
        row
        and row["finished_at"]
        and not row["logging_failed"]
        and expected == len(entries)
        and all(entry["finished_at"] for entry in entries)
    )
    state = (
        "complete"
        if complete
        else "failed"
        if row and row["logging_failed"]
        else "pending"
        if active
        else "incomplete"
    )
    return {
        "audit_status": state,
        "audit_complete": complete,
        "expected_stages": expected,
        "persisted_stages": len(entries),
    }


REQUEST_COLUMNS = (
    "trace_id", "session_id", "user_id", "source_id", "question", "status",
    "started_at", "finished_at", "duration_ms", "metadata_json", "output_json",
    "error_json", "failed_module", "failed_stage", "logging_failed",
)
STAGE_COLUMNS = (
    "stage_id", "trace_id", "parent_stage_id", "module", "stage", "status",
    "started_at", "finished_at", "duration_ms", "input_json", "output_json",
    "details_json", "error_json",
)
JSON_COLUMNS = frozenset(
    {"metadata_json", "output_json", "error_json", "input_json", "details_json"}
)


class DuckDBTraceStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._retained = True
        retain_control_database(self.database_path)
        self._failed_traces: set[str] = set()
        self._initialize()

    def _connect(self):
        return control_database_connection(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS query_trace_requests(
                    trace_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    user_id VARCHAR,
                    source_id VARCHAR,
                    question VARCHAR,
                    status VARCHAR NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP,
                    duration_ms BIGINT,
                    metadata_json VARCHAR,
                    output_json VARCHAR,
                    error_json VARCHAR,
                    failed_module VARCHAR,
                    failed_stage VARCHAR,
                    logging_failed BOOLEAN NOT NULL DEFAULT false
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS query_trace_stages(
                    stage_id VARCHAR PRIMARY KEY,
                    trace_id VARCHAR NOT NULL,
                    parent_stage_id VARCHAR,
                    module VARCHAR NOT NULL,
                    stage VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP,
                    duration_ms BIGINT,
                    input_json VARCHAR,
                    output_json VARCHAR,
                    details_json VARCHAR,
                    error_json VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS query_trace_write_failures(
                    failure_id VARCHAR PRIMARY KEY,
                    trace_id VARCHAR NOT NULL,
                    stage_id VARCHAR,
                    module VARCHAR,
                    stage VARCHAR,
                    operation VARCHAR NOT NULL,
                    error_type VARCHAR NOT NULL,
                    failed_at TIMESTAMP NOT NULL
                )
                """
            )

    @staticmethod
    def _decode_row(cursor, row):
        if row is None:
            return None
        result = dict(zip((item[0] for item in cursor.description), row, strict=True))
        for name in JSON_COLUMNS:
            if result.get(name) is not None:
                result[name] = json.loads(result[name])
        return result

    @staticmethod
    def _database_value(name, value):
        if name in JSON_COLUMNS and value is not None:
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    def _upsert(self, table, key, columns, values):
        with self._connect() as connection:
            cursor = connection.execute(
                f"SELECT * FROM {table} WHERE {key}=?", (values[key],)
            )
            current = self._decode_row(cursor, cursor.fetchone()) or {}
            merged = {name: values.get(name, current.get(name)) for name in columns}
            if table == "query_trace_requests":
                merged["logging_failed"] = bool(
                    values.get("logging_failed")
                    or current.get("logging_failed")
                    or values["trace_id"] in self._failed_traces
                )
            placeholders = ",".join("?" for _ in columns)
            updates = ",".join(f"{name}=excluded.{name}" for name in columns if name != key)
            connection.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders}) "
                f"ON CONFLICT({key}) DO UPDATE SET {updates}",
                [self._database_value(name, merged[name]) for name in columns],
            )

    def _write(self, operation, table, key, columns, values):
        trace_id = values["trace_id"]
        try:
            self._upsert(table, key, columns, values)
            if operation == "finish_request":
                self._failed_traces.discard(trace_id)
            return True
        except Exception as exc:
            self._failed_traces.add(trace_id)
            logger.error(
                "audit_write_failed trace_id=%s stage_id=%s operation=%s type=%s",
                trace_id,
                values.get("stage_id"),
                operation,
                type(exc).__name__,
            )
            failure = {
                "failure_id": uuid4().hex,
                "trace_id": trace_id,
                "stage_id": values.get("stage_id"),
                "module": values.get("module"),
                "stage": values.get("stage"),
                "operation": operation,
                "error_type": type(exc).__name__,
                "failed_at": datetime.now(timezone.utc),
            }
            try:
                self._upsert(
                    "query_trace_write_failures", "failure_id", tuple(failure), failure
                )
            except Exception:
                pass
            return False

    def start_request(self, values):
        return self._write(
            "start_request", "query_trace_requests", "trace_id", REQUEST_COLUMNS, values
        )

    def finish_request(self, trace_id, values):
        return self._write(
            "finish_request", "query_trace_requests", "trace_id", REQUEST_COLUMNS,
            {**values, "trace_id": trace_id},
        )

    def start_stage(self, values):
        return self._write(
            "start_stage", "query_trace_stages", "stage_id", STAGE_COLUMNS, values
        )

    def finish_stage(self, stage_id, values):
        return self._write(
            "finish_stage", "query_trace_stages", "stage_id", STAGE_COLUMNS,
            {**values, "stage_id": stage_id},
        )

    def _request(self, trace_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM query_trace_requests WHERE trace_id=?", (trace_id,)
            )
            return self._decode_row(cursor, cursor.fetchone())

    def _stages(self, trace_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM query_trace_stages WHERE trace_id=? ORDER BY started_at",
                (trace_id,),
            )
            rows = cursor.fetchall()
            names = [item[0] for item in cursor.description]
        result = []
        for row in rows:
            item = dict(zip(names, row, strict=True))
            for name in JSON_COLUMNS:
                if item.get(name) is not None:
                    item[name] = json.loads(item[name])
            result.append(item)
        return result

    def is_complete(self, trace_id):
        if trace_id in self._failed_traces:
            return False
        try:
            return audit_completion(self._request(trace_id), self._stages(trace_id))[
                "audit_complete"
            ]
        except Exception:
            return False

    def read_progress(self, session_id, user_id, expected_trace, *, active):
        if expected_trace:
            row = self._request(expected_trace)
            if row is not None and (
                row["session_id"] != session_id or row["user_id"] != user_id
            ):
                row = None
        else:
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT * FROM query_trace_requests "
                    "WHERE session_id=? AND user_id=? ORDER BY started_at DESC LIMIT 1",
                    (session_id, user_id),
                )
                row = self._decode_row(cursor, cursor.fetchone())
        if row is None:
            return (
                {
                    "trace_id": expected_trace,
                    "status": "running" if active else "incomplete",
                    **audit_completion(None, [], active=active),
                    "stages": [],
                    "model_calls": 0,
                }
                if expected_trace
                else None
            )
        entries = self._stages(row["trace_id"])
        projected = [
            {
                key: entry[key]
                for key in ("module", "stage", "status", "duration_ms", "finished_at")
            }
            for entry in entries
        ]
        return {
            **{key: value for key, value in row.items() if key != "metadata_json"},
            **audit_completion(row, entries, active=active),
            "stages": projected,
            "model_calls": sum(entry["stage"] == "model_call" for entry in entries),
        }

    async def flush(self, trace_id):
        return await asyncio.to_thread(self.is_complete, trace_id)

    def close(self):
        if self._retained:
            self._retained = False
            release_control_database(self.database_path)


class ThreadedDuckDBTraceStore(DuckDBTraceStore):
    """Serialize audit writes and let request handling continue until flush."""

    def __init__(self, database_path: Path):
        super().__init__(database_path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="duckdb-audit")

    def _submit(self, method, *args):
        self._executor.submit(method, *deepcopy(args))

    def start_request(self, values):
        self._submit(super().start_request, values)

    def finish_request(self, trace_id, values):
        self._submit(super().finish_request, trace_id, values)

    def start_stage(self, values):
        self._submit(super().start_stage, values)

    def finish_stage(self, stage_id, values):
        self._submit(super().finish_stage, stage_id, values)

    async def flush(self, trace_id):
        future = self._executor.submit(self.is_complete, trace_id)
        try:
            async with asyncio.timeout(5):
                return await asyncio.shield(asyncio.wrap_future(future))
        except TimeoutError:
            logger.error("audit_flush_timeout trace_id=%s", trace_id)
            return False

    def close(self):
        self._executor.shutdown(wait=True)
