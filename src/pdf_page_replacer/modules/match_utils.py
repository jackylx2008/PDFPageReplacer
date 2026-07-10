"""Filename and OCR text matching helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    expected: str
    method: str
    matched_text: str


def match_filename_to_text(pdf_path: Path, ocr_text: str) -> MatchResult:
    expected = pdf_path.stem
    normalized_expected = normalize_for_exact_match(expected)
    normalized_text = normalize_for_exact_match(ocr_text)
    if normalized_expected and normalized_expected in normalized_text:
        return MatchResult(True, expected, "normalized_exact", expected)

    compact_expected = compact_identifier(expected)
    compact_text = compact_identifier(ocr_text)
    if compact_expected and compact_expected in compact_text:
        return MatchResult(True, expected, "compact_identifier", compact_expected)

    return MatchResult(False, expected, "not_found", "")


def extract_identifier_candidates(ocr_text: str) -> list[str]:
    normalized_text = normalize_for_exact_match(ocr_text)
    candidates = re.findall(r"\d{2}-\d{2}-[A-Z0-9]{2}-\d{3}", normalized_text)
    return sorted(set(candidates))


def normalize_for_exact_match(value: str) -> str:
    value = value.upper()
    value = value.replace("－", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", value)


def compact_identifier(value: str) -> str:
    value = normalize_for_exact_match(value)
    return re.sub(r"[^A-Z0-9]+", "", value)
