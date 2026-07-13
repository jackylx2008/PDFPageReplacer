"""Replace leading pages in attached PDFs with content PDFs."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReplacementResult:
    content_file_name: str
    content_file_path: str
    attached_file_name: str
    attached_file_path: str
    output_file_name: str
    output_file_path: str
    match_method: str
    content_page_count: int
    attached_page_count: int
    removed_attached_page_count: int
    output_page_count: int


@dataclass(frozen=True)
class UnmatchedFile:
    file_name: str
    file_path: str
    side: str
    reason: str
    candidates: list[str]


@dataclass(frozen=True)
class ReplacementError:
    content_file_name: str
    content_file_path: str
    attached_file_name: str
    attached_file_path: str
    error: str


@dataclass(frozen=True)
class WorkflowResult:
    source_path_content: str
    source_path_attached_figures: str
    target_root_path: str
    total_content_files: int
    total_attached_files: int
    matched_count: int
    error_count: int
    unmatched_json: str
    results: list[ReplacementResult]
    unmatched_content_files: list[UnmatchedFile]
    unmatched_attached_figures: list[UnmatchedFile]
    errors: list[ReplacementError]


def run(
    source_path_content: Path,
    source_path_attached_figures: Path,
    target_root_path: Path,
    output_name_source: str = "content",
    dry_run: bool = False,
) -> WorkflowResult:
    _validate_directory(source_path_content, "SOURCE_PATH_CONTENT")
    _validate_directory(source_path_attached_figures, "SOURCE_PATH_ATTACHED_FIGURES")
    target_root_path.mkdir(parents=True, exist_ok=True)

    content_files = _list_pdf_files(source_path_content)
    attached_files = _list_pdf_files(source_path_attached_figures)
    logger.info(
        "开始替换 PDF 首页，面单目录=%s，附图目录=%s，目标目录=%s，面单数=%s，附图数=%s",
        source_path_content,
        source_path_attached_figures,
        target_root_path,
        len(content_files),
        len(attached_files),
    )

    matches, unmatched_content_files = _match_content_to_attached(content_files, attached_files)
    used_attached_paths = {attached.resolve() for _, attached, _ in matches}
    unmatched_attached_figures = [
        UnmatchedFile(
            file_name=attached.name,
            file_path=str(attached),
            side="SOURCE_PATH_ATTACHED_FIGURES",
            reason="no_matched_content_pdf",
            candidates=[],
        )
        for attached in attached_files
        if attached.resolve() not in used_attached_paths
    ]

    results: list[ReplacementResult] = []
    errors: list[ReplacementError] = []
    for content_pdf, attached_pdf, match_method in matches:
        output_file_name = content_pdf.name if output_name_source == "content" else attached_pdf.name
        output_pdf = target_root_path / output_file_name
        try:
            result = _replace_front_pages(
                content_pdf=content_pdf,
                attached_pdf=attached_pdf,
                output_pdf=output_pdf,
                match_method=match_method,
                dry_run=dry_run,
            )
            results.append(result)
            logger.info("生成完成: %s <- %s + %s", output_pdf, content_pdf.name, attached_pdf.name)
        except Exception as exc:
            logger.exception("生成失败: %s + %s", content_pdf, attached_pdf)
            errors.append(
                ReplacementError(
                    content_file_name=content_pdf.name,
                    content_file_path=str(content_pdf),
                    attached_file_name=attached_pdf.name,
                    attached_file_path=str(attached_pdf),
                    error=str(exc),
                )
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unmatched_json = target_root_path / f"pdf_page_replacer_unmatched_{timestamp}.json"
    _write_unmatched_json(
        unmatched_json,
        source_path_content,
        source_path_attached_figures,
        target_root_path,
        content_files,
        attached_files,
        results,
        unmatched_content_files,
        unmatched_attached_figures,
        errors,
        dry_run,
    )

    workflow_result = WorkflowResult(
        source_path_content=str(source_path_content),
        source_path_attached_figures=str(source_path_attached_figures),
        target_root_path=str(target_root_path),
        total_content_files=len(content_files),
        total_attached_files=len(attached_files),
        matched_count=len(results),
        error_count=len(errors),
        unmatched_json=str(unmatched_json),
        results=results,
        unmatched_content_files=unmatched_content_files,
        unmatched_attached_figures=unmatched_attached_figures,
        errors=errors,
    )
    logger.info(
        "替换完成，面单=%s，附图=%s，成功=%s，面单未匹配=%s，附图未匹配=%s，错误=%s，清单=%s",
        workflow_result.total_content_files,
        workflow_result.total_attached_files,
        workflow_result.matched_count,
        len(workflow_result.unmatched_content_files),
        len(workflow_result.unmatched_attached_figures),
        workflow_result.error_count,
        unmatched_json,
    )
    return workflow_result


def _validate_directory(path: Path, env_name: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{env_name} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{env_name} is not a directory: {path}")


def _list_pdf_files(directory: Path) -> list[Path]:
    return sorted(
        {path.resolve(): path for path in directory.glob("*") if path.is_file() and path.suffix.lower() == ".pdf"}.values(),
        key=lambda path: _normalize_for_match(path.name),
    )


def _match_content_to_attached(
    content_files: list[Path],
    attached_files: list[Path],
) -> tuple[list[tuple[Path, Path, str]], list[UnmatchedFile]]:
    attached_by_name: dict[str, list[Path]] = {}
    for attached in attached_files:
        attached_by_name.setdefault(_normalize_for_match(attached.name), []).append(attached)

    attached_stems = [(_normalize_for_match(attached.stem), attached) for attached in attached_files]
    used_attached_paths: set[Path] = set()
    matches: list[tuple[Path, Path, str]] = []
    unmatched: list[UnmatchedFile] = []

    for content in content_files:
        exact_candidates = [
            attached
            for attached in attached_by_name.get(_normalize_for_match(content.name), [])
            if attached.resolve() not in used_attached_paths
        ]
        if len(exact_candidates) == 1:
            matches.append((content, exact_candidates[0], "case_insensitive_full_filename"))
            used_attached_paths.add(exact_candidates[0].resolve())
            continue
        if len(exact_candidates) > 1:
            unmatched.append(_unmatched_content(content, "multiple_exact_filename_matches", exact_candidates))
            continue

        content_stem = _normalize_for_match(content.stem)
        prefix_candidates = [
            attached
            for attached_stem, attached in attached_stems
            if attached_stem.startswith(content_stem) and attached.resolve() not in used_attached_paths
        ]
        if len(prefix_candidates) == 1:
            matches.append((content, prefix_candidates[0], "content_stem_prefix"))
            used_attached_paths.add(prefix_candidates[0].resolve())
            continue
        if len(prefix_candidates) > 1:
            unmatched.append(_unmatched_content(content, "multiple_stem_prefix_matches", prefix_candidates))
            continue

        unmatched.append(_unmatched_content(content, "no_matched_attached_pdf", []))

    return matches, unmatched


def _unmatched_content(content: Path, reason: str, candidates: list[Path]) -> UnmatchedFile:
    return UnmatchedFile(
        file_name=content.name,
        file_path=str(content),
        side="SOURCE_PATH_CONTENT",
        reason=reason,
        candidates=[candidate.name for candidate in candidates],
    )


def _replace_front_pages(
    content_pdf: Path,
    attached_pdf: Path,
    output_pdf: Path,
    match_method: str,
    dry_run: bool,
) -> ReplacementResult:
    with content_pdf.open("rb") as content_file, attached_pdf.open("rb") as attached_file:
        content_reader = PdfReader(content_file)
        attached_reader = PdfReader(attached_file)
        _decrypt_if_needed(content_reader, content_pdf)
        _decrypt_if_needed(attached_reader, attached_pdf)

        content_page_count = len(content_reader.pages)
        attached_page_count = len(attached_reader.pages)
        writer = PdfWriter()
        for page in content_reader.pages:
            writer.add_page(page)
        for page_index in range(content_page_count, attached_page_count):
            writer.add_page(attached_reader.pages[page_index])

        output_page_count = len(writer.pages)
        if not dry_run:
            with output_pdf.open("wb") as output_file:
                writer.write(output_file)

    return ReplacementResult(
        content_file_name=content_pdf.name,
        content_file_path=str(content_pdf),
        attached_file_name=attached_pdf.name,
        attached_file_path=str(attached_pdf),
        output_file_name=output_pdf.name,
        output_file_path=str(output_pdf),
        match_method=match_method,
        content_page_count=content_page_count,
        attached_page_count=attached_page_count,
        removed_attached_page_count=min(content_page_count, attached_page_count),
        output_page_count=output_page_count,
    )


def _decrypt_if_needed(reader: PdfReader, pdf_path: Path) -> None:
    if not reader.is_encrypted:
        return
    if reader.decrypt("") == 0:
        raise ValueError(f"PDF is encrypted and cannot be opened with an empty password: {pdf_path}")


def _normalize_for_match(value: str) -> str:
    normalized = value.upper()
    normalized = normalized.replace("－", "-").replace("–", "-").replace("—", "-")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.casefold()


def _write_unmatched_json(
    output_path: Path,
    source_path_content: Path,
    source_path_attached_figures: Path,
    target_root_path: Path,
    content_files: list[Path],
    attached_files: list[Path],
    results: list[ReplacementResult],
    unmatched_content_files: list[UnmatchedFile],
    unmatched_attached_figures: list[UnmatchedFile],
    errors: list[ReplacementError],
    dry_run: bool,
) -> None:
    payload = {
        "version": 1,
        "description": "PDF files that were not uniquely matched while replacing attached PDF leading pages.",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "source_path_content": str(source_path_content),
        "source_path_attached_figures": str(source_path_attached_figures),
        "target_root_path": str(target_root_path),
        "total_content_files": len(content_files),
        "total_attached_files": len(attached_files),
        "matched_count": len(results),
        "unmatched_content_count": len(unmatched_content_files),
        "unmatched_attached_figures_count": len(unmatched_attached_figures),
        "error_count": len(errors),
        "results": [asdict(result) for result in results],
        "unmatched_content_files": [asdict(item) for item in unmatched_content_files],
        "unmatched_attached_figures": [asdict(item) for item in unmatched_attached_figures],
        "errors": [asdict(error) for error in errors],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
