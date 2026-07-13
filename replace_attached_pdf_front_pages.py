"""PDF 面单替换附图首页工具

用途：
  读取 SOURCE_PATH_CONTENT 下的 PDF 文件 A，在 SOURCE_PATH_ATTACHED_FIGURES
  下查找唯一匹配的 PDF 文件 B。根据 A 的页数删除 B 从头开始对应页数，
  再将 A 的全部页复制到 B 的头部，生成新 PDF 并保存到 TAGENT_ROOT_PATH。

匹配规则：
  1. 优先按完整 PDF 文件名做大小写不敏感匹配。
  2. 如果没有完整同名文件，则用 A 的完整 stem 匹配 B 的 stem 开头。
  3. 找不到或找到多个候选时不生成 PDF，并写入未匹配 JSON。

输出：
  新 PDF 默认使用 A 的完整文件名，保存到 TAGENT_ROOT_PATH。
  未匹配、歧义和错误清单保存到 TAGENT_ROOT_PATH/pdf_page_replacer_unmatched_*.json。
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
from pdf_page_replacer.flows.replace_attached_pdf_front_pages import run
from pdf_page_replacer.modules.env_loader import load_env_files

USAGE = __doc__ or ""


def main() -> int:
    _configure_stdout()
    args = _parse_args()
    setup_logger(log_level=args.log_level)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    load_env_files(PROJECT_ROOT)

    source_path_content = _resolve_required_path("SOURCE_PATH_CONTENT", args.source_path_content)
    source_path_attached_figures = _resolve_required_path("SOURCE_PATH_ATTACHED_FIGURES", args.source_path_attached_figures)
    target_root_path = _resolve_required_path("TAGENT_ROOT_PATH", args.target_root_path)

    result = run(
        source_path_content=source_path_content,
        source_path_attached_figures=source_path_attached_figures,
        target_root_path=target_root_path,
        output_name_source=args.output_name_source,
        dry_run=args.dry_run,
    )
    print(json.dumps(_summary_payload(result), ensure_ascii=False, indent=2))
    return 1 if result.error_count else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 SOURCE_PATH_CONTENT 中的 PDF 页替换到匹配附图 PDF 的头部。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--source-path-content", default="", help="覆盖 SOURCE_PATH_CONTENT。")
    parser.add_argument("--source-path-attached-figures", default="", help="覆盖 SOURCE_PATH_ATTACHED_FIGURES。")
    parser.add_argument("--target-root-path", default="", help="覆盖 TAGENT_ROOT_PATH。")
    parser.add_argument(
        "--output-name-source",
        choices=("content", "attached"),
        default="content",
        help="输出 PDF 使用哪个源文件名，默认 content，即 A 的完整文件名。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只匹配和统计，不写出 PDF。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")
    return parser.parse_args()


def _resolve_required_path(env_name: str, override_value: str) -> Path:
    raw_value = override_value or os.getenv(env_name)
    if not raw_value:
        raise ValueError(f"缺少 {env_name}。请在 common.env/commen.env 中配置，或使用命令行参数覆盖。")
    return Path(resolve_path_markers(raw_value))


def _summary_payload(result) -> dict:
    return {
        "source_path_content": result.source_path_content,
        "source_path_attached_figures": result.source_path_attached_figures,
        "target_root_path": result.target_root_path,
        "total_content_files": result.total_content_files,
        "total_attached_files": result.total_attached_files,
        "matched_count": result.matched_count,
        "unmatched_content_count": len(result.unmatched_content_files),
        "unmatched_attached_figures_count": len(result.unmatched_attached_figures),
        "error_count": result.error_count,
        "unmatched_json": result.unmatched_json,
        "errors": [asdict(error) for error in result.errors],
    }


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
