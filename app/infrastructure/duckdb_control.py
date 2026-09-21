"""Process-wide serialization for one DuckDB control file."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock

import duckdb

_registry_guard = Lock()
_locks: dict[Path, RLock] = {}


@dataclass
class _SharedDatabase:
    connection: duckdb.DuckDBPyConnection
    users: int


_databases: dict[Path, _SharedDatabase] = {}


def duckdb_file_lock(path: Path) -> RLock:
    resolved = path.resolve()
    with _registry_guard:
        return _locks.setdefault(resolved, RLock())


def control_database_lock(path: Path) -> RLock:
    return duckdb_file_lock(path)


def retain_control_database(path: Path) -> None:
    resolved = path.resolve()
    with _registry_guard:
        state = _databases.get(resolved)
        if state is None:
            state = _SharedDatabase(duckdb.connect(str(resolved)), 0)
            _databases[resolved] = state
        state.users += 1


def release_control_database(path: Path) -> None:
    resolved = path.resolve()
    lock = control_database_lock(resolved)
    with lock, _registry_guard:
        state = _databases.get(resolved)
        if state is None:
            return
        state.users -= 1
        if state.users == 0:
            state.connection.close()
            _databases.pop(resolved)


@contextmanager
def control_database_connection(path: Path):
    """Serialize access and reuse a retained service connection when available."""
    resolved = path.resolve()
    lock = control_database_lock(resolved)
    with lock:
        with _registry_guard:
            state = _databases.get(resolved)
        if state is not None:
            yield state.connection
            return
        connection = duckdb.connect(str(resolved))
        try:
            yield connection
        finally:
            connection.close()
