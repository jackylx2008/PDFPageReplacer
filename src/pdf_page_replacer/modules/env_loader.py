"""Local environment file loading helpers."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_files(project_root: Path, filenames: tuple[str, ...] = ("common.env", "commen.env")) -> list[Path]:
    """Load simple KEY=VALUE env files without overriding existing variables."""
    loaded: list[Path] = []
    for filename in filenames:
        env_path = project_root / filename
        if not env_path.exists():
            continue
        _load_env_file(env_path)
        loaded.append(env_path)
    return loaded


def _load_env_file(env_path: Path) -> None:
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
