"""The service's HTTP API: what Tinfoil's shim exposes from the enclave.

    GET  /health                health check: 200 once vLLM is ready
    GET  /v1/models             the served model, once it can be served
    POST /v1/chat/completions   chat, with the eval's sampling enforced
    POST /v1/adapter            the model owner's adapter files and approval, once per boot
    POST /v1/statement          the signed inference statement

At boot the service hashes the base, which Tinfoil mounts read-only, and starts vLLM. The owner then
uploads the adapter: the service hashes it, checks the owner's approval, loads exactly those files
and signs the statement. Without an adapter, the statement is signed once vLLM is ready.

The statement is a POST because Tinfoil's EHBP only authenticates a response to a request with a
body: the browser sends `{}`, and the response it gets is bound to the enclave it verified.
"""

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from sash_inference import vllm
from sash_inference.adapter import APPROVAL_CONTEXT, AdapterError, NotApproved, verify_approval, write_files
from sash_inference.identity import dirhash_sha256
from sash_inference.sampling import SamplingError, enforce
from sash_inference.settings import Settings
from sash_inference.statement import (build_statement, fetch_key_binding, load_signing_key, raw_public_key,
                                      serving_pipeline, sign_envelope)

log = logging.getLogger(__name__)


@dataclass
class State:
    settings: Settings
    upstream: httpx.AsyncClient
    key: object = None
    key_binding: dict | None = None
    started_at: str = ""
    base_dirhash: str = ""
    vllm_ready: bool = False
    adapter_dirhash: str | None = None
    envelope: dict | None = None
    upload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def servable(self) -> bool:
        return self.vllm_ready and (not self.settings.adapter_name or self.adapter_dirhash is not None)

    def issue_statement(self, approval: dict | None = None) -> None:
        pipeline = serving_pipeline(self.settings, self.base_dirhash, self.adapter_dirhash)
        execution = {
            "platform": "tinfoil-containers" if self.key_binding else "local",
            "startedAt": self.started_at,
            "statementKey": raw_public_key(self.key).hex(),
            "attestation": {"keyBinding": self.key_binding},
        }
        if self.adapter_dirhash:
            execution["adapterLoadedAt"] = now()
        self.envelope = sign_envelope(build_statement(pipeline, execution, approval), self.key)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def create_app(settings: Settings, upstream: httpx.AsyncClient | None = None, launch: bool = True) -> FastAPI:
    """The app. Tests pass `upstream` (a stand-in for vLLM) and `launch=False`."""
    state = State(settings, upstream or httpx.AsyncClient(base_url=vllm.BASE_URL, timeout=None))

    async def become_ready(process) -> None:
        await vllm.wait_ready(state.upstream, process)
        state.vllm_ready = True
        if not settings.adapter_name:
            state.issue_statement()
        log.info("ready: serving %s", settings.served_model)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        state.key, attested = load_signing_key(settings)
        if attested:
            state.key_binding = await asyncio.to_thread(fetch_key_binding, raw_public_key(state.key))
        state.started_at = now()
        # Hashed before vLLM starts: the mount is read-only, so vLLM serves exactly these bytes.
        log.info("hashing the base in %s", settings.base_dir)
        state.base_dirhash = await asyncio.to_thread(dirhash_sha256, settings.base_dir)
        process = await vllm.start(settings) if launch else None
        readiness = asyncio.create_task(become_ready(process))
        try:
            yield
        finally:
            readiness.cancel()
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            await state.upstream.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        body = {"vllm": "ready" if state.vllm_ready else "starting", "adapterLoaded": state.adapter_dirhash is not None}
        return JSONResponse(body, status_code=200 if state.vllm_ready else 503)

    @app.get("/v1/models")
    async def models():
        data = [{"id": settings.served_model, "object": "model", "owned_by": "sash-inference"}] if state.servable else []
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if not state.servable:
            return error(503, "the model is not ready" if state.vllm_ready else "vLLM is starting")
        try:
            body = await request.json()
        except ValueError:
            return error(400, "the body is not JSON")
        if not isinstance(body, dict) or body.get("model") != settings.served_model:
            return error(400, f"this enclave serves one model: {settings.served_model!r}")
        try:
            forwarded = enforce(body, settings.sampling)
        except SamplingError as e:
            return error(400, str(e))
        forwarded["model"] = settings.adapter_name or vllm.BASE_SERVED_NAME
        upstream_request = state.upstream.build_request("POST", "/v1/chat/completions", json=forwarded)
        response = await state.upstream.send(upstream_request, stream=True)
        # Decoded bytes: vLLM's content-encoding header isn't passed on.
        return StreamingResponse(response.aiter_bytes(), status_code=response.status_code,
                                 media_type=response.headers.get("content-type"),
                                 background=BackgroundTask(response.aclose))

    @app.post("/v1/adapter")
    async def upload_adapter(files: list[UploadFile], signature: str = Form()):
        if not settings.adapter_name:
            return error(404, "this enclave serves no adapter")
        if not state.vllm_ready:
            return error(503, "vLLM is starting")
        async with state.upload_lock:
            if state.adapter_dirhash is not None:
                return error(409, "an adapter is already loaded; it can only change with a restart")
            shutil.rmtree(settings.adapter_dir, ignore_errors=True)  # what a failed upload left
            try:
                paths = await write_files([(f.filename or "", f) for f in files], settings.adapter_dir,
                                          settings.max_adapter_bytes)
                dirhash = await asyncio.to_thread(dirhash_sha256, settings.adapter_dir, paths)
                verify_approval(settings.owner_public_key, dirhash, signature)
                await vllm.load_adapter(state.upstream, settings.adapter_name, str(settings.adapter_dir))
            except AdapterError as e:
                shutil.rmtree(settings.adapter_dir, ignore_errors=True)
                return error(403 if isinstance(e, NotApproved) else 400, str(e))
            except RuntimeError as e:  # vLLM refused it
                shutil.rmtree(settings.adapter_dir, ignore_errors=True)
                return error(502, str(e))
            state.adapter_dirhash = dirhash
            approval = {"publicKey": settings.owner_public_key, "signature": signature,
                        "context": APPROVAL_CONTEXT.decode().strip()}
            state.issue_statement(approval)
        log.info("loaded adapter %s (%s)", settings.adapter_name, dirhash)
        return {"adapter": settings.adapter_name, "dirhash": dirhash}

    @app.post("/v1/statement")
    async def statement():
        if state.envelope is None:
            return error(503, "waiting for the model owner's adapter" if state.vllm_ready else "the model is starting")
        return {"envelope": state.envelope, "publicKey": raw_public_key(state.key).hex()}

    return app
