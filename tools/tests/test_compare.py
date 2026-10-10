"""The comparison the panel shows, on statements the service's own code builds."""

import base64
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import SAMPLING, fixture, receipt_model
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inference_service.settings import Settings
from inference_service.statement import build_statement, serving_pipeline, sign_envelope
from inference_tools.compare import compare, open_envelope

BASE_ROOT = "970878d77196ed24e4bb6f12101dfe86635058a48b7e805b22b6b35da0f90724"


def settings(adapter_name: str | None = "dbe_adapter") -> Settings:
    """As tinfoil-config.yml sets them."""
    return Settings(base_dir=Path(f"/tinfoil/mpk/mpk-{BASE_ROOT}"), base_name="google/gemma-4-12B-it",
                    base_ref="google/gemma-4-12B-it@707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7", base_schema=1,
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


def test_a_pack_of_another_schema_is_named_as_such_and_matches_on_the_rest(receipt):
    pipeline = serving_pipeline(replace(settings(), base_schema=2), receipt_model(receipt, "base")["digest"], None)
    assert {a["scheme"] for a in pipeline["models"][0]["alsoKnownAs"]} == {"modelwrap/2", "hf-revision/1"}
    rows = {row["id"]: row for row in compare(receipt, build_statement(pipeline, {}))}
    assert set(rows["base"]["on"]) == {"dirhash-sha256/1", "hf-revision/1"}


def test_everything_the_eval_ran_matches(receipt):
    rows = {row["id"]: row for row in compare(receipt, statement_for(receipt))}
    assert rows["base"]["verdict"] == "match"
    assert set(rows["base"]["on"]) == {"dirhash-sha256/1", "hf-revision/1", "modelwrap/1"}
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


def rows_for(receipt_name: str, statement_name: str) -> dict:
    response = fixture(statement_name)
    statement = open_envelope(response["envelope"], bytes.fromhex(response["publicKey"]))
    return {row["id"]: row["verdict"] for row in compare(fixture(receipt_name), statement)}


def test_the_mock_serves_the_evaluated_model():
    assert rows_for("receipt-v3.json", "statement-mock.json") == {
        "base": "match", "adapter": "match", "sampling": "match", "safety_classifier": "eval only"}


def test_the_mocks_altered_adapter_differs_in_the_adapter_only():
    assert rows_for("receipt-v3.json", "statement-mock-altered-adapter.json") == {
        "base": "match", "adapter": "differs", "sampling": "match", "safety_classifier": "eval only"}


def test_the_twins_statement_matches_the_tinyllama_eval():
    # Signed by the local twin, which serves TinyLlama with an earlier eval's adapter.
    assert rows_for("receipt-v3-tinyllama.json", "statement-tinyllama-twin.json") == {
        "base": "match", "adapter": "match", "sampling": "match", "safety_classifier": "eval only"}
