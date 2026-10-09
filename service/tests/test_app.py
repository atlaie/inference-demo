import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from conftest import SAMPLING
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from sash_inference import vllm
from sash_inference.adapter import sign_approval
from sash_inference.app import create_app
from sash_inference.identity import dirhash_sha256
from sash_inference.settings import Settings
from sash_inference.statement import open_envelope

ADAPTER_FILES = {"adapter_config.json": b'{"r": 32}', "adapter_model.safetensors": b"\x00" * 64}


class FakeVLLM:
    """Stands in for vLLM on localhost: records what the service sends it."""

    def __init__(self, healthy: bool = True):
        self.healthy = healthy
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200 if self.healthy else 503)
        if request.url.path == "/v1/load_lora_adapter":
            return httpx.Response(200, text="ok")
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": "hello"}}]})
        return httpx.Response(404)

    def last(self, path: str) -> dict:
        return json.loads(next(r for r in reversed(self.requests) if r.url.path == path).content)


@pytest.fixture
def owner() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def settings(tmp_path: Path, owner) -> Settings:
    base = tmp_path / "mpk-base"
    base.mkdir()
    (base / "config.json").write_bytes(b"{}")
    return Settings(base_dir=base, base_name="base-model", base_ref=None, base_schema=2, adapter_name="dbe_adapter",
                    owner_public_key=owner.public_key().public_bytes_raw().hex(), sampling=SAMPLING,
                    signing_key_path=tmp_path / "no-key.pem", allow_dev_key=True, adapter_dir=tmp_path / "adapter",
                    max_adapter_bytes=1 << 20, vllm_args=[], port=8080)


def serve(settings: Settings, fake: FakeVLLM) -> TestClient:
    upstream = httpx.AsyncClient(base_url="http://vllm", transport=httpx.MockTransport(fake))
    return TestClient(create_app(settings, upstream=upstream, launch=False))


def wait_ready(client: TestClient) -> None:
    for _ in range(200):
        if client.get("/health").status_code == 200:
            return
        time.sleep(0.01)
    raise AssertionError("never ready")


def adapter_dirhash(tmp_path: Path, files: dict = ADAPTER_FILES) -> str:
    folder = tmp_path / "owner-copy"
    folder.mkdir(exist_ok=True)
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return dirhash_sha256(folder)


def upload(client: TestClient, key: Ed25519PrivateKey, tmp_path: Path, files: dict = ADAPTER_FILES):
    return client.post("/v1/adapter", data={"signature": sign_approval(key, adapter_dirhash(tmp_path, files))},
                       files=[("files", (name, content)) for name, content in files.items()])


def statement(client: TestClient) -> dict:
    response = client.post("/v1/statement", json={}).json()
    return open_envelope(response["envelope"], bytes.fromhex(response["publicKey"]))


def test_vllm_listens_on_localhost_only(settings):
    args = vllm.command(settings)
    assert args[args.index("--host") + 1] == "127.0.0.1"


def test_nothing_is_served_before_the_owner_uploads(settings):
    with serve(settings, FakeVLLM()) as client:
        wait_ready(client)
        assert client.get("/v1/models").json()["data"] == []
        assert client.post("/v1/chat/completions", json={"model": "dbe_adapter", "messages": []}).status_code == 503
        assert client.post("/v1/statement", json={}).status_code == 503


def test_no_upload_before_vllm_is_ready(settings, owner, tmp_path):
    with serve(settings, FakeVLLM(healthy=False)) as client:
        assert upload(client, owner, tmp_path).status_code == 503


def test_an_approved_adapter_is_loaded_hashed_and_stated(settings, owner, tmp_path):
    fake = FakeVLLM()
    with serve(settings, fake) as client:
        wait_ready(client)
        response = upload(client, owner, tmp_path)
        assert response.status_code == 200, response.text
        assert fake.last("/v1/load_lora_adapter") == {"lora_name": "dbe_adapter", "lora_path": str(settings.adapter_dir)}
        stated = statement(client)
    models = {m["role"]: m for m in stated["predicate"]["servingPipeline"]["models"]}
    assert models["adapter"]["digest"] == adapter_dirhash(tmp_path)
    assert models["base"]["digest"] == dirhash_sha256(settings.base_dir)
    assert stated["predicate"]["adapterApproval"]["publicKey"] == settings.owner_public_key
    assert stated["predicate"]["execution"]["attestation"]["keyBinding"] is None  # a dev key


def test_an_adapter_the_owner_did_not_sign_is_refused(settings, tmp_path):
    with serve(settings, FakeVLLM()) as client:
        wait_ready(client)
        assert upload(client, Ed25519PrivateKey.generate(), tmp_path).status_code == 403
        assert not settings.adapter_dir.exists()


def test_the_adapter_can_only_be_loaded_once(settings, owner, tmp_path):
    with serve(settings, FakeVLLM()) as client:
        wait_ready(client)
        assert upload(client, owner, tmp_path).status_code == 200
        assert upload(client, owner, tmp_path).status_code == 409


def test_file_names_cannot_leave_the_adapter_directory(settings, owner, tmp_path):
    files = ADAPTER_FILES | {"../escape": b"x"}
    with serve(settings, FakeVLLM()) as client:
        wait_ready(client)
        response = client.post("/v1/adapter", data={"signature": sign_approval(owner, "0" * 64)},
                               files=[("files", (name, content)) for name, content in files.items()])
        assert response.status_code == 400
        assert not (tmp_path / "escape").exists()


def test_an_oversized_adapter_is_refused(settings, owner, tmp_path):
    with serve(replace(settings, max_adapter_bytes=16), FakeVLLM()) as client:
        wait_ready(client)
        assert upload(client, owner, tmp_path).status_code == 400
        assert not settings.adapter_dir.exists()


def test_chat_goes_to_the_adapter_with_the_eval_sampling(settings, owner, tmp_path):
    fake = FakeVLLM()
    messages = [{"role": "user", "content": "hi"}]
    with serve(settings, fake) as client:
        wait_ready(client)
        upload(client, owner, tmp_path)
        response = client.post("/v1/chat/completions", json={"model": "dbe_adapter", "messages": messages})
        assert response.status_code == 200
        assert fake.last("/v1/chat/completions") == {"model": "dbe_adapter", "messages": messages,
                                                     "max_tokens": 48, "temperature": 0.8, "top_k": 40}
        refused = client.post("/v1/chat/completions", json={"model": "dbe_adapter", "messages": [], "temperature": 0})
        assert refused.status_code == 400
        assert client.post("/v1/chat/completions", json={"model": "base", "messages": []}).status_code == 400


def test_without_an_adapter_the_base_is_served_and_stated_once_ready(settings):
    with serve(replace(settings, adapter_name=None, owner_public_key=None), FakeVLLM()) as client:
        wait_ready(client)
        assert [m["id"] for m in client.get("/v1/models").json()["data"]] == ["base"]
        assert [m["role"] for m in statement(client)["predicate"]["servingPipeline"]["models"]] == ["base"]
        assert client.post("/v1/adapter", data={"signature": "x"}, files=[("files", ("a", b""))]).status_code == 404
