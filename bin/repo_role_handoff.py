"""Checkpoint extension: save first, then change one stable workflow slot."""

import hashlib
import json
from pathlib import Path
import repo_roles as profiles


def signature(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


def prepare(api, root, stream, source, identity, rows):
    definition = profiles.roles(root).get(identity)
    if not definition:
        raise RuntimeError("Unknown destination role: " + identity)
    labels = source.get("labels") or {}
    base = labels["repo-tools.role"]
    source_id = labels.get("repo-tools.profile") or base
    if not isinstance(source_id, str) or not profiles.ID.fullmatch(source_id):
        raise RuntimeError("Invalid source role identity")
    if identity == source_id:
        raise RuntimeError(
            "Already using this role; choose New conversation for a fresh chat."
        )
    for row in rows:
        tags = row.get("labels") or {}
        if (
            row.get("state") == "live"
            and row["address"] != source["address"]
            and tags.get("repo-tools.stream") == stream
            and tags.get("repo-tools.role") == definition["base"]
        ):
            raise RuntimeError(
                "The destination workflow slot is already open. Finish/close it before handing off; its conversation was not changed."
            )
    if definition["base"] == "work":
        packet = api.packet(root, stream)
        if not any(
            (packet / name).is_file() and (packet / name).read_text().strip()
            for name in ("implementation.md", "codex-prompt.md")
        ):
            raise RuntimeError("Build the implementation handoff first: studio handoff")
    return dict(
        id=identity,
        base=definition["base"],
        source_id=source_id,
        source_base=base,
        signature=signature(definition),
        agent=labels.get("repo-tools.agent") or "codex",
    )


def validate(root, handoff):
    profile = profiles.roles(root).get(handoff["id"])
    if not profile or signature(profile) != handoff["signature"]:
        raise RuntimeError(
            "Destination role configuration changed; inspect it before requesting a new handoff."
        )


def notes(stream, handoff):
    return "docs/handoffs/" + stream + "/roles/" + handoff["source_id"] + ".md"
