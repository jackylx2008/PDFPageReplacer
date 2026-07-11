"""Persistent filename match confirmations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIRMATION_FILE_NAME = "pdf_filename_match_confirmations.json"
UNMATCHED_FILE_NAME = "pdf_filename_unmatched_results.json"


def confirmation_path(source_path: Path) -> Path:
    return source_path / CONFIRMATION_FILE_NAME


def unmatched_results_path(source_path: Path) -> Path:
    return source_path / UNMATCHED_FILE_NAME


def load_confirmation_store(source_path: Path) -> dict[str, Any]:
    path = confirmation_path(source_path)
    if not path.exists():
        return _empty_store()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", 1)
    data.setdefault("confirmed_matches", {})
    return data


def save_confirmation_store(source_path: Path, store: dict[str, Any]) -> Path:
    store["updated_at"] = _now()
    path = confirmation_path(source_path)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_unmatched_results(source_path: Path, payload: dict[str, Any]) -> Path:
    payload["updated_at"] = _now()
    path = unmatched_results_path(source_path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def get_confirmed_match(store: dict[str, Any], file_name: str) -> dict[str, Any] | None:
    matches = store.get("confirmed_matches", {})
    if not isinstance(matches, dict):
        return None
    return matches.get(_key(file_name))


def add_confirmed_match(
    store: dict[str, Any],
    file_name: str,
    expected: str,
    confirmed_by: str,
    content_number: str = "",
    reason: str = "",
    source_output_json: str = "",
) -> bool:
    matches = store.setdefault("confirmed_matches", {})
    key = _key(file_name)
    new_entry = {
        "file_name": file_name,
        "expected": expected,
        "confirmed_by": confirmed_by,
        "confirmed_at": _now(),
        "content_number": content_number,
        "reason": reason,
        "source_output_json": source_output_json,
    }
    old_entry = matches.get(key)
    if old_entry and _same_confirmation(old_entry, new_entry):
        return False
    matches[key] = new_entry
    return True


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": "",
        "description": "PDF filename/content confirmations used to skip already verified files.",
        "confirmed_matches": {},
    }


def _key(file_name: str) -> str:
    return file_name.casefold()


def _same_confirmation(old_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    compared_fields = ("file_name", "expected", "confirmed_by", "content_number", "reason", "source_output_json")
    return all(old_entry.get(field) == new_entry.get(field) for field in compared_fields)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
