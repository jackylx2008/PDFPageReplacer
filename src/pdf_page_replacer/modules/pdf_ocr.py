"""PDF rendering and OCR helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz
import numpy as np
from PIL import Image

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - depends on runtime packages
    RapidOCR = None  # type: ignore[assignment]

try:
    import pytesseract
except ImportError:  # pragma: no cover - depends on runtime packages
    pytesseract = None  # type: ignore[assignment]


@dataclass(frozen=True)
class OcrPageResult:
    page_number: int
    text: str
    engine: str
    item_count: int


class PdfOcrReader:
    def __init__(self, zoom: float = 2.0, preferred_engine: str = "rapidocr") -> None:
        self.zoom = zoom
        self.preferred_engine = preferred_engine.lower()
        self._rapidocr = None
        self._tesseract_checked = False

    def read_pdf(self, pdf_path: Path, max_pages: int | None = None) -> list[OcrPageResult]:
        page_results: list[OcrPageResult] = []
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
            for page_index in range(page_count):
                page = doc[page_index]
                text = page.get_text("text").strip()
                if text:
                    page_results.append(OcrPageResult(page_index + 1, text, "embedded_text", 0))
                    continue

                image = self._render_page(page)
                page_results.append(self._ocr_image(image, page_index + 1))
        return page_results

    def _render_page(self, page: fitz.Page) -> np.ndarray:
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

    def _ocr_image(self, image: np.ndarray, page_number: int) -> OcrPageResult:
        engines = self._engine_order()
        last_error: Exception | None = None
        for engine in engines:
            try:
                if engine == "rapidocr":
                    return self._ocr_with_rapidocr(image, page_number)
                if engine == "tesseract":
                    return self._ocr_with_tesseract(image, page_number)
            except Exception as exc:  # Keep the next engine available.
                last_error = exc
        if last_error:
            raise RuntimeError(f"OCR failed on page {page_number}: {last_error}") from last_error
        raise RuntimeError("No OCR engine is available.")

    def _engine_order(self) -> Iterable[str]:
        if self.preferred_engine == "tesseract":
            return ("tesseract", "rapidocr")
        return ("rapidocr", "tesseract")

    def _ocr_with_rapidocr(self, image: np.ndarray, page_number: int) -> OcrPageResult:
        if RapidOCR is None:
            raise RuntimeError("rapidocr_onnxruntime is not installed.")
        if self._rapidocr is None:
            self._rapidocr = RapidOCR()
        result, _ = self._rapidocr(image)
        lines = [_repair_mojibake(item[1]) for item in result or [] if len(item) >= 2 and item[1]]
        return OcrPageResult(page_number, "\n".join(lines), "rapidocr", len(lines))

    def _ocr_with_tesseract(self, image: np.ndarray, page_number: int) -> OcrPageResult:
        if pytesseract is None:
            raise RuntimeError("pytesseract is not installed.")
        self._ensure_tesseract_command()
        pil_image = Image.fromarray(image)
        text = pytesseract.image_to_string(pil_image, lang="chi_sim+eng")
        text = _repair_mojibake(text)
        lines = [line for line in text.splitlines() if line.strip()]
        return OcrPageResult(page_number, text.strip(), "tesseract", len(lines))

    def _ensure_tesseract_command(self) -> None:
        if self._tesseract_checked:
            return
        command = shutil.which("tesseract")
        if command is None:
            default_windows_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            if default_windows_path.exists():
                pytesseract.pytesseract.tesseract_cmd = str(default_windows_path)
            else:
                raise RuntimeError("tesseract executable was not found.")
        self._tesseract_checked = True


def _repair_mojibake(text: str) -> str:
    try:
        repaired = text.encode("latin1").decode("gbk")
    except UnicodeError:
        return text
    original_cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    repaired_cjk = sum(1 for char in repaired if "\u4e00" <= char <= "\u9fff")
    return repaired if repaired_cjk > original_cjk else text
