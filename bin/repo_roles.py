"""Small role profiles over the two stable workflow/ownership slots."""

import json
import os
import re
from pathlib import Path
from repo_state import write_json

DEFAULTS = {
    "studio": dict(
        base="studio",
        label="Studio",
        description="Planning & handoffs",
        instructions="",
        handoff_to=[],
    ),
    "work": dict(
        base="work",
        label="Work",
        description="Implementation & Docker",
        instructions="",
        handoff_to=[],
    ),
}
ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")


def roles(root):
    result = {key: dict(value) for key, value in DEFAULTS.items()}
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    for path in (config / "bollard/roles.json", Path(root) / ".bollard/roles.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or len(data) > 32:
                raise ValueError("expected an object with at most 32 roles")
            for key, fields in data.items():
                if not ID.fullmatch(key) or len(key) > 48:
                    raise ValueError("invalid role ID")
                if not isinstance(fields, dict) or set(fields) - {
                    "base",
                    "label",
                    "description",
                    "instructions",
                    "instructions_file",
                    "handoff_to",
                }:
                    raise ValueError("unsupported role fields")
                value = dict(
                    result.get(
                        key,
                        dict(label=key, description="", instructions="", handoff_to=[]),
                    )
                )
                value.update(fields)
                if value.get("base") not in DEFAULTS or (
                    key in DEFAULTS and value["base"] != key
                ):
                    raise ValueError(
                        "base must be studio or work; built-in bases cannot change"
                    )
                for field, limit in (
                    ("label", 40),
                    ("description", 160),
                    ("instructions", 8000),
                ):
                    item = value[field]
                    if (
                        not isinstance(item, str)
                        or len(item) > limit
                        or (field == "label" and not item.strip())
                        or (field != "instructions" and "\n" in item)
                    ):
                        raise ValueError("invalid " + field)
                targets = value["handoff_to"]
                if not isinstance(targets, list) or any(
                    not isinstance(x, str) or not ID.fullmatch(x) for x in targets
                ):
                    raise ValueError("handoff_to must be a list of role IDs")
                if "instructions_file" in fields:
                    rel = fields["instructions_file"]
                    if (
                        not isinstance(rel, str)
                        or Path(rel).is_absolute()
                        or ".." in Path(rel).parts
                    ):
                        raise ValueError(
                            "instructions_file must be relative to the configuration directory"
                        )
                    file = (path.parent / rel).resolve()
                    if (
                        not file.is_relative_to(path.parent.resolve())
                        or not file.is_file()
                        or file.stat().st_size > 32000
                    ):
                        raise ValueError(
                            "instructions_file must be a small file within the configuration directory"
                        )
                    value["instructions"] += "\n" + file.read_text()
                    if len(value["instructions"]) > 8000:
                        raise ValueError("combined instructions exceed 8000 characters")
                result[key] = value
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"Invalid role configuration {path}: {exc}") from exc
    for key, value in result.items():
        if any(target not in result for target in value["handoff_to"]):
            raise RuntimeError("Unknown handoff destination in role " + key)
    return result


def selected(root, pref, base):
    path = pref.with_suffix(".profile.json")
    record = json.loads(path.read_text()) if path.exists() else {"id": base}
    identity = record["id"]
    definitions = roles(root)
    if identity not in definitions or definitions[identity]["base"] != base:
        raise RuntimeError("Saved role is unavailable or changed base: " + identity)
    return identity, definitions[identity]


def select(root, pref, base, identity):
    definitions = roles(root)
    if identity not in definitions or definitions[identity]["base"] != base:
        raise RuntimeError("Choose a role with base " + base)
    pref.parent.mkdir(parents=True, exist_ok=True)
    write_json(pref.with_suffix(".profile.json"), {"id": identity})
    return definitions[identity]
