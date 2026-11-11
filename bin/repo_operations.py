"""Shared operation state for the CLI, desktop and TUI.

No process launches or Git mutations belong here. Existing controllers own those
operations and their locks. Status is a read-only projection of existing records;
old records remain valid and need no migration.
"""

from datetime import datetime
import time

CHECKPOINT_STAGES = (
    "queued",
    "saving",
    "committing",
    "pushing",
    "verifying",
    "restarting",
    "started",
)
CHECKPOINT_LABELS = dict(
    zip(
        CHECKPOINT_STAGES,
        (
            "Queued",
            "Saving context",
            "Committing changes",
            "Pushing branch",
            "Verifying checkpoint",
            "Restarting conversation",
            "Fresh conversation requested",
        ),
    )
)
WORKFLOW_ACTIVE = ("queued", "preparing", "implementing", "fixing", "reviewing")
CHECKPOINT_ACTIVE = ("queued", "saving", "verifying", "restarting")
SUCCESS = ("ready", "verified", "started")


def timestamp(value, default=0):
    """Accept timestamps written by both existing controllers."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return default


def transition(job, state, message, *, now=None):
    """Update one in-memory record. Its controller persists it under its lock."""
    now = time.time() if now is None else now
    previous = job.get("stage", job.get("state", "queued"))
    if state == "needs-you":
        job["failed_stage"] = previous
    else:
        job["stage"] = state
        job.pop("failed_stage", None)
    if job.get("state") != state:
        job.setdefault("history", []).append(
            {"stage": state, "at": now, "message": message}
        )
    job.setdefault("started_at", timestamp(job.get("updated"), now))
    job.update(state=state, message=message, updated=now, heartbeat=now)
    return job


def retry_allowed(kind, job):
    """Display eligibility only. Controllers still revalidate locks and evidence."""
    return bool(
        job.get("token")
        and job.get("state") == "needs-you"
        and (kind == "checkpoint" or job.get("action") == "open")
    )


def require_retry(kind, job, token, *, target=None):
    if job.get("token") != token or (
        target is not None and job.get("target") != target
    ):
        raise RuntimeError("Operation changed; refresh before retrying")
    if not retry_allowed(kind, job):
        raise RuntimeError(
            "Only a failed operation can be retried; inspect the current operation"
        )


def describe(kind, job, *, now=None):
    """Return status plus a common display contract. Never writes runtime state."""
    if not job:
        return {}
    now = time.time() if now is None else now
    out = dict(job)
    active_states = CHECKPOINT_ACTIVE if kind == "checkpoint" else WORKFLOW_ACTIVE
    active = job.get("state") in active_states
    stalled = (
        kind == "checkpoint" and active and now - timestamp(job.get("heartbeat")) > 90
    )
    if stalled:
        out.update(
            state="needs-you",
            message="Checkpoint controller stopped responding. Inspect the conversation before retrying; no restart confirmed.",
        )
    failed = out.get("state") == "needs-you"
    stage = out.get("failed_stage") if failed else out.get("stage")
    stage = stage or job.get("stage") or job.get("state", "queued")
    end = now if active else timestamp(job.get("heartbeat", job.get("updated")), now)
    elapsed = max(
        0, int(end - timestamp(job.get("started_at", job.get("updated")), end))
    )
    stages = (
        CHECKPOINT_STAGES
        if kind == "checkpoint"
        else ("queued", "preparing", "ready") if job.get("action") == "open" else ()
    )
    index = stages.index(stage) if stage in stages else -1
    steps = []
    for i, name in enumerate(stages):
        # These describe reported progress, not independent test/backup evidence.
        status = (
            "failed"
            if failed and i == index
            else (
                "done"
                if i < index or (i == index and out.get("state") in SUCCESS)
                else "active" if i == index else "pending"
            )
        )
        steps.append(
            {
                "stage": name,
                "label": CHECKPOINT_LABELS.get(name, name.title()),
                "status": status,
            }
        )
    out["elapsed_seconds"] = elapsed
    out["operation"] = {
        "version": 1,
        "kind": kind,
        "stage": stage,
        "label": CHECKPOINT_LABELS.get(stage, stage.replace("-", " ").title()),
        "active": active and not stalled,
        "stalled": stalled,
        "failed": failed,
        "success": out.get("state") in SUCCESS,
        "can_retry": not stalled and retry_allowed(kind, job),
        "event_id": ":".join(
            str(x)
            for x in (
                kind,
                job.get("token", ""),
                job.get("attempt", 1),
                out.get("state"),
            )
        ),
        "notification": (
            "warning" if failed else "success" if out.get("state") in SUCCESS else None
        ),
        "steps": steps,
    }
    return out
