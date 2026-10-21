"""Logs table schema (contracts/logs-schema.json, packaged copy) and row validation."""

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("logs-schema.json")

RUNS = "ComplianceCollectionRuns_CL"
SNAPSHOTS = "PolicyComplianceSnapshots_CL"
REPORTS = "MachineConfigReports_CL"
CHECKS = "MachineConfigChecks_CL"
SERVER_FILLED = {"SentAt"}  # set by the sender on every attempt, never stored in the outbox


@dataclass(frozen=True)
class Table:
    name: str
    stream: str
    columns: dict[str, str]


@lru_cache
def load_schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return data


@lru_cache
def tables() -> dict[str, Table]:
    schema = load_schema()
    prefix = schema["streamPrefix"]
    return {
        t["name"]: Table(
            t["name"], prefix + t["name"], {c["name"]: c["type"] for c in t["columns"]}
        )
        for t in schema["tables"]
    }


def schema_version() -> str:
    return str(load_schema()["schemaVersion"])


def api_version() -> str:
    return str(load_schema()["ingestionApiVersion"])


_CHECKS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "datetime": lambda v: isinstance(v, str) and v.endswith("Z") and datetime.fromisoformat(v[:-1]),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "long": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "real": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "dynamic": lambda v: True,
}


def validate_row(table: str, row: dict[str, Any], *, sent: bool = False) -> None:
    """Raise ValueError if a row has unknown columns, missing columns or wrongly typed values."""
    spec = tables()[table]
    unknown = set(row) - set(spec.columns)
    if unknown:
        raise ValueError(f"{table}: unknown columns {sorted(unknown)}")
    required = set(spec.columns) - (set() if sent else SERVER_FILLED)
    missing = required - set(row)
    if missing:
        raise ValueError(f"{table}: missing columns {sorted(missing)}")
    for name, value in row.items():
        if value is None:
            continue
        if not _CHECKS[spec.columns[name]](value):
            raise ValueError(f"{table}.{name}: value does not match type {spec.columns[name]}")
