"""Workflow for checking whether PDF filenames appear in OCR text."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from logging_config import get_logger
from pdf_page_replacer.modules.ai_filename_judge import judge_filename_match
from pdf_page_replacer.modules.llamacpp_client import LlamaCppClient, LlamaCppConfig
from pdf_page_replacer.modules.match_utils import extract_identifier_candidates, match_filename_to_text
from pdf_page_replacer.modules.pdf_ocr import PdfOcrReader

logger = get_logger(__name__)


@dataclass(frozen=True)
class FileCheckResult:
    file_name: str
    file_path: str
    matched: bool
    expected: str
    match_method: str
    matched_text: str
    page_count_checked: int
    ocr_engines: str
    ocr_text_length: int
    ocr_identifier_candidates: str
    ocr_preview: str
    ai_model: str
    ai_matched: bool | None
    ai_content_number: str
    ai_reason: str
    error: str = ""


@dataclass(frozen=True)
class WorkflowResult:
    source_path: str
    total_files: int
    matched_count: int
    unmatched_count: int
    error_count: int
    output_json: str
    output_csv: str
    unmatched_files: list[FileCheckResult]


def run(
    source_path: Path,
    output_dir: Path,
    max_pages: int | None = None,
    ocr_engine: str = "rapidocr",
    zoom: float = 2.0,
    use_local_qwen: bool = True,
    project_root: Path | None = None,
) -> WorkflowResult:
    if not source_path.exists():
        raise FileNotFoundError(f"SOURCE_PATH_CONTENT does not exist: {source_path}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"SOURCE_PATH_CONTENT is not a directory: {source_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted({path.resolve(): path for path in source_path.glob("*") if path.is_file() and path.suffix.lower() == ".pdf"}.values())
    logger.info("开始校核 PDF 文件名与 OCR 内容，目录=%s，文件数=%s", source_path, len(pdf_files))

    reader = PdfOcrReader(zoom=zoom, preferred_engine=ocr_engine)
    ai_client: LlamaCppClient | None = None
    ai_model = ""
    if use_local_qwen:
        if project_root is None:
            raise RuntimeError("use_local_qwen=True 时必须传入 project_root。")
        config = LlamaCppConfig.from_env()
        ai_client = LlamaCppClient(config, project_root=project_root)
        models = ai_client.ensure_server()
        ai_client.assert_model_available(models)
        ai_model = config.model
        logger.info("启用本地 Qwen AI 判定，模型=%s", ai_model)
    results: list[FileCheckResult] = []

    try:
        for index, pdf_path in enumerate(pdf_files, start=1):
            logger.info("处理 PDF %s/%s: %s", index, len(pdf_files), pdf_path.name)
            try:
                page_results = reader.read_pdf(pdf_path, max_pages=max_pages)
                ocr_text = "\n".join(page.text for page in page_results)
                deterministic_match = match_filename_to_text(pdf_path, ocr_text)
                ai_matched = None
                ai_content_number = ""
                ai_reason = ""
                matched = deterministic_match.matched
                match_method = deterministic_match.method
                matched_text = deterministic_match.matched_text

                if ai_client is not None:
                    ai_result = judge_filename_match(ai_client, deterministic_match.expected, ocr_text)
                    ai_matched = ai_result.matched
                    ai_content_number = ai_result.normalized_content_number
                    ai_reason = ai_result.reason
                    matched = ai_result.matched
                    match_method = "local_qwen"
                    matched_text = ai_content_number

                result = FileCheckResult(
                    file_name=pdf_path.name,
                    file_path=str(pdf_path),
                    matched=matched,
                    expected=deterministic_match.expected,
                    match_method=match_method,
                    matched_text=matched_text,
                    page_count_checked=len(page_results),
                    ocr_engines=",".join(sorted({page.engine for page in page_results})),
                    ocr_text_length=len(ocr_text),
                    ocr_identifier_candidates=";".join(extract_identifier_candidates(ocr_text)),
                    ocr_preview=_preview(ocr_text),
                    ai_model=ai_model,
                    ai_matched=ai_matched,
                    ai_content_number=ai_content_number,
                    ai_reason=ai_reason,
                )
                if result.matched:
                    logger.info("匹配成功: %s，方式=%s，AI理由=%s", pdf_path.name, result.match_method, result.ai_reason)
                else:
                    logger.warning(
                        "未匹配: %s，期望=%s，OCR长度=%s，AI理由=%s",
                        pdf_path.name,
                        result.expected,
                        result.ocr_text_length,
                        result.ai_reason,
                    )
            except Exception as exc:
                logger.exception("处理失败: %s", pdf_path)
                result = FileCheckResult(
                    file_name=pdf_path.name,
                    file_path=str(pdf_path),
                    matched=False,
                    expected=pdf_path.stem,
                    match_method="error",
                    matched_text="",
                    page_count_checked=0,
                    ocr_engines="",
                    ocr_text_length=0,
                    ocr_identifier_candidates="",
                    ocr_preview="",
                    ai_model=ai_model,
                    ai_matched=None,
                    ai_content_number="",
                    ai_reason="",
                    error=str(exc),
                )
            results.append(result)
    finally:
        if ai_client is not None:
            ai_client.shutdown_server()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_json = output_dir / f"pdf_filename_ocr_check_{timestamp}.json"
    output_csv = output_dir / f"pdf_filename_ocr_check_{timestamp}.csv"
    _write_json(output_json, source_path, results)
    _write_csv(output_csv, results)

    unmatched_files = [result for result in results if not result.matched]
    error_count = sum(1 for result in results if result.error)
    workflow_result = WorkflowResult(
        source_path=str(source_path),
        total_files=len(results),
        matched_count=sum(1 for result in results if result.matched),
        unmatched_count=len(unmatched_files),
        error_count=error_count,
        output_json=str(output_json),
        output_csv=str(output_csv),
        unmatched_files=unmatched_files,
    )
    logger.info(
        "校核完成，总数=%s，匹配=%s，未匹配=%s，错误=%s，结果=%s",
        workflow_result.total_files,
        workflow_result.matched_count,
        workflow_result.unmatched_count,
        workflow_result.error_count,
        output_json,
    )
    return workflow_result


def _write_json(output_path: Path, source_path: Path, results: list[FileCheckResult]) -> None:
    payload = {
        "source_path": str(source_path),
        "total_files": len(results),
        "matched_count": sum(1 for result in results if result.matched),
        "unmatched_count": sum(1 for result in results if not result.matched),
        "error_count": sum(1 for result in results if result.error),
        "results": [asdict(result) for result in results],
        "unmatched_files": [asdict(result) for result in results if not result.matched],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(output_path: Path, results: list[FileCheckResult]) -> None:
    fieldnames = list(FileCheckResult.__dataclass_fields__.keys())
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def _preview(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    return compact[:limit]
