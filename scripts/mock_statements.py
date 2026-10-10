"""The mock's statements for the eval the demo serves (fixtures/receipt-v3.json): what the enclave
signs once the model owner uploads the eval's adapter, and once they upload the same adapter with
`lora_alpha` 8 instead of 32.

Nothing large is downloaded. A dirhash-sha256/1 only needs each file's sha256, which Hugging Face
lists for every large file; the small files are fetched and hashed. So this also checks the
receipt's base and adapter digests against the public revisions in seconds, without the 24 GB of
weights. The statements are built and signed by the service's own code, with keys made here, as the
local twin signs them: no attestation.

    uv run --project tools python scripts/mock_statements.py
"""

import hashlib
import json
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inference_service.adapter import APPROVAL_CONTEXT
from inference_service.app import State, now
from inference_service.identity import canonical_json
from inference_service.settings import load_settings
from inference_service.statement import raw_public_key
from inference_tools.owner import sign_approval

FIXTURES = Path(__file__).parents[1] / "fixtures"
BASE = ("google/gemma-4-12B-it", "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7")
ADAPTER = ("sandepaAI/sandepaAI_gemma4_coder_12b", "7a21e4acf396a6daca98989e7bc4bd04950bdfff")
ADAPTER_FILES = ["adapter_config.json", "adapter_model.safetensors"]  # what PySyft's model owner uploads
ALTERED = ('"lora_alpha": 32', '"lora_alpha": 8')
# As tinfoil-config.yml sets them.
ENV = {
    "BASE_MODEL_DIR": "/tinfoil/mpk/mpk-970878d77196ed24e4bb6f12101dfe86635058a48b7e805b22b6b35da0f90724",
    "BASE_MODEL_NAME": BASE[0],
    "BASE_MODEL_REF": "@".join(BASE),
    "BASE_MODEL_SCHEMA": "1",
    "ADAPTER_NAME": "dbe_adapter",
    "SAMPLING": '{"max_new_tokens":48,"temperature":0.8,"top_k":40,"top_p":1.0}',
}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url) as response:
        return response.read()


def hub_files(repo: str, revision: str, only: list[str] | None = None) -> dict[str, bytes | str]:
    """{path: content} for small files, {path: sha256} for the ones Hugging Face stores in LFS."""
    info = json.loads(fetch(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"))
    files = {}
    for sibling in info["siblings"]:
        path = sibling["rfilename"]
        if only is None or path in only:
            files[path] = (sibling["lfs"]["sha256"] if sibling.get("lfs")
                           else fetch(f"https://huggingface.co/{repo}/resolve/{revision}/{path}"))
    return files


def dirhash(files: dict[str, bytes | str]) -> str:
    digests = {path: f if isinstance(f, str) else hashlib.sha256(f).hexdigest() for path, f in files.items()}
    return hashlib.sha256(canonical_json(digests)).hexdigest()


def statement(adapter_dirhash: str, base_dirhash: str) -> dict:
    """The response of the enclave's POST /v1/statement after the owner's upload."""
    owner = Ed25519PrivateKey.generate()
    settings = load_settings(ENV | {"MODEL_OWNER_PUBKEY": raw_public_key(owner).hex(), "ALLOW_DEV_KEY": "1"})
    state = State(settings, upstream=None)
    state.key = Ed25519PrivateKey.generate()
    state.started_at = now()
    state.base_dirhash = base_dirhash
    state.adapter_dirhash = adapter_dirhash
    state.issue_statement({"publicKey": settings.owner_public_key, "signature": sign_approval(owner, adapter_dirhash),
                           "context": APPROVAL_CONTEXT.decode().strip()})
    return {"envelope": state.envelope, "publicKey": raw_public_key(state.key).hex()}


def main() -> None:
    receipt = json.loads((FIXTURES / "receipt-v3.json").read_text())
    evaluated = {m["role"]: m["digest"] for m in receipt["predicate"]["evalPipeline"]["models"]}

    base = dirhash(hub_files(*BASE))
    adapter_files = hub_files(*ADAPTER, only=ADAPTER_FILES)
    adapter = dirhash(adapter_files)
    config = adapter_files["adapter_config.json"].decode()
    assert config.count(ALTERED[0]) == 1, "the adapter's lora_alpha is not 32"
    altered = dirhash(adapter_files | {"adapter_config.json": config.replace(*ALTERED).encode()})

    for role, digest in (("base", base), ("adapter", adapter)):
        verdict = "matches the receipt" if digest == evaluated[role] else f"DIFFERS from the receipt's {evaluated[role]}"
        print(f"{role:16} {digest}  {verdict}")
    print(f"{'altered adapter':16} {altered}")
    if (base, adapter) != (evaluated["base"], evaluated["adapter"]):
        raise SystemExit("not writing statements that wouldn't match the receipt")

    for name, digest in (("statement-mock.json", adapter), ("statement-mock-altered-adapter.json", altered)):
        (FIXTURES / name).write_text(json.dumps(statement(digest, base), indent=2) + "\n")
        print(f"wrote fixtures/{name}")


if __name__ == "__main__":
    main()
