from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.contracts.base import DTO


class WorkbookUpload(DTO):
    filename: str = Field(min_length=1, max_length=255)
    content: bytes = Field(min_length=1)
    dataset_id: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"
    )


class DatasetRecord(DTO):
    dataset_id: str
    source_name: str
    content_hash: str
    source_path: Path
    tables: tuple[dict[str, Any], ...]


class RelationshipInput(DTO):
    left_model: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    left_column: str = Field(min_length=1, max_length=255)
    right_model: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    right_column: str = Field(min_length=1, max_length=255)
    join_type: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"]


class RelationshipDefinition(DTO):
    name: str
    models: tuple[str, str]
    join_type: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"]
    condition: str


class PublicationCandidate(DTO):
    workspace_id: str
    publication_id: str
    base_publication_id: str | None
    database_path: Path
    project_path: Path
    project_relative_path: Path
    signature: str
    datasets: tuple[DatasetRecord, ...]
    relationships: tuple[RelationshipDefinition, ...] = ()
    changed: bool = True


class DatasetSummary(DTO):
    dataset_id: str
    source_name: str
    content_hash: str
    tables: tuple[dict[str, Any], ...]


class PublicationResult(DTO):
    workspace_id: str
    publication_id: str
    changed: bool
    datasets: tuple[DatasetSummary, ...]
    relationships: tuple[RelationshipDefinition, ...] = ()


class PublicationSummary(DTO):
    publication_id: str
    created_at: str
    active: bool
    datasets: tuple[DatasetSummary, ...]
    relationships: tuple[RelationshipDefinition, ...] = ()
