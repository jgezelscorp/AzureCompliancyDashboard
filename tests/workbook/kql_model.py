"""Python model of the workbook KQL, evaluated over ARG-shaped rows built from the golden fixtures.

There is no KQL engine in CI, so this module mirrors the queries in workbooks/queries/_fragments and
01-ovw-*.kql step by step (same columns, same grouping, same null handling). tests assert it equals
scripts/metrics_reference.py. It proves the *logic* matches; it cannot prove the KQL text parses or
that the live ARG projection exposes the same properties (see docs/workbook.md).
"""
from datetime import datetime, timedelta, timezone

FAMILIES = ("AzureWindowsBaseline", "CISWindowsSecurityBaseline")
EPOCH = datetime(1900, 1, 1, tzinfo=timezone.utc)


def ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def to_arg_rows(bundle, cis_def="6dcfa239-b481-4de9-a03f-980f24f3b0bb",
                azure_def="00000000-0000-0000-0000-0000000000a1"):
    """Shape a normalized bundle like the Resource Graph tables the queries read."""
    resources = []
    for m in bundle["machines"]:
        props = {}
        # Fixture eligibility is the authority: Unknown means the OS evidence is absent from ARG.
        os_type = {"Eligible": "Windows", "NotEligible": "Linux"}.get(m["eligibility"])
        if os_type:
            if m["kind"] == "ArcMachine":
                props["osType"] = os_type.lower()
            else:
                props["storageProfile"] = {"osDisk": {"osType": os_type}}
        resources.append({
            "id": m["machineId"], "name": m["name"], "subscriptionId": m["subscriptionId"],
            "resourceGroup": m["resourceGroup"],
            "type": "microsoft.hybridcompute/machines" if m["kind"] == "ArcMachine"
            else "microsoft.compute/virtualmachines",
            "properties": props,
        })
    guest = []
    for a in bundle["assignments"]:
        mine = [r for r in bundle["reports"] if r["assignmentId"] == a["assignmentId"]]
        latest = None
        if mine:
            r = max(mine, key=lambda x: x["endTime"])
            latest = {
                "endTime": r.get("endTime"), "complianceStatus": r["complianceStatus"],
                "resources": [{
                    "resourceId": c["checkKey"], "complianceStatus": c["complianceStatus"] == "Compliant",
                    "reasons": [{"code": x.get("code"), "phrase": x["phrase"]} for x in c["reasons"]],
                } for c in r["checks"]],
            }
        guest.append({
            "id": a["assignmentId"], "name": a["guestConfigurationName"],
            "properties": {"guestConfiguration": {"name": a["guestConfigurationName"],
                                                  "version": a.get("guestConfigurationVersion")},
                           "latestAssignmentReport": latest},
        })
    defs = {"cis": f"/providers/Microsoft.Authorization/policyDefinitions/{cis_def}",
            "azure": f"/providers/Microsoft.Authorization/policyDefinitions/{azure_def}"}
    policy = [{"properties": {"resourceId": s["resourceId"], "policyDefinitionId": s["policyDefinitionId"],
                              "complianceState": s["complianceState"]}} for s in bundle["policyStates"]]
    return resources, guest, policy, {"cis": cis_def, "azure": azure_def, "defs": defs}


def machines_fragment(resources):
    out = []
    for r in resources:
        arc = r["type"] == "microsoft.hybridcompute/machines"
        p = r["properties"]
        os_type = (p.get("osType") if arc else p.get("storageProfile", {}).get("osDisk", {}).get("osType")) or ""
        os_type = os_type.lower()
        out.append({
            "machineId": r["id"].lower(), "kind": "ArcMachine" if arc else "AzureVM",
            "eligibility": {"windows": "Eligible", "linux": "NotEligible"}.get(os_type, "Unknown"),
        })
    return out


def assignments_fragment(guest):
    out = []
    for g in guest:
        assignment_id = g["id"].lower()
        machine_id = assignment_id.split("/providers/microsoft.guestconfiguration/")[0]
        gc = g["properties"].get("guestConfiguration") or {}
        name = gc.get("name") or g["name"]
        family = {"azurewindowsbaseline": FAMILIES[0], "ciswindowssecuritybaseline": FAMILIES[1]}.get(
            name.lower(), "Other")
        if family == "Other":
            continue
        latest = g["properties"].get("latestAssignmentReport")
        state = str((latest or {}).get("complianceStatus", "")).lower()
        report_end = ts((latest or {}).get("endTime"))
        out.append({
            "assignmentId": assignment_id, "machineId": machine_id, "family": family,
            "hasReport": bool(latest), "reportEnd": report_end,
            "reportState": {"compliant": "Compliant", "noncompliant": "NonCompliant",
                            "pending": "Pending"}.get(state, "Unknown"),
            "rank": report_end or EPOCH, "resources": (latest or {}).get("resources") or [],
        })
    return out


def evidence_fragment(machines, assignments, now):
    latest = {}
    for a in assignments:  # summarize arg_max(rank, *) by machineId, family
        key = (a["machineId"], a["family"])
        if key not in latest or a["rank"] > latest[key]["rank"]:
            latest[key] = a
    rows = []
    for m in machines:
        for family in FAMILIES:  # mv-expand family
            a = latest.get((m["machineId"], family))
            if m["eligibility"] == "Unknown":
                quality = "UnknownApplicability"
            elif a is None:
                quality = "MissingAssignment"
            elif not a["hasReport"]:
                quality = "NoReport"
            elif a["reportEnd"] is None:
                quality = "UnknownAge"
            elif (now - a["reportEnd"]).total_seconds() <= 86400:
                quality = "Fresh"
            else:
                quality = "Stale"
            state = a["reportState"] if a and a["hasReport"] else ""
            rows.append({
                **m, "family": family, "quality": quality, "reportedState": state,
                "green": quality == "Fresh" and state == "Compliant",
                "resources": a["resources"] if a else [],
            })
    return rows


def fresh_checks(evidence):
    out = []
    for e in evidence:
        if e["quality"] != "Fresh":
            continue
        by_key = {}
        for r in e["resources"]:
            key = r.get("resourceId")
            if not key:
                continue
            ok = str(r.get("complianceStatus")).lower() in ("true", "compliant")
            by_key.setdefault(key, []).append(ok)
        for key, oks in by_key.items():
            out.append({"machineId": e["machineId"], "family": e["family"], "checkKey": key,
                        "checkStatus": "NonCompliant" if not all(oks) else "Compliant"})
    return out


def pct(num, den):
    return None if den == 0 else round(100.0 * num / den, 2)


def run(bundle, now=None, **kwargs):
    """Returns {family: {policyCompliance, checkPassRate, coverage, machines}} like metrics_reference."""
    now = now or ts(bundle["snapshotAt"])
    resources, guest, policy, ids = to_arg_rows(bundle, **kwargs)
    machines = machines_fragment(resources)
    evidence = evidence_fragment(machines, assignments_fragment(guest), now)
    checks = fresh_checks(evidence)
    unknown_eligibility = sum(m["eligibility"] == "Unknown" for m in machines)
    result = {}
    for family in FAMILIES:
        defid = ids["cis"] if family == FAMILIES[1] else ids["azure"]
        states = [p["properties"]["complianceState"] for p in policy
                  if p["properties"]["policyDefinitionId"].lower().endswith("/" + defid.lower())]
        compliant, noncompliant = states.count("Compliant"), states.count("NonCompliant")
        exempt = states.count("Exempt")
        mine = [c for c in checks if c["family"] == family]
        passed = sum(c["checkStatus"] == "Compliant" for c in mine)
        fam_ev = [e for e in evidence if e["family"] == family]
        eligible = [e for e in fam_ev if e["eligibility"] == "Eligible"]
        assigned = sum(e["quality"] != "MissingAssignment" for e in eligible)
        usable = sum(e["quality"] in ("Fresh", "Stale", "UnknownAge") for e in eligible)
        fresh = sum(e["quality"] == "Fresh" for e in eligible)
        result[family] = {
            "policyCompliance": {"compliant": compliant, "nonCompliant": noncompliant, "exempt": exempt,
                                 "other": len(states) - compliant - noncompliant - exempt,
                                 "percent": pct(compliant, compliant + noncompliant)},
            "checkPassRate": {"passed": passed, "failed": len(mine) - passed, "total": len(mine),
                              "percent": pct(passed, len(mine)),
                              "reportsExcludedAsNotFresh": sum(e["quality"] in ("Stale", "UnknownAge")
                                                               for e in fam_ev)},
            "coverage": {"eligible": len(eligible), "unknownEligibility": unknown_eligibility,
                         "assigned": assigned, "usableReport": usable, "freshReport": fresh,
                         "assignmentPercent": pct(assigned, len(eligible)),
                         "usableReportPercent": pct(usable, len(eligible)),
                         "freshReportPercent": pct(fresh, len(eligible))},
            "machines": [{"machineId": e["machineId"], "evidenceQuality": e["quality"],
                          "reportedState": e["reportedState"] or None, "green": e["green"]}
                         for e in fam_ev],
        }
    return result
