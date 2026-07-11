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

    canonical_expected = canonical_document_number(expected)
    canonical_candidates = [canonical_document_number(candidate) for candidate in extract_identifier_candidates(ocr_text)]
    if canonical_expected and canonical_expected in canonical_candidates:
        matched_text = extract_identifier_candidates(ocr_text)[canonical_candidates.index(canonical_expected)]
        return MatchResult(True, expected, "c2_ocr_equivalent", matched_text)

    compact_expected = compact_identifier(expected)
    compact_text = compact_identifier(ocr_text)
    if compact_expected and compact_expected in compact_text:
        return MatchResult(True, expected, "compact_identifier", compact_expected)

    compact_canonical_expected = compact_identifier(canonical_expected)
    compact_canonical_text = compact_identifier(canonicalize_document_numbers(ocr_text))
    if compact_canonical_expected and compact_canonical_expected in compact_canonical_text:
        return MatchResult(True, expected, "compact_c2_ocr_equivalent", compact_canonical_expected)

    return MatchResult(False, expected, "not_found", "")


def extract_identifier_candidates(ocr_text: str) -> list[str]:
    normalized_text = normalize_for_exact_match(ocr_text)
    candidates = re.findall(r"(?:JZ)?\d{2}-\d{2}-[A-Z0-9]{2}-\d{2,3}", normalized_text)
    return sorted(set(candidates))


def normalize_for_exact_match(value: str) -> str:
    value = value.upper()
    value = value.replace("－", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", value)


def compact_identifier(value: str) -> str:
    value = normalize_for_exact_match(value)
    return re.sub(r"[^A-Z0-9]+", "", value)


def canonical_document_number(value: str) -> str:
    candidates = extract_identifier_candidates(value)
    if not candidates:
        compact_value = compact_identifier(value)
        compact_match = re.search(r"(JZ)?(\d{2})(\d{2})(C2|O2|02|CZ)(\d{2,3})", compact_value)
        if compact_match:
            prefix, area, phase, kind, serial = compact_match.groups()
            return _canonical_parts(prefix or "", area, phase, kind, serial)
        return normalize_for_exact_match(value)

    candidate = candidates[0]
    match = re.search(r"^(JZ)?(\d{2})-(\d{2})-([A-Z0-9]{2})-(\d{2,3})$", candidate)
    if match is None:
        return candidate
    prefix, area, phase, kind, serial = match.groups()
    return _canonical_parts(prefix or "", area, phase, kind, serial)


def canonicalize_document_numbers(value: str) -> str:
    normalized = normalize_for_exact_match(value)

    def replace(match: re.Match[str]) -> str:
        prefix, area, phase, kind, serial = match.groups()
        return _canonical_parts(prefix or "", area, phase, kind, serial)

    return re.sub(r"(JZ)?(\d{2})-(\d{2})-(C2|O2|02|CZ)-(\d{2,3})", replace, normalized)


def _canonical_parts(prefix: str, area: str, phase: str, kind: str, serial: str) -> str:
    normalized_kind = "C2" if kind in {"C2", "O2", "02", "CZ"} else kind
    normalized_serial = serial.zfill(3)
    prefix_text = prefix or ""
    return f"{prefix_text}{area}-{phase}-{normalized_kind}-{normalized_serial}"
