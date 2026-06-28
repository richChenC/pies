from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core.models import ProbeRecord, ProbeStatistics


@dataclass
class DatasetState:
    records: list[ProbeRecord] = field(default_factory=list)
    statistics: dict[str, ProbeStatistics] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    warning_groups: dict[tuple[Any, ...], dict[str, Any]] = field(default_factory=dict)
    deduplication_info: dict[str, Any] = field(default_factory=dict)
    error_records: list[dict[str, Any]] = field(default_factory=list)
    import_summaries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AppState:
    folder_path: str = ""
    file_path: str = ""
    current_scope: str = "current"
    current_view: str = "split"
    history_enabled: bool = True
    current: DatasetState = field(default_factory=DatasetState)
    history: DatasetState = field(default_factory=DatasetState)
