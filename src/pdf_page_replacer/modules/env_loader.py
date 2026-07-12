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
    for key, value in _iter_env_assignments(env_path.read_text(encoding="utf-8-sig").splitlines()):
        key = key.strip()
        value = _strip_wrapping_quotes(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


def _iter_env_assignments(lines: list[str]) -> list[tuple[str, str]]:
    assignments: list[tuple[str, str]] = []
    pending_key = ""
    pending_value_lines: list[str] = []
    quote_char = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not pending_key and (not line or line.startswith("#") or "=" not in line):
            continue

        if pending_key:
            pending_value_lines.append(raw_line)
            if _line_closes_quote(raw_line, quote_char):
                assignments.append((pending_key, "\n".join(pending_value_lines)))
                pending_key = ""
                pending_value_lines = []
                quote_char = ""
            continue

        key, value = line.split("=", 1)
        value = value.strip()
        if _starts_unclosed_quote(value):
            pending_key = key
            pending_value_lines = [value]
            quote_char = value[0]
            if _line_closes_quote(value, quote_char):
                assignments.append((pending_key, "\n".join(pending_value_lines)))
                pending_key = ""
                pending_value_lines = []
                quote_char = ""
            continue

        assignments.append((key, value))

    if pending_key:
        assignments.append((pending_key, "\n".join(pending_value_lines)))

    return assignments


def _starts_unclosed_quote(value: str) -> bool:
    return len(value) >= 1 and value[0] in ("'", '"') and not _line_closes_quote(value, value[0])


def _line_closes_quote(value: str, quote_char: str) -> bool:
    stripped = value.rstrip()
    return len(stripped) > 1 and stripped.endswith(quote_char) and not stripped.endswith(f"\\{quote_char}")


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
