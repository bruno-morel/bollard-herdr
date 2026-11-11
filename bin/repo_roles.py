"""Role presentation and additive instructions; lifecycle IDs remain stable."""

import json
import os
from pathlib import Path

DEFAULTS = {
    "studio": {
        "label": "Studio",
        "description": "Planning & handoffs",
        "instructions": "",
    },
    "work": {
        "label": "Work",
        "description": "Implementation & Docker",
        "instructions": "",
    },
}


def roles(root):
    result = {key: dict(value) for key, value in DEFAULTS.items()}
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    for path in (config / "bollard/roles.json", Path(root) / ".bollard/roles.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or set(data) - set(DEFAULTS):
                raise ValueError("expected studio and/or work objects")
            for key, fields in data.items():
                if not isinstance(fields, dict) or set(fields) - {
                    "label",
                    "description",
                    "instructions",
                }:
                    raise ValueError(
                        "supported fields: label, description, instructions"
                    )
                for field, value in fields.items():
                    limit = (
                        8000
                        if field == "instructions"
                        else 160 if field == "description" else 40
                    )
                    if (
                        not isinstance(value, str)
                        or len(value) > limit
                        or (
                            field != "instructions"
                            and (not value.strip() or "\n" in value)
                        )
                    ):
                        raise ValueError("invalid " + field)
                    result[key][field] = value
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Invalid role configuration {path}: {exc}") from exc
    return result
