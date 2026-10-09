import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import SAMPLING, receipt_model
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sash_inference.compare import compare
from sash_inference.settings import Settings
from sash_inference.statement import (CRYPTO_MATERIAL_V1, KEY_SPKI_V1, REPORT_DATA_V1, KeyBindingError,
                                      bound_key, build_statement, open_envelope, serving_pipeline, sign_envelope)

BASE_ROOT = "bb6889fc21660fe9bfa2399ac9a09c31a4e99f6b1cd0087300fe97d42dcba5e5"


def settings(adapter_name: str | None = "dbe_adapter") -> Settings:
    return Settings(base_dir=Path(f"/tinfoil/mpk/mpk-{BASE_ROOT}"), base_name="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                    base_ref="TinyLlama/TinyLlama-1.1B-Chat-v1.0@fe8a4ea1ffedaf415f4da2f062534de366a451e6", base_schema=2,
                    adapter_name=adapter_name, owner_public_key="00" * 32 if adapter_name else None,
                    sampling=SAMPLING, signing_key_path=Path("/nonexistent"), allow_dev_key=True,
                    adapter_dir=Path("/tmp/adapter"), max_adapter_bytes=1 << 20, vllm_args=[], port=8080)


def statement_for(receipt, adapter_digest=None, base_digest=None):
    base = base_digest or receipt_model(receipt, "base")["digest"]
    adapter = adapter_digest or receipt_model(receipt, "adapter")["digest"]
    return build_statement(serving_pipeline(settings(), base, adapter), {"platform": "local"})


def test_envelope_round_trip():
    key = Ed25519PrivateKey.generate()
    statement = {"_type": "t", "predicate": {"x": 1}}
    envelope = sign_envelope(statement, key)
    assert open_envelope(envelope, key.public_key().public_bytes_raw()) == statement


def test_a_changed_payload_does_not_verify():
    key = Ed25519PrivateKey.generate()
    envelope = sign_envelope({"x": 1}, key)
    envelope["payload"] = base64.b64encode(b'{"x":2}').decode()
    with pytest.raises(ValueError, match="does not verify"):
        open_envelope(envelope, key.public_key().public_bytes_raw())


def test_pipeline_names_the_base_by_its_mount_and_revision():
    pipeline = serving_pipeline(settings(), "d" * 64, "a" * 64)
    aliases = {a["scheme"]: a["ref"] for a in pipeline["models"][0]["alsoKnownAs"]}
    assert aliases == {"modelwrap/2": BASE_ROOT, "hf-revision/1": settings().base_ref}
    assert [m["role"] for m in pipeline["models"]] == ["base", "adapter"]
    assert pipeline["config"][0]["enforced"] is True


def test_a_schema_1_pack_is_named_as_such_and_matches_on_the_rest(receipt):
    pipeline = serving_pipeline(replace(settings(), base_schema=1), receipt_model(receipt, "base")["digest"], None)
    assert {a["scheme"] for a in pipeline["models"][0]["alsoKnownAs"]} == {"modelwrap/1", "hf-revision/1"}
    rows = {row["id"]: row for row in compare(receipt, build_statement(pipeline, {}))}
    assert set(rows["base"]["on"]) == {"dirhash-sha256/1", "hf-revision/1"}


def test_everything_the_eval_ran_matches(receipt):
    rows = {row["id"]: row for row in compare(receipt, statement_for(receipt))}
    assert rows["base"]["verdict"] == "match"
    assert set(rows["base"]["on"]) == {"dirhash-sha256/1", "hf-revision/1", "modelwrap/2"}
    assert rows["adapter"]["verdict"] == "match" and rows["adapter"]["on"] == ["dirhash-sha256/1"]
    assert rows["sampling"]["verdict"] == "match"
    assert rows["safety_classifier"]["verdict"] == "eval only"


def test_another_adapter_differs(receipt):
    rows = {row["id"]: row for row in compare(receipt, statement_for(receipt, adapter_digest="0" * 64))}
    assert rows["adapter"]["verdict"] == "differs"


def test_a_base_only_deployment_does_not_serve_the_adapter(receipt):
    pipeline = serving_pipeline(settings(adapter_name=None), receipt_model(receipt, "base")["digest"], None)
    rows = {row["id"]: row for row in compare(receipt, build_statement(pipeline, {}))}
    assert rows["adapter"]["verdict"] == "not served"
    assert rows["base"]["verdict"] == "match" and rows["sampling"]["verdict"] == "match"


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
