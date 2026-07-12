"""PDF 页数一致性校核工具

用途：
  读取 TAGENT_ROOT_PATH 下的 PDF 文件 A，在 TARGET_PDF_DIRECTORIES_JSON
  列出的目录下查找唯一匹配的 PDF 文件 B。匹配规则为 B 的文件名 stem
  必须以 A 的文件名 stem 原样开头。匹配成功后对比 A 和 B 的页数。

输出：
  页数不一致、未匹配、匹配歧义和读取错误写入 output/pdf_page_count_check
  下的 JSON 和 CSV 文件。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from logging_config import resolve_path_markers, setup_logger
from pdf_page_replacer.flows.verify_pdf_page_counts import run
from pdf_page_replacer.modules.env_loader import load_env_files

USAGE = __doc__ or ""


def main() -> int:
    _configure_stdout()
    args = _parse_args()
    setup_logger(log_level=args.log_level)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    load_env_files(PROJECT_ROOT)

    source_root_path = _resolve_required_path("TAGENT_ROOT_PATH", args.source_root_path)
    target_pdf_directories = _resolve_target_directories(args.target_pdf_directories_json)
    output_dir = Path(resolve_path_markers(args.output_dir))

    result = run(
        source_root_path=source_root_path,
        target_pdf_directories=target_pdf_directories,
        output_dir=output_dir,
        recursive=not args.no_recursive,
    )
    print(json.dumps(_summary_payload(result), ensure_ascii=False, indent=2))
    return 1 if result.issue_count else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校核 TAGENT_ROOT_PATH 与 TARGET_PDF_DIRECTORIES_JSON 中 PDF 的页数是否一致。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--source-root-path", default="", help="覆盖 TAGENT_ROOT_PATH。")
    parser.add_argument("--target-pdf-directories-json", default="", help="覆盖 TARGET_PDF_DIRECTORIES_JSON。")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output" / "pdf_page_count_check"),
        help="结果输出目录。",
    )
    parser.add_argument("--no-recursive", action="store_true", help="只扫描 TARGET_PDF_DIRECTORIES_JSON 目录第一层。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")
    return parser.parse_args()


def _resolve_required_path(env_name: str, override_value: str) -> Path:
    raw_value = override_value or os.getenv(env_name)
    if not raw_value:
        raise ValueError(f"缺少 {env_name}。请在 common.env/commen.env 中配置，或使用命令行参数覆盖。")
    return Path(resolve_path_markers(raw_value))


def _resolve_target_directories(override_value: str) -> list[Path]:
    raw_value = override_value or os.getenv("TARGET_PDF_DIRECTORIES_JSON")
    if not raw_value:
        raise ValueError("缺少 TARGET_PDF_DIRECTORIES_JSON。请在 common.env/commen.env 中配置，或使用命令行参数覆盖。")
    values = json.loads(raw_value)
    if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("TARGET_PDF_DIRECTORIES_JSON 必须是非空字符串数组。")
    return [Path(resolve_path_markers(value)) for value in values]


def _summary_payload(result) -> dict:
    return {
        "source_root_path": result.source_root_path,
        "target_pdf_directories": result.target_pdf_directories,
        "total_source_files": result.total_source_files,
        "total_target_files": result.total_target_files,
        "matched_count": result.matched_count,
        "consistent_count": result.consistent_count,
        "issue_count": result.issue_count,
        "output_json": result.output_json,
        "output_csv": result.output_csv,
        "issues": [asdict(issue) for issue in result.issues],
    }


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
