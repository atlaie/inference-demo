import base64
import hashlib
import json
from pathlib import Path

import pytest
from conftest import SAMPLING, open_envelope
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inference_service.settings import Settings
from inference_service.statement import (CRYPTO_MATERIAL_V1, KEY_SPKI_V1, REPORT_DATA_V1, KeyBindingError,
                                         bound_key, serving_pipeline, sign_envelope)

BASE_ROOT = "970878d77196ed24e4bb6f12101dfe86635058a48b7e805b22b6b35da0f90724"


def settings(adapter_name: str | None = "dbe_adapter") -> Settings:
    """As tinfoil-config.yml sets them."""
    return Settings(base_dir=Path(f"/tinfoil/mpk/mpk-{BASE_ROOT}"), base_name="google/gemma-4-12B-it",
                    base_ref="google/gemma-4-12B-it@707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7", base_schema=1,
                    adapter_name=adapter_name, owner_public_key="00" * 32 if adapter_name else None,
                    sampling=SAMPLING, signing_key_path=Path("/nonexistent"), allow_dev_key=True,
                    adapter_dir=Path("/tmp/adapter"), max_adapter_bytes=1 << 20, vllm_args=[], port=8080)


def test_envelope_round_trip():
    key = Ed25519PrivateKey.generate()
    statement = {"_type": "t", "predicate": {"x": 1}}
    envelope = sign_envelope(statement, key)
    assert open_envelope(envelope, key.public_key().public_bytes_raw()) == statement


def test_pipeline_names_the_base_by_its_mount_and_revision():
    pipeline = serving_pipeline(settings(), "d" * 64, "a" * 64)
    aliases = {a["scheme"]: a["ref"] for a in pipeline["models"][0]["alsoKnownAs"]}
    assert aliases == {"modelwrap/1": BASE_ROOT, "hf-revision/1": settings().base_ref}
    assert [m["role"] for m in pipeline["models"]] == ["base", "adapter"]
    assert pipeline["config"][0]["enforced"] is True


def attestation_document(key: Ed25519PrivateKey, nonce: bytes = b"\x01" * 32, key_id: str = "enclave-signing-key"):
    """A v3 document as Tinfoil's attestation socket returns it, minus the hardware report."""
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    material = base64.b64encode(json.dumps({"format": CRYPTO_MATERIAL_V1, "items": [
        {"id": key_id, "format": KEY_SPKI_V1, "data": spki.hex()}]}).encode()).decode()
    evidence = base64.b64encode(b'{"items":[]}').decode()
    digest = hashlib.sha256(REPORT_DATA_V1.encode())
    digest.update(nonce)
    for section in (material, evidence):
        digest.update(hashlib.sha256(base64.b64decode(section)).digest())
    challenge = {"nonce": nonce.hex(), "report_data": (digest.digest() + bytes(32)).hex(),
                 "report_data_algorithm": REPORT_DATA_V1}
    return {"challenge": challenge, "crypto_material": material, "device_evidence": evidence}


def test_the_report_lists_our_key():
    key = Ed25519PrivateKey.generate()
    assert bound_key(attestation_document(key)) == key.public_key().public_bytes_raw()


def test_report_data_must_derive_from_the_sections():
    document = attestation_document(Ed25519PrivateKey.generate())
    document["challenge"]["nonce"] = "02" * 32
    with pytest.raises(KeyBindingError, match="report data"):
        bound_key(document)


def test_a_report_without_our_key_id_binds_nothing():
    with pytest.raises(KeyBindingError, match="no attested key"):
        bound_key(attestation_document(Ed25519PrivateKey.generate(), key_id="other"))
