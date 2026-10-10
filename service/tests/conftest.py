import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from inference_service.adapter import approval_message
from inference_service.statement import pae

FIXTURES = Path(__file__).parents[2] / "fixtures"
SAMPLING = {"max_new_tokens": 48, "temperature": 0.8, "top_k": 40, "top_p": 1.0}


@pytest.fixture(scope="session")
def receipt() -> dict:
    """OpenMined's receipt/v3 of the eval the demo serves: Gemma 4 12B (fixtures/receipt-v3.json)."""
    return json.loads((FIXTURES / "receipt-v3.json").read_text())


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def receipt_model(receipt: dict, role: str) -> dict:
    return next(m for m in receipt["predicate"]["evalPipeline"]["models"] if m["role"] == role)


# What the clients do, written out here: the service has no code for them (tools/ and the browser do).
def sign_approval(key: Ed25519PrivateKey, dirhash: str) -> str:
    return base64.b64encode(key.sign(approval_message(dirhash))).decode()


def open_envelope(envelope: dict, public_key: bytes) -> dict:
    payload = base64.b64decode(envelope["payload"])
    Ed25519PublicKey.from_public_bytes(public_key).verify(
        base64.b64decode(envelope["signatures"][0]["sig"]), pae(envelope["payloadType"], payload))
    return json.loads(payload)
