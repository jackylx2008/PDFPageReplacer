"""PDF 文件名与内容 OCR 校核工具

用途：
  读取 SOURCE_PATH_CONTENT 目录下的 PDF 文件，对每个 PDF 页面进行 OCR 识别，
  校核 PDF 文件名 stem 是否出现在 OCR 文本中，并统一记录未匹配文件。

配置文件：
  默认读取项目根目录下的 common.env 或 commen.env，其中 SOURCE_PATH_CONTENT
  用于指定待校核 PDF 目录。当前项目已有 commen.env，因此会兼容该文件名。

可选参数：
  --source-path   覆盖 SOURCE_PATH_CONTENT 指定的目录。
  --output-dir    结果输出目录，默认 output/pdf_filename_ocr_check。
  --max-pages     每个 PDF 最多识别页数，默认识别全部页面。
  --ocr-engine    OCR 优先引擎，默认 rapidocr，可选 rapidocr 或 tesseract。
  --zoom          PDF 渲染倍率，默认 2.0。
  --no-local-qwen 不调用本地 Qwen，仅使用 OCR 字符串规则匹配。

示例：
  python verify_pdf_filename_content.py
  python verify_pdf_filename_content.py --max-pages 1 --ocr-engine rapidocr

输出：
  日志写入 log/verify_pdf_filename_content.log。
  校核明细写入 output/pdf_filename_ocr_check/*.json 和 *.csv。
  控制台显示汇总信息和所有未匹配文件。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from logging_config import get_logger, resolve_path_markers, setup_logger
from pdf_page_replacer.flows.verify_pdf_filename_content import run
from pdf_page_replacer.modules.env_loader import load_env_files

USAGE = __doc__ or ""


def main() -> int:
    _configure_stdout()
    args = _parse_args()
    setup_logger(log_level=args.log_level)
    logger = get_logger(__name__)

    loaded_env_files = load_env_files(PROJECT_ROOT)
    logger.info("已读取环境文件: %s", ", ".join(str(path) for path in loaded_env_files) or "无")

    source_path_value = args.source_path or os.getenv("SOURCE_PATH_CONTENT")
    if not source_path_value:
        print("缺少 SOURCE_PATH_CONTENT。请在 common.env/commen.env 中配置，或使用 --source-path。", file=sys.stderr)
        return 2

    source_path = Path(resolve_path_markers(source_path_value))
    output_dir = Path(resolve_path_markers(args.output_dir))
    result = run(
        source_path=source_path,
        output_dir=output_dir,
        max_pages=args.max_pages,
        ocr_engine=args.ocr_engine,
        zoom=args.zoom,
        use_local_qwen=not args.no_local_qwen,
        project_root=PROJECT_ROOT,
    )

    print(json.dumps(_summary_payload(result), ensure_ascii=False, indent=2))
    return 1 if result.unmatched_count or result.error_count else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校核 PDF 文件名是否出现在 PDF OCR 文本中。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--source-path", default="", help="待校核 PDF 目录。")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "output" / "pdf_filename_ocr_check"), help="结果输出目录。")
    parser.add_argument("--max-pages", type=int, default=None, help="每个 PDF 最多识别页数，默认全部。")
    parser.add_argument("--ocr-engine", choices=("rapidocr", "tesseract"), default="rapidocr", help="优先使用的 OCR 引擎。")
    parser.add_argument("--zoom", type=float, default=2.0, help="PDF 页面渲染倍率。")
    parser.add_argument("--no-local-qwen", action="store_true", help="不调用本地 Qwen，仅使用 OCR 字符串规则匹配。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")
    return parser.parse_args()


def _summary_payload(result) -> dict:
    return {
        "source_path": result.source_path,
        "total_files": result.total_files,
        "matched_count": result.matched_count,
        "unmatched_count": result.unmatched_count,
        "error_count": result.error_count,
        "output_json": result.output_json,
        "output_csv": result.output_csv,
        "unmatched_files": [asdict(item) for item in result.unmatched_files],
    }


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
