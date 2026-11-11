"""Finite command definitions shared by test runs and independent reviews."""

from pathlib import Path
import re


def validate_commands(checks):
    """Validate command data only; never run it or inspect the environment."""
    if not isinstance(checks, list) or not 1 <= len(checks) <= 8:
        raise RuntimeError("Declare 1–8 finite checks")
    ids = set()
    for check in checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("id"), str)
            or not re.fullmatch("[a-z0-9-]{1,40}", check["id"])
            or check["id"] in ids
        ):
            raise RuntimeError("Check IDs must be unique lowercase names")
        ids.add(check["id"])
        if check.get("kind") not in ("unit", "integration", "e2e", "static"):
            raise RuntimeError("Invalid check kind")
        argv = check.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(s, str) and s and "\0" not in s for s in argv)
        ):
            raise RuntimeError("Each check needs a nonempty argv array")
        cwd = check.get("cwd", ".")
        if (
            not isinstance(cwd, str)
            or not cwd
            or "\0" in cwd
            or Path(cwd).is_absolute()
            or ".." in Path(cwd).parts
        ):
            raise RuntimeError("Check cwd must be inside this checkout")
        timeout = check.get("timeout", 120)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise RuntimeError("Timeout must be 1–300 seconds")
    if sum(check.get("timeout", 120) for check in checks) > 1200:
        raise RuntimeError("Total test timeouts cannot exceed 20 minutes")
    return ids
