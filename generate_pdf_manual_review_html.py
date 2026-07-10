"""PDF 未匹配项人工复核 HTML 生成工具

用途：
  读取 verify_pdf_filename_content.py 输出的 JSON 结果，将未匹配且文件名符合
  工程编号规则的 PDF 汇总成 HTML 复核页。HTML 中提供人工确认标记位、OCR 预览、
  AI 判断结果和 PDF 打开入口。

配置文件：
  默认读取项目根目录下的 common.env 或 commen.env，用于获取 SOURCE_PATH_CONTENT。

可选参数：
  --result-json   指定 verify 输出 JSON；不指定时自动读取 output/pdf_filename_ocr_check
                  下最新的 JSON。
  --source-path   覆盖 SOURCE_PATH_CONTENT。
  --output-name   HTML 输出文件名，默认 pdf_filename_manual_review.html。

输出：
  HTML 保存到 SOURCE_PATH_CONTENT 下。
  人工确认后，将 HTML 导出的 JSON 保存为
  SOURCE_PATH_CONTENT/pdf_filename_match_confirmations.json。
  后续 verify_pdf_filename_content.py 会跳过这些已确认文件。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from logging_config import resolve_path_markers, setup_logger
from pdf_page_replacer.modules.confirmation_store import (
    CONFIRMATION_FILE_NAME,
    load_confirmation_store,
)
from pdf_page_replacer.modules.env_loader import load_env_files

FILENAME_RULE = re.compile(r"^(?:JZ)?\d{2}-\d{2}-C2-\d{3}$", re.IGNORECASE)
USAGE = __doc__ or ""


def main() -> int:
    _configure_stdout()
    args = _parse_args()
    setup_logger(log_level=args.log_level)
    load_env_files(PROJECT_ROOT)

    result_json = Path(resolve_path_markers(args.result_json)) if args.result_json else _latest_result_json()
    data = json.loads(result_json.read_text(encoding="utf-8"))

    source_path_value = args.source_path or data.get("source_path") or os.getenv("SOURCE_PATH_CONTENT")
    if not source_path_value:
        print("缺少 SOURCE_PATH_CONTENT。请在 common.env/commen.env 中配置，或使用 --source-path。", file=sys.stderr)
        return 2
    source_path = Path(resolve_path_markers(source_path_value))
    source_path.mkdir(parents=True, exist_ok=True)

    confirmation_store = load_confirmation_store(source_path)
    review_items = _review_items(data)
    html_path = source_path / args.output_name
    html_path.write_text(_render_html(review_items, source_path, result_json, confirmation_store), encoding="utf-8")

    print(
        json.dumps(
            {
                "result_json": str(result_json),
                "source_path": str(source_path),
                "html_path": str(html_path),
                "confirmation_json": str(source_path / CONFIRMATION_FILE_NAME),
                "existing_confirmed_count": len(confirmation_store.get("confirmed_matches", {})),
                "review_item_count": len(review_items),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据 verify 输出 JSON 生成 PDF 未匹配项人工复核 HTML。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--result-json", default="", help="verify_pdf_filename_content.py 输出的 JSON。")
    parser.add_argument("--source-path", default="", help="PDF 所在目录；默认用 JSON 或 env 中的 SOURCE_PATH_CONTENT。")
    parser.add_argument("--output-name", default="pdf_filename_manual_review.html", help="保存到 SOURCE_PATH_CONTENT 下的 HTML 文件名。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")
    return parser.parse_args()


def _latest_result_json() -> Path:
    output_dir = PROJECT_ROOT / "output" / "pdf_filename_ocr_check"
    candidates = sorted(output_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"未找到 verify 输出 JSON: {output_dir}")
    return candidates[0]


def _review_items(data: dict) -> list[dict]:
    items = []
    for item in data.get("unmatched_files", []):
        if item.get("error"):
            continue
        expected = str(item.get("expected", ""))
        if not FILENAME_RULE.match(expected):
            continue
        file_path = Path(str(item.get("file_path", "")))
        if not file_path.exists():
            continue
        items.append(item)
    return items


def _render_html(items: list[dict], source_path: Path, result_json: Path, confirmation_store: dict) -> str:
    item_rows = "\n".join(_render_item(item, index) for index, item in enumerate(items, start=1))
    embedded_items = json.dumps(items, ensure_ascii=False)
    embedded_store = json.dumps(confirmation_store, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>PDF 文件名人工复核</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f6f7f9; color: #1f2933; }}
    header {{ position: sticky; top: 0; z-index: 2; background: #ffffff; border-bottom: 1px solid #d8dee8; padding: 14px 20px; }}
    main {{ padding: 18px 20px 40px; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; }}
    .meta {{ color: #536170; font-size: 13px; line-height: 1.7; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    button {{ border: 1px solid #9aa8b6; background: #fff; border-radius: 4px; padding: 8px 12px; cursor: pointer; }}
    button.primary {{ background: #1f6feb; border-color: #1f6feb; color: #fff; }}
    .item {{ background: #fff; border: 1px solid #d8dee8; border-radius: 6px; margin: 14px 0; overflow: hidden; }}
    .item-head {{ display: grid; grid-template-columns: 48px minmax(220px, 1fr) 240px 180px; gap: 12px; align-items: center; padding: 12px; border-bottom: 1px solid #e4e9f0; }}
    .idx {{ color: #6b7785; font-weight: 600; }}
    .file-name {{ font-weight: 700; }}
    .badge {{ display: inline-block; border: 1px solid #d8dee8; border-radius: 4px; padding: 2px 6px; margin: 2px 4px 2px 0; font-size: 12px; background: #f8fafc; }}
    .decision {{ display: flex; gap: 8px; align-items: center; }}
    .grid {{ display: grid; grid-template-columns: minmax(340px, 42%) minmax(360px, 58%); min-height: 420px; }}
    .detail {{ padding: 12px; border-right: 1px solid #e4e9f0; }}
    .pdf-pane {{ background: #eef2f6; min-height: 420px; }}
    iframe {{ width: 100%; height: 620px; border: 0; background: white; }}
    label {{ font-size: 13px; }}
    textarea {{ width: 100%; min-height: 54px; resize: vertical; box-sizing: border-box; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #e4e9f0; padding: 10px; border-radius: 4px; max-height: 220px; overflow: auto; }}
    .kv {{ margin: 8px 0; }}
    .kv b {{ display: inline-block; min-width: 110px; color: #425466; }}
    @media (max-width: 900px) {{
      .item-head {{ grid-template-columns: 40px 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
      .detail {{ border-right: 0; border-bottom: 1px solid #e4e9f0; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>PDF 文件名人工复核</h1>
    <div class="meta">
      来源 JSON: {html.escape(str(result_json))}<br>
      PDF 目录: {html.escape(str(source_path))}<br>
      人工确认 JSON 文件名: {CONFIRMATION_FILE_NAME}<br>
      勾选“人工确认匹配”后导出 JSON，并将该 JSON 保存到当前 PDF 目录；后续 verify 会跳过这些已确认文件。
    </div>
    <div class="toolbar">
      <button class="primary" onclick="downloadConfirmations()">导出人工确认 JSON</button>
      <button onclick="saveConfirmations()">保存人工确认 JSON</button>
      <button onclick="checkAll()">全部标记为人工确认</button>
      <button onclick="uncheckAll()">清空人工确认</button>
    </div>
  </header>
  <main>
    {item_rows if item_rows else "<p>没有符合规则的未匹配 PDF 需要人工复核。</p>"}
  </main>
  <script>
    const reviewItems = {embedded_items};
    const confirmationStore = {embedded_store};
    const confirmationFileName = "{CONFIRMATION_FILE_NAME}";

    function checkAll() {{
      document.querySelectorAll('.manual-confirm').forEach(input => input.checked = true);
    }}

    function uncheckAll() {{
      document.querySelectorAll('.manual-confirm').forEach(input => input.checked = false);
    }}

    function buildConfirmationStore() {{
      const store = structuredClone(confirmationStore);
      store.version = 1;
      store.updated_at = new Date().toISOString().slice(0, 19);
      store.description = 'PDF filename/content confirmations used to skip already verified files.';
      store.confirmed_matches = store.confirmed_matches || {{}};
      reviewItems.forEach(item => {{
        const checkbox = document.querySelector(`[data-file="${{cssEscape(item.file_name)}}"]`);
        if (!checkbox || !checkbox.checked) return;
        const notes = document.querySelector(`[data-notes="${{cssEscape(item.file_name)}}"]`)?.value || '';
        store.confirmed_matches[item.file_name.toLowerCase()] = {{
          file_name: item.file_name,
          expected: item.expected,
          confirmed_by: 'manual_html',
          confirmed_at: new Date().toISOString().slice(0, 19),
          content_number: item.ai_content_number || item.matched_text || '',
          reason: notes || '人工复核确认文件名与 PDF 内容编号一致',
          source_output_json: {json.dumps(str(result_json), ensure_ascii=False)}
        }};
      }});
      return store;
    }}

    function downloadConfirmations() {{
      const blob = new Blob([JSON.stringify(buildConfirmationStore(), null, 2)], {{ type: 'application/json;charset=utf-8' }});
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = confirmationFileName;
      link.click();
      URL.revokeObjectURL(link.href);
    }}

    async function saveConfirmations() {{
      const content = JSON.stringify(buildConfirmationStore(), null, 2);
      if (!window.showSaveFilePicker) {{
        downloadConfirmations();
        return;
      }}
      const handle = await window.showSaveFilePicker({{
        suggestedName: confirmationFileName,
        types: [{{ description: 'JSON', accept: {{ 'application/json': ['.json'] }} }}]
      }});
      const writable = await handle.createWritable();
      await writable.write(content);
      await writable.close();
    }}

    function cssEscape(value) {{
      return String(value).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
    }}
  </script>
</body>
</html>
"""


def _render_item(item: dict, index: int) -> str:
    file_name = str(item.get("file_name", ""))
    file_uri = Path(str(item.get("file_path", ""))).resolve().as_uri()
    return f"""<section class="item">
  <div class="item-head">
    <div class="idx">#{index}</div>
    <div>
      <div class="file-name">{html.escape(file_name)}</div>
      <div>
        <span class="badge">期望: {html.escape(str(item.get("expected", "")))}</span>
        <span class="badge">AI编号: {html.escape(str(item.get("ai_content_number", "")))}</span>
        <span class="badge">OCR候选: {html.escape(str(item.get("ocr_identifier_candidates", "")))}</span>
      </div>
    </div>
    <label class="decision">
      <input class="manual-confirm" type="checkbox" data-file="{html.escape(file_name, quote=True)}">
      人工确认匹配
    </label>
    <a href="{html.escape(file_uri, quote=True)}" target="_blank">打开 PDF</a>
  </div>
  <div class="grid">
    <div class="detail">
      <div class="kv"><b>AI matched</b>{html.escape(str(item.get("ai_matched", "")))}</div>
      <div class="kv"><b>AI reason</b>{html.escape(str(item.get("ai_reason", "")))}</div>
      <div class="kv"><b>OCR engine</b>{html.escape(str(item.get("ocr_engines", "")))}</div>
      <div class="kv"><b>OCR length</b>{html.escape(str(item.get("ocr_text_length", "")))}</div>
      <label>人工备注</label>
      <textarea data-notes="{html.escape(file_name, quote=True)}" placeholder="人工确认依据或备注"></textarea>
      <p><b>OCR 预览</b></p>
      <pre>{html.escape(str(item.get("ocr_preview", "")))}</pre>
    </div>
    <div class="pdf-pane">
      <iframe src="{html.escape(file_uri, quote=True)}"></iframe>
    </div>
  </div>
</section>"""


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
