"""Helpers for loading RAG configuration from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def _expand_path(value: str, base_dir: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config and expand known filesystem paths."""
    path = Path(config_path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    base_dir = path.parent
    data_sources = config.setdefault("data_sources", {})
    for key, value in list(data_sources.items()):
        if value:
            data_sources[key] = _expand_path(value, base_dir)

    rag_db_path = config.get("rag_db_path", "rag.db")
    config["rag_db_path"] = _expand_path(rag_db_path, base_dir)
    config["_config_path"] = str(path)
    return config
