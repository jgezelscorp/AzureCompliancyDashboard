"""Deterministically generate fully synthetic golden fixtures into tests/fixtures.

Run: python scripts/generate_fixtures.py
All identifiers are placeholders; nothing here is real tenant or customer data.
"""
import json
import random
from pathlib import Path

from metrics_reference import compute

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures"
SUB = "00000000-0000-0000-0000-000000000000"
SNAPSHOT = "2026-01-15T12:00:00Z"
BASELINE_DEF = "/providers/Microsoft.Authorization/policyDefinitions/00000000-0000-0000-0000-0000000000a1"
CIS_DEF = "/providers/Microsoft.Authorization/policyDefinitions/6dcfa239-b481-4de9-a03f-980f24f3b0bb"
POLICY_ASSIGN = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/synthetic-assignment"

CATEGORIES = {
    "Account Policies": ["Minimum password length", "Maximum password age", "Password complexity", "Account lockout threshold", "Account lockout duration"],
    "Audit Policy": ["Audit logon events", "Audit account management", "Audit policy change", "Audit privilege use", "Audit process creation"],
    "Windows Firewall": ["Domain profile state", "Private profile state", "Public profile state", "Inbound connections default", "Logging dropped packets"],
    "Security Options": ["Rename administrator account", "Interactive logon message title", "Network access anonymous enumeration", "LAN Manager authentication level", "User Account Control admin approval mode"],
    "User Rights Assignment": ["Access this computer from the network", "Debug programs", "Deny log on locally", "Shut down the system", "Take ownership of files"],
    "Services": ["Print Spooler startup type", "Remote Registry startup type", "Windows Installer startup type", "Xbox services startup type", "Telnet startup type"],
    "Administrative Templates": ["AutoPlay policy", "Remote Desktop encryption level", "PowerShell script block logging", "Windows Update behavior", "Telemetry level"],
}
SEVERITIES = ["Critical", "High", "Medium", "Low"]
PHRASES = [
    "The registry key value does not match the expected value.",
    "The setting is not configured on the machine.",
    "The service startup type differs from the baseline.",
    "The audit subcategory is not enabled for failure events.",
    "The local policy value is outside the allowed range.",
]


def rid(kind, name):
    if kind == "AzureVM":
        return f"/subscriptions/{SUB}/resourcegroups/rg-synthetic/providers/microsoft.compute/virtualmachines/{name}"
    return f"/subscriptions/{SUB}/resourcegroups/rg-synthetic/providers/microsoft.hybridcompute/machines/{name}"


def machine(name, kind, eligibility="Eligible"):
    return {
        "machineId": rid(kind, name), "name": name, "kind": kind, "subscriptionId": SUB,
        "resourceGroup": "rg-synthetic", "location": "westeurope", "osType": "Windows",
        "osName": "Windows Server 2025 Datacenter (synthetic)", "osBuild": "26100",
        "eligibility": eligibility, "tags": {"owner": "synthetic-team"}, "synthetic": True,
    }


def assignment(m, family, status, checked, name):
    return {
        "assignmentId": f"{m['machineId']}/providers/microsoft.guestconfiguration/guestconfigurationassignments/{name}",
        "machineId": m["machineId"], "baselineFamily": family, "guestConfigurationName": name,
        "guestConfigurationVersion": "0.0.0-synthetic",
        "policyDefinitionId": BASELINE_DEF if family == "AzureWindowsBaseline" else CIS_DEF,
        "policyDefinitionVersion": None, "policyAssignmentId": POLICY_ASSIGN,
        "assignmentHash": "synthetic-assignment-hash", "parameterHash": "synthetic-parameter-hash",
        "contentHash": "synthetic-content-hash", "includeArcMachines": m["kind"] == "ArcMachine" or None,
        "complianceStatus": status, "lastComplianceStatusChecked": checked, "synthetic": True,
    }


def report(a, status, start, end, checks):
    return {
        "reportId": f"synthetic-report-{abs(hash_str(a['assignmentId'])) % 10**8:08d}",
        "assignmentId": a["assignmentId"], "machineId": a["machineId"],
        "baselineFamily": a["baselineFamily"], "complianceStatus": status,
        "startTime": start, "endTime": end, "operationType": "Consistency",
        "configurationVersion": a["guestConfigurationVersion"], "checks": checks, "synthetic": True,
    }


def hash_str(s):
    # Stable across runs (Python's hash() is salted).
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) % (2**61 - 1)
    return h


def policy_state(m, family, state, ts):
    return {
        "resourceId": m["machineId"], "policyAssignmentId": POLICY_ASSIGN,
        "policyDefinitionId": BASELINE_DEF if family == "AzureWindowsBaseline" else CIS_DEF,
        "policyDefinitionReferenceId": None, "baselineFamily": family,
        "complianceState": state, "isCompliant": {"Compliant": True, "NonCompliant": False}.get(state),
        "timestamp": ts, "synthetic": True,
    }


def bundle(description, machines, assignments, reports, states, exemptions, families):
    b = {
        "schemaVersion": "1.0", "synthetic": True, "description": description,
        "snapshotAt": SNAPSHOT, "machines": machines, "assignments": assignments,
        "reports": reports, "policyStates": states, "exemptions": exemptions,
    }
    b["expected"] = {f: compute(b, f) for f in families}
    return b


def write(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


def baseline_checks():
    names = []
    n = 0
    while len(names) < 373:
        for cat, settings in CATEGORIES.items():
            for s in settings:
                suffix = f" (rule {n // 35 + 1})" if n >= 35 else ""
                names.append((cat, f"{s}{suffix}"))
                n += 1
                if len(names) == 373:
                    break
            if len(names) == 373:
                break
    rng = random.Random(20260121)
    noncompliant = set(rng.sample(range(373), 264))
    checks = []
    for i, (cat, name) in enumerate(names):
        c = {"checkKey": f"synth-check-{i + 1:03d}", "name": name,
             "complianceStatus": "NonCompliant" if i in noncompliant else "Compliant",
             "category": cat, "severity": SEVERITIES[i % 4], "benchmarkControlId": None, "reasons": []}
        if i in noncompliant:
            for r in range(rng.choice([1, 1, 2, 3])):
                c["reasons"].append({"phrase": PHRASES[(i + r) % len(PHRASES)], "code": f"SYN{(i + r) % 97:03d}",
                                     "expected": "synthetic-expected", "actual": "synthetic-actual"})
        checks.append(c)
    return checks


def gen_arc_baseline():
    m = machine("arc-synth-01", "ArcMachine")
    a = assignment(m, "AzureWindowsBaseline", "NonCompliant", "2026-01-15T10:05:00Z", "AzureWindowsBaseline")
    r = report(a, "NonCompliant", "2026-01-15T10:00:00Z", "2026-01-15T10:05:00Z", baseline_checks())
    s = policy_state(m, "AzureWindowsBaseline", "NonCompliant", "2026-01-15T10:30:00Z")
    b = bundle("Synthetic Arc AzureWindowsBaseline report: 373 unique checks (109 Compliant, 264 NonCompliant); reasons are not checks.",
               [m], [a], [r], [s], [], ["AzureWindowsBaseline"])
    write("arc-azurewindowsbaseline-373.json", b)


def cis_checks(total, passing):
    checks = []
    for i in range(total):
        ok = i < passing
        checks.append({
            "checkKey": f"synth-cis-{i + 1:03d}", "name": f"Synthetic CIS-style control {i + 1:03d}",
            "complianceStatus": "Compliant" if ok else "NonCompliant", "category": None, "severity": None,
            "benchmarkControlId": None,
            "reasons": [] if ok else [{"phrase": "Synthetic reason.", "code": None, "expected": None, "actual": None}],
        })
    return checks


def gen_cis():
    fam, name = "CISWindowsSecurityBaseline", "CISWindowsSecurityBaseline"
    ms = [machine("vm-synth-01", "AzureVM"), machine("arc-synth-02", "ArcMachine"),
          machine("vm-synth-03", "AzureVM"), machine("vm-synth-04", "AzureVM"),
          machine("arc-synth-05", "ArcMachine", "Unknown"), machine("vm-synth-06", "AzureVM")]
    a1 = assignment(ms[0], fam, "Compliant", "2026-01-15T11:00:00Z", name)
    a2 = assignment(ms[1], fam, "NonCompliant", "2026-01-15T09:00:00Z", name)
    a3 = assignment(ms[2], fam, "Compliant", "2026-01-13T18:00:00Z", name)
    a6 = assignment(ms[5], fam, "Pending", None, name)
    reports = [
        report(a1, "Compliant", "2026-01-15T10:55:00Z", "2026-01-15T11:00:00Z", cis_checks(10, 10)),
        report(a2, "NonCompliant", "2026-01-15T08:55:00Z", "2026-01-15T09:00:00Z", cis_checks(10, 6)),
        report(a3, "Compliant", "2026-01-13T17:55:00Z", "2026-01-13T18:00:00Z", cis_checks(10, 10)),
    ]
    states = [policy_state(ms[0], fam, "Compliant", "2026-01-15T11:30:00Z"),
              policy_state(ms[1], fam, "NonCompliant", "2026-01-15T09:30:00Z"),
              policy_state(ms[2], fam, "Compliant", "2026-01-13T18:30:00Z"),
              policy_state(ms[5], fam, "Exempt", "2026-01-15T09:30:00Z")]
    ex = [{"exemptionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyExemptions/synthetic-exemption",
           "scope": ms[5]["machineId"], "policyAssignmentId": POLICY_ASSIGN, "category": "Waiver",
           "expiresOn": "2026-02-15T00:00:00Z", "displayName": "Synthetic exemption", "synthetic": True}]
    b = bundle("EXPLICITLY SYNTHETIC native CIS fixture (not verified CIS evidence): fresh compliant, fresh noncompliant, stale, missing assignment, unknown eligibility, no report + exempt.",
               ms, [a1, a2, a3, a6], reports, states, ex, [fam])
    write("cis-synthetic-mixed.json", b)


def gen_empty_and_dual():
    write("empty-estate.json", bundle("Synthetic empty estate: every ratio is null, never 100%.", [], [], [], [], [],
                                      ["AzureWindowsBaseline", "CISWindowsSecurityBaseline"]))
    # Same machine, both families kept distinct.
    m = machine("vm-synth-10", "AzureVM")
    aw = assignment(m, "AzureWindowsBaseline", "Compliant", "2026-01-15T11:00:00Z", "AzureWindowsBaseline")
    rw = report(aw, "Compliant", "2026-01-15T10:55:00Z", "2026-01-15T11:00:00Z", cis_checks(4, 4))
    b = bundle("Synthetic: AzureWindowsBaseline present, CIS family has no assignment; families are never merged.",
               [m], [aw], [rw], [policy_state(m, "AzureWindowsBaseline", "Compliant", "2026-01-15T11:30:00Z")], [],
               ["AzureWindowsBaseline", "CISWindowsSecurityBaseline"])
    write("dual-family-distinct.json", b)


def gen_large_estate(count):
    """Synthetic large estate (in memory only; never written). Deterministic mix per machine index."""
    fam_a, fam_c = "AzureWindowsBaseline", "CISWindowsSecurityBaseline"
    machines, assignments, reports, states = [], [], [], []
    for i in range(count):
        kind = "ArcMachine" if i % 3 == 0 else "AzureVM"
        slot = i % 10
        m = machine(f"{'arc' if kind == 'ArcMachine' else 'vm'}-load-{i:05d}", kind,
                    "Unknown" if slot == 9 else "Eligible")
        machines.append(m)
        if slot == 7:
            continue  # no assignment at all: must surface as missing evidence
        fam = fam_a if slot % 2 == 0 else fam_c
        age_hours = 60 if slot == 6 else 1  # stale beyond 24h
        end = "2026-01-12T00:00:00Z" if age_hours == 60 else "2026-01-15T11:00:00Z"
        status = "NonCompliant" if slot in (1, 2, 3) else "Compliant"
        a = assignment(m, fam, status, end, fam)
        assignments.append(a)
        if slot == 8:
            continue  # assignment without report
        passing = 8 if status == "Compliant" else 3
        reports.append(report(a, status, end, end, cis_checks(8, passing)))
        states.append(policy_state(m, fam, status, end))
    return bundle(f"Synthetic large estate of {count} machines for load testing.",
                  machines, assignments, reports, states, [], [fam_a, fam_c])


if __name__ == "__main__":
    gen_arc_baseline()
    gen_cis()
    gen_empty_and_dual()
    print("fixtures written to", OUT)
