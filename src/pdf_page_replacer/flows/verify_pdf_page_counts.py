"""Verify page-count consistency between generated PDFs and target PDFs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PageCountIssue:
    status: str
    source_file_name: str
    source_file_path: str
    source_page_count: int | None
    matched_file_name: str
    matched_file_path: str
    matched_page_count: int | None
    candidates: list[str]
    reason: str


@dataclass(frozen=True)
class PageCountMatch:
    source_file_name: str
    source_file_path: str
    source_page_count: int
    matched_file_name: str
    matched_file_path: str
    matched_page_count: int


@dataclass(frozen=True)
class WorkflowResult:
    source_root_path: str
    target_pdf_directories: list[str]
    output_json: str
    output_csv: str
    total_source_files: int
    total_target_files: int
    matched_count: int
    consistent_count: int
    issue_count: int
    issues: list[PageCountIssue]


def run(
    source_root_path: Path,
    target_pdf_directories: list[Path],
    output_dir: Path,
    recursive: bool = True,
) -> WorkflowResult:
    _validate_directory(source_root_path, "TAGENT_ROOT_PATH")
    for directory in target_pdf_directories:
        _validate_directory(directory, "TARGET_PDF_DIRECTORIES_JSON")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_files = _list_pdf_files(source_root_path, recursive=False)
    target_files = _list_target_pdf_files(target_pdf_directories, recursive=recursive)
    logger.info(
        "开始校核 PDF 页数，A目录=%s，B目录数=%s，A文件数=%s，B文件数=%s",
        source_root_path,
        len(target_pdf_directories),
        len(source_files),
        len(target_files),
    )

    matches: list[PageCountMatch] = []
    issues: list[PageCountIssue] = []
    one_to_many_matches: list[tuple[Path, list[Path]]] = []
    used_target_paths: set[Path] = set()
    used_target_to_source: dict[Path, Path] = {}

    for source_pdf in source_files:
        candidates = [target_pdf for target_pdf in target_files if target_pdf.stem.startswith(source_pdf.stem)]
        if not candidates:
            issues.append(_issue_without_match(source_pdf, "unmatched", "no_target_pdf_stem_startswith_source_stem"))
            continue
        if len(candidates) > 1:
            one_to_many_matches.append((source_pdf, candidates))
            issues.append(_issue_without_match(source_pdf, "ambiguous", "multiple_target_pdf_stem_prefix_matches", candidates))
            continue

        target_pdf = candidates[0]
        resolved_target = target_pdf.resolve()
        if resolved_target in used_target_paths:
            previous_source = used_target_to_source[resolved_target]
            issues.append(
                PageCountIssue(
                    status="ambiguous",
                    source_file_name=source_pdf.name,
                    source_file_path=str(source_pdf),
                    source_page_count=None,
                    matched_file_name=target_pdf.name,
                    matched_file_path=str(target_pdf),
                    matched_page_count=None,
                    candidates=[target_pdf.name],
                    reason=f"target_pdf_already_matched_by_source:{previous_source.name}",
                )
            )
            continue

        try:
            source_page_count = _read_page_count(source_pdf)
            target_page_count = _read_page_count(target_pdf)
        except Exception as exc:
            logger.exception("读取页数失败: %s -> %s", source_pdf, target_pdf)
            issues.append(
                PageCountIssue(
                    status="error",
                    source_file_name=source_pdf.name,
                    source_file_path=str(source_pdf),
                    source_page_count=None,
                    matched_file_name=target_pdf.name,
                    matched_file_path=str(target_pdf),
                    matched_page_count=None,
                    candidates=[target_pdf.name],
                    reason=str(exc),
                )
            )
            used_target_paths.add(resolved_target)
            used_target_to_source[resolved_target] = source_pdf
            continue

        used_target_paths.add(resolved_target)
        used_target_to_source[resolved_target] = source_pdf
        if source_page_count == target_page_count:
            matches.append(
                PageCountMatch(
                    source_file_name=source_pdf.name,
                    source_file_path=str(source_pdf),
                    source_page_count=source_page_count,
                    matched_file_name=target_pdf.name,
                    matched_file_path=str(target_pdf),
                    matched_page_count=target_page_count,
                )
            )
            continue

        issues.append(
            PageCountIssue(
                status="page_count_mismatch",
                source_file_name=source_pdf.name,
                source_file_path=str(source_pdf),
                source_page_count=source_page_count,
                matched_file_name=target_pdf.name,
                matched_file_path=str(target_pdf),
                matched_page_count=target_page_count,
                candidates=[target_pdf.name],
                reason="page_count_not_equal",
            )
        )

    _log_one_to_many_summary(one_to_many_matches)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_json = output_dir / f"pdf_page_count_check_{timestamp}.json"
    output_csv = output_dir / f"pdf_page_count_check_{timestamp}.csv"
    _write_json(output_json, source_root_path, target_pdf_directories, source_files, target_files, matches, issues, recursive)
    _write_csv(output_csv, issues)

    result = WorkflowResult(
        source_root_path=str(source_root_path),
        target_pdf_directories=[str(directory) for directory in target_pdf_directories],
        output_json=str(output_json),
        output_csv=str(output_csv),
        total_source_files=len(source_files),
        total_target_files=len(target_files),
        matched_count=len(matches) + sum(1 for issue in issues if issue.matched_file_path),
        consistent_count=len(matches),
        issue_count=len(issues),
        issues=issues,
    )
    logger.info(
        "页数校核完成，A文件=%s，B文件=%s，一致=%s，问题=%s，JSON=%s，CSV=%s",
        result.total_source_files,
        result.total_target_files,
        result.consistent_count,
        result.issue_count,
        output_json,
        output_csv,
    )
    return result


def _validate_directory(path: Path, env_name: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{env_name} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{env_name} is not a directory: {path}")


def _list_pdf_files(directory: Path, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(
        {path.resolve(): path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"}.values(),
        key=lambda path: str(path),
    )


def _list_target_pdf_files(directories: list[Path], recursive: bool) -> list[Path]:
    files_by_path: dict[Path, Path] = {}
    for directory in directories:
        for path in _list_pdf_files(directory, recursive=recursive):
            files_by_path[path.resolve()] = path
    return sorted(files_by_path.values(), key=lambda path: str(path))


def _read_page_count(pdf_path: Path) -> int:
    with pdf_path.open("rb") as file:
        reader = PdfReader(file)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError(f"PDF is encrypted and cannot be opened with an empty password: {pdf_path}")
        return len(reader.pages)


def _log_one_to_many_summary(one_to_many_matches: list[tuple[Path, list[Path]]]) -> None:
    if not one_to_many_matches:
        return

    logger.warning("发现 PDF 文件名前缀匹配一对多: %s 个 A 文件存在多个 B 候选。", len(one_to_many_matches))
    for source_pdf, candidates in one_to_many_matches:
        logger.warning(
            "一对多: A=%s，B候选数=%s，B候选=%s",
            source_pdf.name,
            len(candidates),
            "; ".join(str(candidate) for candidate in candidates),
        )


def _issue_without_match(
    source_pdf: Path,
    status: str,
    reason: str,
    candidates: list[Path] | None = None,
) -> PageCountIssue:
    candidate_paths = candidates or []
    return PageCountIssue(
        status=status,
        source_file_name=source_pdf.name,
        source_file_path=str(source_pdf),
        source_page_count=None,
        matched_file_name="",
        matched_file_path="",
        matched_page_count=None,
        candidates=[candidate.name for candidate in candidate_paths],
        reason=reason,
    )


def _write_json(
    output_path: Path,
    source_root_path: Path,
    target_pdf_directories: list[Path],
    source_files: list[Path],
    target_files: list[Path],
    matches: list[PageCountMatch],
    issues: list[PageCountIssue],
    recursive: bool,
) -> None:
    payload = {
        "version": 1,
        "description": "PDF page-count comparison from TAGENT_ROOT_PATH to TARGET_PDF_DIRECTORIES_JSON prefix matches.",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recursive_target_scan": recursive,
        "source_root_path": str(source_root_path),
        "target_pdf_directories": [str(directory) for directory in target_pdf_directories],
        "total_source_files": len(source_files),
        "total_target_files": len(target_files),
        "consistent_count": len(matches),
        "issue_count": len(issues),
        "consistent_matches": [asdict(match) for match in matches],
        "issues": [asdict(issue) for issue in issues],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(output_path: Path, issues: list[PageCountIssue]) -> None:
    fieldnames = [
        "status",
        "source_file_name",
        "source_file_path",
        "source_page_count",
        "matched_file_name",
        "matched_file_path",
        "matched_page_count",
        "candidates",
        "reason",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for issue in issues:
            row = asdict(issue)
            row["candidates"] = "; ".join(issue.candidates)
            writer.writerow(row)
