"""Write a standard Wren v5 project beside an immutable DuckDB publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

KNOWLEDGE_DIRECTORIES = ("caveats", "glossary", "metrics", "rules", "sql")


def write_wren_project(
    project_path: Path,
    *,
    workspace_id: str,
    publication_id: str,
    models: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
) -> None:
    relationships = relationships or []
    project = {
        "schema_version": 5,
        "name": f"{workspace_id}_{publication_id}",
        "version": publication_id,
        "catalog": "wren",
        "schema": "main",
        "data_source": "duckdb",
    }
    _write_yaml(project_path / "wren_project.yml", project)
    _write_yaml(
        project_path / "relationships.yml",
        {"relationships": relationships},
    )
    (project_path / "views").mkdir(exist_ok=True)
    (project_path / "cubes").mkdir(exist_ok=True)

    primary_keys = _primary_keys(relationships)
    for model in models:
        metadata = {
            "name": model["name"],
            "properties": {"description": model["description"]},
            "table_reference": {
                "catalog": "data",
                "schema": "main",
                "table": model["tableReference"]["table"],
            },
            "columns": [
                {
                    "name": column["name"],
                    "type": column["type"],
                    "is_calculated": False,
                    "is_primary_key": column["name"]
                    == primary_keys.get(model["name"]),
                    "not_null": False,
                    "properties": {
                        "description": f"Excel column {column['name']}"
                    },
                }
                for column in model["columns"]
            ],
            "cached": False,
        }
        if model["name"] in primary_keys:
            metadata["primary_key"] = primary_keys[model["name"]]
        _write_yaml(
            project_path / "models" / model["name"] / "metadata.yml",
            metadata,
        )

    knowledge = project_path / "knowledge"
    _write_yaml(knowledge / "knowledge.yml", {"schema_version": 1})
    for name in KNOWLEDGE_DIRECTORIES:
        directory = knowledge / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").write_text("", encoding="utf-8")
    (knowledge / "rules" / "general.md").write_text(
        "# Query rules\n\n"
        "Use Wren model names and model relationships. "
        "Treat source file and sheet descriptions as provenance only.\n",
        encoding="utf-8",
    )


def _primary_keys(relationships: list[dict[str, Any]]) -> dict[str, str]:
    keys: dict[str, str] = {}
    for relationship in relationships:
        left, right = relationship["models"]
        left_expression, right_expression = relationship["condition"].split("=", 1)
        left_column = left_expression.strip().split(".", 1)[1]
        right_column = right_expression.strip().split(".", 1)[1]
        join_type = relationship["join_type"]
        if join_type in {"ONE_TO_ONE", "ONE_TO_MANY"}:
            keys[left] = left_column
        if join_type in {"ONE_TO_ONE", "MANY_TO_ONE"}:
            keys[right] = right_column
    return keys


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
