from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from agentscope.app.storage import (
    AgentRecord,
    ChannelOrigin,
    CredentialRecord,
    MCPRecord,
    ScheduleOrigin,
    ScheduleRecord,
    SessionConfig,
    SessionRecord,
    SkillRecord,
    TeamRecord,
    UserOrigin,
)
from agentscope.credential import CredentialBase
from agentscope.message import Msg
from agentscope.state import AgentState
from pydantic import BaseModel, SecretStr

from app.infrastructure.duckdb_control import (
    control_database_connection,
    release_control_database,
    retain_control_database,
)


class DuckDBConversationStore:
    """Explicit AgentScope persistence for the features enabled by this service."""

    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._retained = True
        retain_control_database(self.database_path)
        self._initialize()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._retained:
            self._retained = False
            await asyncio.to_thread(release_control_database, self.database_path)

    def _initialize(self) -> None:
        with control_database_connection(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agentscope_records(
                    kind VARCHAR NOT NULL,
                    user_id VARCHAR NOT NULL,
                    record_id VARCHAR NOT NULL,
                    parent_id VARCHAR,
                    name VARCHAR,
                    source VARCHAR,
                    payload_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    PRIMARY KEY(kind,user_id,record_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agentscope_messages(
                    user_id VARCHAR NOT NULL,
                    session_id VARCHAR NOT NULL,
                    message_id VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    payload_json VARCHAR NOT NULL,
                    PRIMARY KEY(user_id,session_id,message_id)
                )
                """
            )

    async def _run(self, function, *args):
        return await asyncio.to_thread(function, *args)

    def _put_record(
        self,
        kind: str,
        user_id: str,
        record: BaseModel,
        parent_id: str | None = None,
        name: str | None = None,
        source: str | None = None,
    ) -> None:
        now = datetime.now()
        if hasattr(record, "updated_at"):
            record.updated_at = now
        created_at = getattr(record, "created_at", now)
        payload = record.model_dump_json()
        with control_database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO agentscope_records VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(kind,user_id,record_id) DO UPDATE SET
                    parent_id=excluded.parent_id,
                    name=excluded.name,
                    source=excluded.source,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    kind,
                    user_id,
                    record.id,
                    parent_id,
                    name,
                    source,
                    payload,
                    created_at,
                    now,
                ),
            )

    def _get_record(self, kind: str, user_id: str, record_id: str, model):
        with control_database_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM agentscope_records "
                "WHERE kind=? AND user_id=? AND record_id=?",
                (kind, user_id, record_id),
            ).fetchone()
        return None if row is None else model.model_validate_json(row[0])

    def _list_records(
        self,
        kind: str,
        user_id: str | None,
        model,
        parent_id: str | None = None,
        name: str | None = None,
        source: str | None = None,
    ) -> list:
        clauses = ["kind=?"]
        values: list[Any] = [kind]
        for column, value in (
            ("user_id", user_id),
            ("parent_id", parent_id),
            ("name", name),
            ("source", source),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        sql = (
            "SELECT payload_json FROM agentscope_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC"
        )
        with control_database_connection(self.database_path) as connection:
            rows = connection.execute(sql, values).fetchall()
        return [model.model_validate_json(row[0]) for row in rows]

    def _delete_record(self, kind: str, user_id: str, record_id: str) -> bool:
        with control_database_connection(self.database_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM agentscope_records "
                "WHERE kind=? AND user_id=? AND record_id=?",
                (kind, user_id, record_id),
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                "DELETE FROM agentscope_records "
                "WHERE kind=? AND user_id=? AND record_id=?",
                (kind, user_id, record_id),
            )
        return True

    async def upsert_credential(self, user_id: str, credential_data: CredentialBase) -> str:
        if not credential_data.name:
            base = credential_data.type.removesuffix("_credential").replace("_", " ").title()
            existing = await self.list_credentials(user_id)
            names = {item.data.get("name") for item in existing}
            credential_data.name = base or "Credential"
            suffix = 2
            while credential_data.name in names:
                credential_data.name = f"{base} ({suffix})"
                suffix += 1
        data = _reveal_secrets(credential_data)
        existing = await self.get_credential(user_id, credential_data.id)
        record = existing or CredentialRecord(id=credential_data.id, user_id=user_id, data=data)
        record.data = data
        await self._run(self._put_record, "credential", user_id, record)
        return record.id

    async def list_credentials(self, user_id: str) -> list[CredentialRecord]:
        return await self._run(self._list_records, "credential", user_id, CredentialRecord)

    async def get_credential(self, user_id: str, credential_id: str) -> CredentialRecord | None:
        return await self._run(
            self._get_record, "credential", user_id, credential_id, CredentialRecord
        )

    async def delete_credential(self, user_id: str, credential_id: str) -> bool:
        return await self._run(self._delete_record, "credential", user_id, credential_id)

    async def upsert_agent(self, user_id: str, agent_record: AgentRecord) -> str:
        await self._run(
            self._put_record,
            "agent",
            user_id,
            agent_record,
            None,
            None,
            agent_record.source,
        )
        return agent_record.id

    async def list_agents(self, user_id: str) -> list[AgentRecord]:
        records = await self._run(self._list_records, "agent", user_id, AgentRecord)
        return [record for record in records if record.source == "user"]

    async def get_agent(self, user_id: str, agent_id: str) -> AgentRecord | None:
        return await self._run(self._get_record, "agent", user_id, agent_id, AgentRecord)

    async def delete_agent(self, user_id: str, agent_id: str) -> bool:
        sessions = await self.list_sessions(user_id, agent_id)
        for session in sessions:
            await self.delete_session(user_id, agent_id, session.id)
        return await self._run(self._delete_record, "agent", user_id, agent_id)

    async def upsert_session(
        self,
        user_id: str,
        agent_id: str,
        config: SessionConfig,
        state: AgentState | None = None,
        session_id: str | None = None,
        origin=None,
        source: str | None = None,
        source_schedule_id: str | None = None,
        source_chat_id: str | None = None,
        source_chat_name: str | None = None,
        source_channel_id: str | None = None,
    ) -> SessionRecord:
        record = (
            await self.get_session(user_id, agent_id, session_id)
            if session_id is not None
            else None
        )
        if record is None:
            if origin is None and source == "schedule":
                origin = ScheduleOrigin(schedule_id=source_schedule_id or "")
            elif origin is None and source == "channel":
                origin = ChannelOrigin(
                    channel_id=source_channel_id or "",
                    chat_id=source_chat_id or "",
                    chat_name=source_chat_name,
                )
            record = SessionRecord(
                **({"id": session_id} if session_id else {}),
                user_id=user_id,
                agent_id=agent_id,
                config=config,
                state=state or AgentState(),
                origin=origin or UserOrigin(),
            )
        else:
            record.config = config
            if state is not None:
                record.state = state
        await self._run(
            self._put_record,
            "session",
            user_id,
            record,
            agent_id,
            record.config.name,
            record.origin.type,
        )
        return record

    async def set_session_team_id(
        self, user_id: str, session_id: str, team_id: str | None
    ) -> None:
        sessions = await self._run(self._list_records, "session", user_id, SessionRecord)
        record = next((item for item in sessions if item.id == session_id), None)
        if record is not None:
            record.team_id = team_id
            await self._run(
                self._put_record,
                "session",
                user_id,
                record,
                record.agent_id,
                record.config.name,
                record.origin.type,
            )

    async def update_session_state(
        self, user_id: str, agent_id: str, session_id: str, state: AgentState
    ) -> None:
        record = await self.get_session(user_id, agent_id, session_id)
        if record is None:
            raise KeyError(f"Session {session_id!r} not found.")
        record.state = state
        await self._run(
            self._put_record,
            "session",
            user_id,
            record,
            agent_id,
            record.config.name,
            record.origin.type,
        )

    async def list_sessions(self, user_id: str, agent_id: str) -> list[SessionRecord]:
        return await self._run(
            self._list_records,
            "session",
            user_id,
            SessionRecord,
            agent_id,
        )

    async def get_session(
        self, user_id: str, agent_id: str, session_id: str | None
    ) -> SessionRecord | None:
        if session_id is None:
            return None
        record = await self._run(
            self._get_record, "session", user_id, session_id, SessionRecord
        )
        if record is None or (agent_id and record.agent_id != agent_id):
            return None
        return record

    async def delete_session(self, user_id: str, agent_id: str, session_id: str) -> bool:
        record = await self.get_session(user_id, agent_id, session_id)
        if record is None:
            return False
        with control_database_connection(self.database_path) as connection:
            connection.execute(
                "DELETE FROM agentscope_messages WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            )
        return await self._run(self._delete_record, "session", user_id, session_id)

    async def list_sessions_by_schedule(
        self, user_id: str, schedule_id: str
    ) -> list[SessionRecord]:
        records = await self._run(self._list_records, "session", user_id, SessionRecord)
        return [
            record
            for record in records
            if record.origin.type == "schedule" and record.origin.schedule_id == schedule_id
        ]

    async def list_sessions_by_channel(
        self, user_id: str, channel_id: str
    ) -> list[SessionRecord]:
        records = await self._run(self._list_records, "session", user_id, SessionRecord)
        return [
            record
            for record in records
            if record.origin.type == "channel" and record.origin.channel_id == channel_id
        ]

    async def upsert_message(self, user_id: str, session_id: str, msg: Msg) -> None:
        await self._run(self._upsert_message, user_id, session_id, msg)

    def _upsert_message(self, user_id: str, session_id: str, msg: Msg) -> None:
        with control_database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO agentscope_messages VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,session_id,message_id) DO UPDATE SET
                    payload_json=excluded.payload_json
                """,
                (user_id, session_id, msg.id, datetime.now(), msg.model_dump_json()),
            )

    async def get_message(
        self, user_id: str, session_id: str, message_id: str
    ) -> Msg | None:
        def read():
            with control_database_connection(self.database_path) as connection:
                row = connection.execute(
                    "SELECT payload_json FROM agentscope_messages "
                    "WHERE user_id=? AND session_id=? AND message_id=?",
                    (user_id, session_id, message_id),
                ).fetchone()
            return None if row is None else Msg.model_validate_json(row[0])

        return await self._run(read)

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        **kwargs,
    ) -> tuple[list[Msg], bool]:
        del kwargs

        def read():
            with control_database_connection(self.database_path) as connection:
                if before is not None:
                    cursor = connection.execute(
                        "SELECT created_at,message_id FROM agentscope_messages "
                        "WHERE user_id=? AND session_id=? AND message_id=?",
                        (user_id, session_id, before),
                    ).fetchone()
                    if cursor is None:
                        return [], False
                    rows = connection.execute(
                        "SELECT payload_json FROM agentscope_messages "
                        "WHERE user_id=? AND session_id=? "
                        "AND (created_at<? OR (created_at=? AND message_id<?)) "
                        "ORDER BY created_at DESC,message_id DESC LIMIT ?",
                        (user_id, session_id, cursor[0], cursor[0], cursor[1], limit + 1),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT payload_json FROM agentscope_messages "
                        "WHERE user_id=? AND session_id=? "
                        "ORDER BY created_at DESC,message_id DESC LIMIT ?",
                        (user_id, session_id, limit + 1),
                    ).fetchall()
            has_more = len(rows) > limit
            page = rows[:limit]
            page.reverse()
            return [Msg.model_validate_json(row[0]) for row in page], has_more

        return await self._run(read)

    async def upsert_mcp(self, user_id: str, record: MCPRecord) -> str:
        await self._run(self._put_record, "mcp", user_id, record, None, record.name)
        return record.id

    async def list_mcps(self, user_id: str) -> list[MCPRecord]:
        return await self._run(self._list_records, "mcp", user_id, MCPRecord)

    async def get_mcp(self, user_id: str, record_id: str) -> MCPRecord | None:
        return await self._run(self._get_record, "mcp", user_id, record_id, MCPRecord)

    async def get_mcp_by_name(self, user_id: str, name: str) -> MCPRecord | None:
        records = await self._run(self._list_records, "mcp", user_id, MCPRecord, None, name)
        return records[0] if records else None

    async def delete_mcp(self, user_id: str, record_id: str) -> bool:
        return await self._run(self._delete_record, "mcp", user_id, record_id)

    async def upsert_skill(self, user_id: str, record: SkillRecord) -> str:
        await self._run(self._put_record, "skill", user_id, record, None, record.name)
        return record.id

    async def list_skills(self, user_id: str) -> list[SkillRecord]:
        return await self._run(self._list_records, "skill", user_id, SkillRecord)

    async def get_skill(self, user_id: str, record_id: str) -> SkillRecord | None:
        return await self._run(self._get_record, "skill", user_id, record_id, SkillRecord)

    async def get_skill_by_name(self, user_id: str, name: str) -> SkillRecord | None:
        records = await self._run(
            self._list_records, "skill", user_id, SkillRecord, None, name
        )
        return records[0] if records else None

    async def delete_skill(self, user_id: str, record_id: str) -> bool:
        return await self._run(self._delete_record, "skill", user_id, record_id)

    async def upsert_schedule(self, user_id: str, record: ScheduleRecord) -> str:
        await self._run(self._put_record, "schedule", user_id, record, record.agent_id)
        return record.id

    async def get_schedule(self, user_id: str, record_id: str) -> ScheduleRecord | None:
        return await self._run(
            self._get_record, "schedule", user_id, record_id, ScheduleRecord
        )

    async def list_schedules(self, user_id: str) -> list[ScheduleRecord]:
        return await self._run(self._list_records, "schedule", user_id, ScheduleRecord)

    async def list_all_schedules(self) -> list[ScheduleRecord]:
        return await self._run(self._list_records, "schedule", None, ScheduleRecord)

    async def delete_schedule(self, user_id: str, record_id: str) -> bool:
        for session in await self.list_sessions_by_schedule(user_id, record_id):
            await self.delete_session(user_id, session.agent_id, session.id)
        return await self._run(self._delete_record, "schedule", user_id, record_id)

    async def upsert_team(self, user_id: str, record: TeamRecord) -> TeamRecord:
        await self._run(self._put_record, "team", user_id, record)
        return record

    async def get_team(self, user_id: str, record_id: str) -> TeamRecord | None:
        return await self._run(self._get_record, "team", user_id, record_id, TeamRecord)

    async def list_teams(self, user_id: str) -> list[TeamRecord]:
        return await self._run(self._list_records, "team", user_id, TeamRecord)

    async def delete_team(self, user_id: str, record_id: str) -> bool:
        return await self._run(self._delete_record, "team", user_id, record_id)


def _reveal_secrets(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, BaseModel):
        return _reveal_secrets(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {key: _reveal_secrets(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_reveal_secrets(item) for item in value]
    return value
