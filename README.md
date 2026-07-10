# PDFPageReplacer

PDFPageReplacer is a Python utility project for checking PDF cover/content files. The current workflow scans PDFs under `SOURCE_PATH_CONTENT`, OCRs the PDF pages, and uses a local Qwen model served by `llama.cpp` to judge whether the PDF filename matches the document number found in the OCR text.

## Features

- Reads local paths from `common.env` or the existing compatible `commen.env`.
- Renders scanned PDFs with PyMuPDF and extracts text with OCR.
- Calls a local Qwen model through a `llama.cpp` OpenAI-compatible API for final filename/content matching.
- Logs the processing workflow to `log/`.
- Writes JSON and CSV result files to `output/pdf_filename_ocr_check/`.
- Records unmatched files, OCR candidates, OCR preview text, AI model name, AI decision, and AI reason.

## Project Structure

```text
.
├── verify_pdf_filename_content.py
├── logging_config.py
├── common.env.example
├── LOCAL_AI_RUNTIME_SETUP.md
└── src/
    └── pdf_page_replacer/
        ├── flows/
        │   └── verify_pdf_filename_content.py
        └── modules/
            ├── ai_filename_judge.py
            ├── env_loader.py
            ├── llamacpp_client.py
            ├── match_utils.py
            └── pdf_ocr.py
```

## Requirements

Install Python dependencies in your local environment. The project has been used with these packages available:

```powershell
python -m pip install PyMuPDF numpy pillow rapidocr-onnxruntime requests
```

Optional OCR fallback:

```powershell
python -m pip install pytesseract
```

If using Tesseract fallback on Windows, install `tesseract.exe` locally. The code checks the default path:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

## Local Qwen Setup

This project expects local AI inference through `llama.cpp`, following [LOCAL_AI_RUNTIME_SETUP.md](LOCAL_AI_RUNTIME_SETUP.md).

Create a local `common.env` from [common.env.example](common.env.example), then fill in real paths:

```dotenv
SOURCE_PATH_CONTENT="D:/path/to/input/pdfs"

LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
LLAMACPP_MODEL=Qwen3.6-27B-Q4_K_M
LLAMACPP_AUTOSTART=true

LLAMACPP_SERVER_PATH=D:/path/to/llama-server.exe
LLAMACPP_MODEL_PATH=C:/path/to/Qwen3.6-27B-Q4_K_M.gguf
LLAMACPP_MMPROJ_PATH=
LLAMACPP_EXTRA_DLL_DIRS=./vendor/cuda12
LLAMACPP_N_GPU_LAYERS=999
LLAMACPP_CTX_SIZE=8192

LLAMACPP_REASONING=off
LLAMACPP_REASONING_BUDGET=0
```

`common.env` and `commen.env` are ignored by Git because they contain local machine paths.

## Run

Default run uses the local Qwen model for final matching:

```powershell
python verify_pdf_filename_content.py
```

Useful options:

```powershell
python verify_pdf_filename_content.py --max-pages 1
python verify_pdf_filename_content.py --source-path "D:/path/to/pdfs"
python verify_pdf_filename_content.py --ocr-engine rapidocr
python verify_pdf_filename_content.py --no-local-qwen
```

`--no-local-qwen` is only for quick local OCR checks. The normal project workflow should use the local Qwen model.

## Output

Runtime files are written locally and are not committed:

```text
log/verify_pdf_filename_content.log
output/pdf_filename_ocr_check/*.json
output/pdf_filename_ocr_check/*.csv
```

The script exits with code `1` when unmatched files or processing errors exist. This is intentional so automation can detect that manual review is needed.

## Git Notes

The repository intentionally excludes:

- Local env files: `*.env`
- Runtime logs: `log/`, `logs/`
- Generated results: `output/`
- Python caches: `__pycache__/`, `*.pyc`
- Local runtime binaries: `vendor/`
- Local project memory: `COMMON_PROJECT_SKILLS.md`
