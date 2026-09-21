"""Reserved source boundary for a future Feishu change detector."""

from typing import Protocol

from app.contracts.base import DTO
from app.modules.datasets import WorkbookUpload


class SourceSnapshot(DTO):
    source_id: str
    source_version: str
    uploads: tuple[WorkbookUpload, ...]


class SourceAdapter(Protocol):
    async def fetch_changed(self, cursor: str | None) -> SourceSnapshot | None: ...
