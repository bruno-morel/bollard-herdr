#!/usr/bin/env python3
"""Local completion receipts. Never runs tests, agents, Docker or network commands."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

BIN = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), BIN / (name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = module("repo-tests")
R = T.R


def fail(text):
    raise RuntimeError(text)


def assessment(root, stream):
    path = R.safe(root, "docs/handoffs/" + stream + "/validation-plan.json")
    if not path.is_file():
        fail(
            "Record risk and focused coverage first: work complete "
            + stream
            + " --init"
        )
    if path.stat().st_size > 32000:
        fail("validation-plan.json is too large")
    p = R.read(path)
    if not isinstance(p, dict) or p.get("version") != 1:
        fail("validation-plan.json needs version 1")
    if p.get("risk") not in ("low", "medium", "high"):
        fail("Choose low, medium or high risk")
    for field in ("scope", "rationale", "coverage"):
        value = p.get(field)
        if (
            not isinstance(value, str)
            or len(value.strip()) < 8
            or value.strip().lower().startswith(("todo", "tbd", "replace"))
        ):
            fail("Fill validation-plan.json " + field + " with an actual assessment")
    ids = p.get("checks")
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(x, str) or not x for x in ids)
        or len(set(ids)) != len(ids)
    ):
        fail("List the selected check IDs in validation-plan.json checks")
    limitations = p.get("limitations", [])
    if not isinstance(limitations, list) or any(
        not isinstance(x, str) or len(x.strip()) < 8 for x in limitations
    ):
        fail("limitations must be a list of concrete gaps/reasons")
    deferred = p.get("review_deferred_reason", "")
    if not isinstance(deferred, str) or (deferred and len(deferred.strip()) < 20):
        fail("Explain deferred review in at least 20 characters")
    controls = p.get("risk_controls", "")
    if p["risk"] == "high" and (
        not isinstance(controls, str) or len(controls.strip()) < 20
    ):
        fail(
            "High risk requires risk_controls: affected regression scope and recovery/rollback considerations"
        )
    return p


def validate_evidence(
    root, plan, state, config, rows, expected_state, *, complete_run=True
):
    if state.get("state") != expected_state:
        fail(
            "Evidence is "
            + str(state.get("state"))
            + "; passing, current results are required"
        )
    declared = {x["id"]: x for x in config["checks"]}
    if not isinstance(rows, list) or any(
        not isinstance(x, dict) or not isinstance(x.get("id"), str) for x in rows
    ):
        fail("Invalid recorded check results; rerun the configured checks")
    result_ids = {x["id"] for x in rows}
    # A review may rerun a check up to three times. Each attempt must retain
    # its own passing log; never silently overwrite the earlier evidence.
    if expected_state != "verified" and len(result_ids) != len(rows):
        fail("Duplicate evidence IDs")
    logs = [x.get("log") for x in rows]
    if any(not isinstance(log, str) for log in logs) or len(set(logs)) != len(logs):
        fail("Each check attempt needs a distinct evidence log")
    if complete_run and result_ids != set(declared):
        fail("Recorded run is missing configured checks or contains unknown checks")
    for ident in plan["checks"]:
        if ident not in result_ids or ident not in declared:
            fail("No recorded result for selected check " + ident)
    for row in rows:
        command = declared.get(row["id"])
        if (
            not command
            or type(row.get("exit_code")) is not int
            or row["exit_code"] != 0
            or row.get("argv") != command["argv"]
        ):
            fail("Check did not pass as configured: " + row["id"])
        log = R.safe(root, row["log"])
        if not log.is_file() or hashlib.sha256(log.read_bytes()).hexdigest() != row.get(
            "sha256"
        ):
            fail("Missing or changed evidence log: " + row["id"])


def evaluate(ctx, require_review=False):
    root, stream, runtime, review, packet, key = ctx
    plan = assessment(root, stream)
    reviewed = R.snapshot_status(root, stream, review)
    if reviewed["state"] == "verified":
        c = R.load_config(root, stream)
        validate_evidence(
            root, plan, reviewed, c, reviewed.get("checks", []), "verified"
        )
        evidence = reviewed
        source = "review"
    else:
        if require_review:
            fail(
                "Independent review must verify this version before the workflow accepts completion"
            )
        evidence = T.snapshot(ctx)
        c, _ = T.config(root, stream)
        validate_evidence(
            root, plan, evidence, c, evidence.get("results", []), "passed"
        )
        source = "tests"
        if plan["risk"] != "low" and not plan.get("review_deferred_reason"):
            fail(
                "Medium/high risk needs current independent review, or an explicit review_deferred_reason for completion with limitations; no Claude call was made"
            )
        if reviewed["state"] in (
            "changes-required",
            "incomplete",
            "preflight",
            "reviewing",
        ):
            fail(
                "Resolve the outstanding/active review before accepting completion: "
                + reviewed["state"]
            )
    limitations = list(plan.get("limitations", []))
    if source != "review" and plan.get("review_deferred_reason"):
        limitations.append(plan["review_deferred_reason"])
    if require_review and limitations:
        fail("Workflow verification requires resolving the declared limitations")
    return dict(
        state="completed-with-limitations" if limitations else "completed",
        risk=plan["risk"],
        scope=plan["scope"],
        coverage=plan["coverage"],
        checks=plan["checks"],
        limitations=limitations,
        evidence_source=source,
        independent_review=source == "review",
        fingerprint=evidence["fingerprint"],
        at=R.now(),
        message="Local completion only; no merge, push, release approval or claim of full feature correctness.",
    )


def snapshot(ctx, record=False):
    root, stream, runtime, review, packet, key = ctx
    out = dict(
        state="blocked",
        risk="unassessed",
        scope="",
        coverage="",
        checks=[],
        missing=[],
        limitations=[],
        independent_review=False,
    )
    try:
        plan = assessment(root, stream)
        out.update({k: plan.get(k, "") for k in ("risk", "scope", "coverage")})
        out["limitations"] = plan.get("limitations", [])
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        plan = None
        out["missing"].append(str(e))
    try:
        reviewed = R.snapshot_status(root, stream, review)
        if reviewed["state"] == "verified":
            evidence = reviewed
            c = R.load_config(root, stream)
            rows = evidence.get("checks", [])
            passed_state = "verified"
        else:
            evidence = T.snapshot(ctx)
            c, _ = T.config(root, stream)
            rows = evidence.get("results", [])
            passed_state = "passed"
        selected = plan["checks"] if plan else [x["id"] for x in c["checks"]]
        for ident in selected:
            item = dict(
                id=ident,
                status="passed",
                detail="Recorded command passed; current source and log verified",
            )
            try:
                display_state = dict(evidence)
                if display_state.get("state") == "failed":
                    display_state["state"] = passed_state
                validate_evidence(
                    root,
                    {"checks": [ident]},
                    display_state,
                    c,
                    [x for x in rows if x.get("id") == ident],
                    passed_state,
                    complete_run=False,
                )
            except (RuntimeError, OSError, ValueError, KeyError) as e:
                item.update(status="missing", detail=str(e))
            out["checks"].append(item)
        out["evidence_state"] = evidence.get("state", "not-run")
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        out["missing"].append(str(e))
    try:
        result = evaluate(ctx)
        out.update({k: v for k, v in result.items() if k != "checks"})
        if record:
            if evaluate(ctx)["fingerprint"] != result["fingerprint"]:
                fail("Files changed while checking completion")
            R.write(runtime / "completion.json", result)
        receipt = R.read(runtime / "completion.json", {})
        out["recorded_at"] = (
            receipt.get("at")
            if receipt.get("fingerprint") == result["fingerprint"]
            else None
        )
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        out["state"] = "blocked"
        out["missing"].append(str(e))
    out["missing"] = list(dict.fromkeys(out["missing"]))
    out["checked_at"] = R.now()
    out["message"] = (
        "Existing evidence only. No tests, agents or Claude calls were started."
    )
    return out


def main():
    p = argparse.ArgumentParser(prog="work complete", description=__doc__)
    p.add_argument("stream", nargs="?")
    p.add_argument("--init", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--status",
        action="store_true",
        help="Read-only structured status including missing evidence",
    )
    p.add_argument(
        "--record",
        action="store_true",
        help="With --status, record completion only if the gate passes",
    )
    a = p.parse_args()
    ctx = T.context(a.stream)
    root, stream, runtime, review, packet, key = ctx
    if a.init:
        path = R.safe(root, "docs/handoffs/" + stream + "/validation-plan.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        template = dict(
            version=1,
            risk="low",
            scope="TODO describe this change only",
            rationale="TODO explain behavior, blast radius and reversibility",
            coverage="TODO explain why these focused checks cover the change; identify deliberate omissions",
            checks=[],
            limitations=[],
            review_deferred_reason="",
        )
        try:
            with path.open("x") as f:
                json.dump(template, f, indent=2)
                f.write("\n")
        except FileExistsError:
            pass
        print(
            "Assessment preserved/created: "
            + str(path)
            + "\nFill it BEFORE running checks. Use project test commands through work tests; completion never starts tests or Claude."
        )
        return
    if a.status:
        print(json.dumps(snapshot(ctx, record=a.record)))
        return
    if a.record:
        p.error("--record requires --status")
    result = evaluate(ctx)
    # Recheck immediately before writing a runtime-only receipt.
    if result["fingerprint"] != evaluate(ctx)["fingerprint"]:
        fail("Files changed while checking completion")
    R.write(runtime / "completion.json", result)
    print(
        json.dumps(result)
        if a.json
        else result["state"]
        + " ("
        + result["risk"]
        + "): "
        + result["scope"]
        + "\n"
        + result["message"]
        + (
            "\nLimitations: " + "; ".join(result["limitations"])
            if result["limitations"]
            else ""
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        sys.exit("work complete: " + str(e))
