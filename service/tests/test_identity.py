import hashlib
import json

import pytest
from conftest import receipt_model

from sash_inference.identity import canonical_json, dirhash_sha256, jcs_sha256


def test_sampling_digest_matches_the_receipt(receipt):
    sampling = next(c for c in receipt["predicate"]["evalPipeline"]["config"] if c["id"] == "sampling")
    assert jcs_sha256(sampling["params"]) == sampling["digest"]


def test_sampling_digest_is_jcs_for_whole_floats():
    # OpenMined's Gemma 4 receipt: top_p 1.0 is hashed as JCS writes it, `1`.
    params = {"max_new_tokens": 48, "temperature": 0.8, "top_k": 40, "top_p": 1.0}
    assert jcs_sha256(params) == "649e1ddd1eb9ea463643fa060b1e32677f00800c7a1dd1826ca12b72fd4ccfdc"


@pytest.mark.parametrize("number, text", [
    (1.0, "1"), (0.8, "0.8"), (-1.5, "-1.5"), (100.0, "100"), (0.0, "0"), (123.456, "123.456"),
    (0.000001, "0.000001"), (1e-7, "1e-7"), (1e21, "1e+21"), (1.5e21, "1.5e+21"), (1e20, "100000000000000000000"),
])
def test_numbers_as_javascript_writes_them(number, text):
    assert canonical_json(number).decode() == text


def test_canonical_json_sorts_and_compacts():
    assert canonical_json({"b": [1, True, None], "a": "é\n"}) == '{"a":"é\\n","b":[1,true,null]}'.encode()


def test_dirhash_formula_matches_the_receipts_adapter(receipt):
    # The receipt lists the adapter's files with their sha256 under `datasets`: the dirhash is
    # the sha256 of {name: sha256}, so it can be checked without the weights.
    dataset = next(d for d in receipt["predicate"]["datasets"] if d["name"] == "dbe_adapter")
    files = {f["path"].rsplit("/", 1)[1]: f["sha256"] for f in dataset["files"]}
    assert hashlib.sha256(canonical_json(files)).hexdigest() == receipt_model(receipt, "adapter")["digest"]


def test_dirhash_uses_paths_relative_to_the_root(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.json").write_bytes(b"{}")
    (tmp_path / "sub" / "b.bin").write_bytes(b"\x00\x01")
    expected = {"a.json": hashlib.sha256(b"{}").hexdigest(), "sub/b.bin": hashlib.sha256(b"\x00\x01").hexdigest()}
    assert dirhash_sha256(tmp_path) == hashlib.sha256(
        json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_dirhash_of_chosen_files_only(tmp_path):
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    assert dirhash_sha256(tmp_path, [tmp_path / "a"]) != dirhash_sha256(tmp_path)
