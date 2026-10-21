"""Static guards for the workbook: constructs Azure Resource Graph rejects or silently truncates."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_workbook import arg_unsupported, strip_strings  # noqa: E402
from workbook_lib import KNOWN_PARAMETERS, WORKBOOK_PATH, load_queries  # noqa: E402

ARG_QUERIES = [q for q in load_queries() if q["source"] == "arg"]


@pytest.mark.parametrize("q", ARG_QUERIES, ids=lambda q: q["id"])
def test_arg_query_uses_only_supported_constructs(q):
    assert arg_unsupported(strip_strings(q["query"])) == []


@pytest.mark.parametrize("q", ARG_QUERIES, ids=lambda q: q["id"])
def test_arg_query_is_a_single_pipeline(q):
    first = q["query"].lstrip().splitlines()[0]
    assert re.match(r"(resources|policyresources|guestconfigurationresources|resourcecontainers)\b", first)
    assert ";" not in strip_strings(q["query"])


def test_every_placeholder_is_a_declared_parameter():
    workbook = json.loads(WORKBOOK_PATH.read_text(encoding="utf-8"))
    declared = {p["name"] for it in workbook["items"] if it["type"] == 9 for p in it["content"]["parameters"]}
    used = {m for q in ARG_QUERIES for m in re.findall(r"\{(\w+)\}", q["query"])}
    assert used <= declared
    assert used <= KNOWN_PARAMETERS


def test_definition_id_defaults_are_real_builtin_guids():
    workbook = json.loads(WORKBOOK_PATH.read_text(encoding="utf-8"))
    params = {p["name"]: p for it in workbook["items"] if it["type"] == 9 for p in it["content"]["parameters"]}
    assert params["CisDefinitionId"]["value"] == "6dcfa239-b481-4de9-a03f-980f24f3b0bb"
    assert params["AzureBaselineDefinitionId"]["value"] == "72650e9f-97bc-4b2a-ab5f-9781a9fcecbc"
    assert params["Workspace"]["value"] == "__DEFAULT_WORKSPACE_RESOURCE_ID__"
