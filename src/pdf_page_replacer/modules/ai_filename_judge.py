"""Use local Qwen to judge whether filename and OCR content match."""

from __future__ import annotations

from dataclasses import dataclass

from pdf_page_replacer.modules.llamacpp_client import LlamaCppClient
from pdf_page_replacer.modules.match_utils import extract_identifier_candidates


@dataclass(frozen=True)
class AiJudgeResult:
    matched: bool
    normalized_content_number: str
    reason: str


SYSTEM_PROMPT = """你是严谨的工程资料编号校核助手。只输出 JSON，不输出解释性散文。"""


def judge_filename_match(client: LlamaCppClient, expected_filename_stem: str, ocr_text: str) -> AiJudgeResult:
    preview = " ".join(ocr_text.split())[:2500]
    candidates = extract_identifier_candidates(ocr_text)
    user_prompt = f"""请判断 PDF 文件名编号是否与 OCR 内容中的“资料编号/编号”一致。

文件名编号：
{expected_filename_stem}

OCR 识别出的编号候选：
{candidates}

OCR 文本片段：
{preview}

判定规则：
1. 优先看 OCR 文本中“资料编号”附近的编号。
2. 允许常见 OCR 混淆：C2 可能被识别成 02、O2、CZ；数字 0 可能和字母 O 混淆；连字符缺失或多余不影响；末尾流水号 011 被识别成 11 这类前导 0 缺失不影响。
3. 如果内容编号实质上对应文件名编号，matched=true。
4. 如果内容编号明显是另一个编号，matched=false。
5. 如果 OCR 文本不足以确认，matched=false。

只返回以下 JSON：
{{
  "matched": true 或 false,
  "normalized_content_number": "你认为内容里的编号，无法确认则为空字符串",
  "reason": "一句中文理由"
}}
"""
    payload = client.chat_json(SYSTEM_PROMPT, user_prompt, max_tokens=256)
    return AiJudgeResult(
        matched=bool(payload.get("matched", False)),
        normalized_content_number=str(payload.get("normalized_content_number", "")),
        reason=str(payload.get("reason", "")),
    )
