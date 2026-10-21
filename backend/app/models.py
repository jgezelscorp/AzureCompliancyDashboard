"""Typed API models mirroring contracts/schemas (camelCase on the wire)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

BaselineFamily = Literal["AzureWindowsBaseline", "CISWindowsSecurityBaseline", "Other", "Unknown"]
MachineKind = Literal["AzureVM", "ArcMachine"]
ComplianceState = Literal["Compliant", "NonCompliant", "Pending", "Unknown"]
Eligibility = Literal["Eligible", "NotEligible", "Unknown"]
Severity = Literal["Critical", "High", "Medium", "Low", "Informational"]
GUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Machine(ApiModel):
    machine_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: MachineKind
    subscription_id: str = Field(pattern=GUID_PATTERN)
    resource_group: str = Field(min_length=1)
    location: str | None = None
    os_type: Literal["Windows", "Linux", "Unknown"]
    os_name: str | None = None
    os_build: str | None = None
    eligibility: Eligibility
    tags: dict[str, str] | None = None
    synthetic: Literal[True] | None = None


class Assignment(ApiModel):
    assignment_id: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    baseline_family: BaselineFamily
    guest_configuration_name: str = Field(min_length=1)
    guest_configuration_version: str | None = None
    policy_definition_id: str | None = None
    policy_definition_version: str | None = None
    policy_assignment_id: str | None = None
    assignment_hash: str | None = None
    parameter_hash: str | None = None
    content_hash: str | None = None
    include_arc_machines: bool | None = None
    compliance_status: ComplianceState
    last_compliance_status_checked: datetime | None = None
    synthetic: Literal[True] | None = None


class CheckReason(ApiModel):
    phrase: str
    code: str | None = None
    expected: str | None = None
    actual: str | None = None


class Check(ApiModel):
    check_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    compliance_status: Literal["Compliant", "NonCompliant"]
    category: str | None = None
    category_source: Literal["source", "derived", "override", "unmapped"] | None = None
    category_rule_version: int | None = None
    severity: Severity | None = None
    benchmark_control_id: str | None = None
    reasons: list[CheckReason]


class Report(ApiModel):
    report_id: str = Field(min_length=1)
    assignment_id: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    baseline_family: BaselineFamily
    compliance_status: ComplianceState
    start_time: datetime
    end_time: datetime
    operation_type: str | None = None
    configuration_version: str | None = None
    checks: list[Check]
    synthetic: Literal[True] | None = None


class PolicyState(ApiModel):
    resource_id: str = Field(min_length=1)
    policy_assignment_id: str = Field(min_length=1)
    policy_definition_id: str = Field(min_length=1)
    policy_definition_reference_id: str | None = None
    baseline_family: BaselineFamily | None = None
    compliance_state: Literal[
        "Compliant", "NonCompliant", "Exempt", "Conflict", "NotStarted", "Unknown"
    ]
    is_compliant: bool | None = None
    timestamp: datetime
    synthetic: Literal[True] | None = None


class Exemption(ApiModel):
    exemption_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    policy_assignment_id: str = Field(min_length=1)
    category: Literal["Waiver", "Mitigated"]
    expires_on: datetime | None = None
    display_name: str | None = None
    synthetic: Literal[True] | None = None


class EvidenceBundle(ApiModel):
    """Collector output; fixture-only `expected` metadata is ignored by the API."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    schema_version: str
    synthetic: Literal[True] | None = None
    description: str | None = None
    snapshot_at: datetime | None = None
    machines: list[Machine] = Field(default_factory=list)
    assignments: list[Assignment] = Field(default_factory=list)
    reports: list[Report] = Field(default_factory=list)
    policy_states: list[PolicyState] = Field(default_factory=list)
    exemptions: list[Exemption] = Field(default_factory=list)


class HealthResponse(ApiModel):
    status: Literal["ok"]
    version: str


class InfoResponse(ApiModel):
    version: str
    environment: str
    freshness_hours: int
    retention_months: int
    subscription_count: int


class BundleSummary(ApiModel):
    machines: int
    assignments: int
    reports: int
    checks: int
    policy_states: int
    exemptions: int
    synthetic: bool
