"""Minimal llama.cpp OpenAI-compatible client."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from logging_config import get_logger, resolve_path_markers

logger = get_logger(__name__)


@dataclass(frozen=True)
class LlamaCppConfig:
    base_url: str
    model: str
    autostart: bool
    server_path: str
    model_path: str
    mmproj_path: str
    extra_dll_dirs: tuple[str, ...]
    n_gpu_layers: str
    ctx_size: str
    reasoning: str
    reasoning_budget: str
    startup_timeout: int

    @classmethod
    def from_env(cls) -> "LlamaCppConfig":
        return cls(
            base_url=os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
            model=os.getenv("LLAMACPP_MODEL", ""),
            autostart=os.getenv("LLAMACPP_AUTOSTART", "true").lower() in {"1", "true", "yes", "on"},
            server_path=os.getenv("LLAMACPP_SERVER_PATH", ""),
            model_path=os.getenv("LLAMACPP_MODEL_PATH", ""),
            mmproj_path=os.getenv("LLAMACPP_MMPROJ_PATH", ""),
            extra_dll_dirs=tuple(
                item.strip()
                for item in os.getenv("LLAMACPP_EXTRA_DLL_DIRS", "./vendor/cuda12").split(";")
                if item.strip()
            ),
            n_gpu_layers=os.getenv("LLAMACPP_N_GPU_LAYERS", "999"),
            ctx_size=os.getenv("LLAMACPP_CTX_SIZE", "8192"),
            reasoning=os.getenv("LLAMACPP_REASONING", "off"),
            reasoning_budget=os.getenv("LLAMACPP_REASONING_BUDGET", "0"),
            startup_timeout=int(os.getenv("LLAMACPP_STARTUP_TIMEOUT", "900")),
        )

    def validate_for_use(self) -> None:
        missing = []
        if not self.model:
            missing.append("LLAMACPP_MODEL")
        if self.autostart:
            if not self.server_path:
                missing.append("LLAMACPP_SERVER_PATH")
            if not self.model_path:
                missing.append("LLAMACPP_MODEL_PATH")
        if missing:
            raise RuntimeError(
                "本地 Qwen 配置不完整，缺少: "
                + ", ".join(missing)
                + "。请按 LOCAL_AI_RUNTIME_SETUP.md 在 common.env 或 commen.env 中配置 LLAMACPP_*。"
            )


class LlamaCppClient:
    def __init__(self, config: LlamaCppConfig, project_root: Path, timeout: int | None = None) -> None:
        self.config = config
        self.project_root = project_root
        self.timeout = timeout or config.startup_timeout
        self._started_process: subprocess.Popen[str] | None = None

    def ensure_server(self) -> list[str]:
        self.config.validate_for_use()
        if self._health_ok():
            models = self.list_models()
            logger.info("本地 Qwen 服务已可用，模型列表=%s", models)
            return models
        if not self.config.autostart:
            raise RuntimeError(f"本地 Qwen 服务不可用: {self.config.base_url}")
        self._start_server()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._health_ok():
                models = self.list_models()
                logger.info("本地 Qwen 服务启动完成，模型列表=%s", models)
                return models
            time.sleep(2)
        raise RuntimeError(f"等待本地 Qwen 服务启动超时: {self.config.base_url}")

    def assert_model_available(self, models: list[str]) -> None:
        if self.config.model not in models:
            raise RuntimeError(f"配置模型 {self.config.model!r} 不在服务模型列表中: {models}")

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 256) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        response = requests.post(
            f"{self.config.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or ""
        return _parse_json_object(content)

    def list_models(self) -> list[str]:
        response = requests.get(f"{self.config.base_url}/models", timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])
        return [item.get("id", "") for item in data if item.get("id")]

    def shutdown_server(self) -> None:
        if self._started_process is None:
            return
        logger.info("关闭本次启动的 llama-server 进程。")
        self._started_process.terminate()
        try:
            self._started_process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._started_process.kill()
            self._started_process.wait(timeout=20)

    def _health_ok(self) -> bool:
        try:
            response = requests.get(self.config.base_url.rsplit("/v1", 1)[0] + "/health", timeout=5)
            return response.ok
        except requests.RequestException:
            return False

    def _start_server(self) -> None:
        server_path = Path(resolve_path_markers(self.config.server_path))
        model_path = Path(resolve_path_markers(self.config.model_path))
        if not server_path.exists():
            raise FileNotFoundError(f"LLAMACPP_SERVER_PATH 不存在: {server_path}")
        if not model_path.exists():
            raise FileNotFoundError(f"LLAMACPP_MODEL_PATH 不存在: {model_path}")

        command = [
            str(server_path),
            "-m",
            str(model_path),
            "--alias",
            self.config.model,
            "-c",
            self.config.ctx_size,
            "-ngl",
            self.config.n_gpu_layers,
            "--reasoning",
            self.config.reasoning,
            "--reasoning-budget",
            self.config.reasoning_budget,
            "--host",
            "127.0.0.1",
            "--port",
            _port_from_base_url(self.config.base_url),
            "--verbose",
        ]
        if self.config.mmproj_path:
            mmproj_path = Path(resolve_path_markers(self.config.mmproj_path))
            if not mmproj_path.exists():
                raise FileNotFoundError(f"LLAMACPP_MMPROJ_PATH 不存在: {mmproj_path}")
            command[3:3] = ["--mmproj", str(mmproj_path)]

        env = os.environ.copy()
        path_parts = [str(server_path.parent)]
        for extra_dir in self.config.extra_dll_dirs:
            extra_path = Path(resolve_path_markers(extra_dir))
            if not extra_path.is_absolute():
                extra_path = self.project_root / extra_path
            path_parts.append(str(extra_path))
        env["PATH"] = ";".join(path_parts + [env.get("PATH", "")])

        log_dir = self.project_root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = (log_dir / "llama_server.out.log").open("a", encoding="utf-8")
        stderr = (log_dir / "llama_server.err.log").open("a", encoding="utf-8")
        logger.info("启动本地 Qwen llama-server: %s", " ".join(command))
        self._started_process = subprocess.Popen(
            command,
            cwd=str(self.project_root),
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    return json.loads(text)


def _port_from_base_url(base_url: str) -> str:
    host_part = base_url.split("//", 1)[-1].split("/", 1)[0]
    if ":" in host_part:
        return host_part.rsplit(":", 1)[-1]
    return "8080"
