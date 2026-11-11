"""Validate saved Compose configuration and isolate each stream's environment."""

import os
from pathlib import Path


def prepared_environment(values, root):
    """Studio allocates state.env before it ever generates a Compose environment.

    Only that exact, wholly absent generated pair is an expected empty state.
    Partial configurations, custom paths and unreadable files stay errors.
    """
    compose = values.get("COMPOSE_FILE", "")
    envfile = values.get("COMPOSE_ENV_FILES", "")
    if not values.get("COMPOSE_PROJECT_NAME") or not compose:
        raise RuntimeError("This stream has no valid saved Docker environment.")
    config_path = Path(compose)
    env_path = Path(envfile)
    if not config_path.is_absolute():
        config_path = root / config_path
    if not env_path.is_absolute():
        env_path = root / env_path
    generated = (
        config_path.name == "compose.work.json"
        and env_path.name == "compose.env"
        and config_path.parent == env_path.parent
        and (config_path.parent / "state.env").is_file()
    )
    if generated:

        def present(path):
            try:
                path.stat()
                return True
            except FileNotFoundError:
                # A broken symlink is configuration damage, not a fresh stream.
                return path.is_symlink()

        config_exists, env_exists = present(config_path), present(env_path)
        if not config_exists and not env_exists:
            return False
        if config_exists != env_exists:
            raise RuntimeError(
                "The saved Docker configuration is incomplete. "
                "Its Compose file and environment file must both be present."
            )
    return True


def environment(values):
    """Never inherit a different stream's COMPOSE_* settings."""
    result = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    result.update(
        {
            k: v
            for k, v in values.items()
            if k.startswith("COMPOSE_") and isinstance(v, str)
        }
    )
    return result
