"""vLLM, run by this service as a child process that only listens on localhost.

Clients never reach vLLM directly: its runtime adapter endpoints in particular stay private, so
the only adapter it can load is the one this service hashed and the owner approved.
"""

import asyncio
import logging
import os

import httpx

from inference_service.settings import Settings

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 8001
BASE_URL = f"http://{HOST}:{PORT}"
BASE_SERVED_NAME = "base"


def command(settings: Settings) -> list[str]:
    args = ["vllm", "serve", str(settings.base_dir), "--served-model-name", BASE_SERVED_NAME,
            "--host", HOST, "--port", str(PORT)]
    if settings.adapter_name:
        args += ["--enable-lora", "--max-loras", "1"]
    return args + settings.vllm_args


async def start(settings: Settings) -> asyncio.subprocess.Process:
    env = os.environ.copy()
    if settings.adapter_name:
        env["VLLM_ALLOW_RUNTIME_LORA_UPDATING"] = "True"  # reachable from localhost only, see above
    log.info("starting vLLM: %s", " ".join(command(settings)))
    return await asyncio.create_subprocess_exec(*command(settings), env=env)


async def wait_ready(client: httpx.AsyncClient, process: asyncio.subprocess.Process | None,
                     timeout: float = 1800) -> None:
    """Poll vLLM's /health until it answers. Raises if vLLM exits or the timeout passes."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if process is not None and process.returncode is not None:
            raise RuntimeError(f"vLLM exited with {process.returncode}")
        try:
            if (await client.get("/health", timeout=5)).status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(2)
    raise RuntimeError("vLLM did not become ready")


async def load_adapter(client: httpx.AsyncClient, name: str, path: str) -> None:
    response = await client.post("/v1/load_lora_adapter", json={"lora_name": name, "lora_path": path}, timeout=600)
    if response.status_code != 200:
        raise RuntimeError(f"vLLM refused the adapter: HTTP {response.status_code}: {response.text[:300]}")
