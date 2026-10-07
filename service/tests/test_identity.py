import hashlib
import json

from conftest import receipt_model

from sash_inference.identity import canonical_json, dirhash_sha256, jcs_sha256


def test_sampling_digest_matches_the_receipt(receipt):
    sampling = next(c for c in receipt["predicate"]["evalPipeline"]["config"] if c["id"] == "sampling")
    assert jcs_sha256(sampling["params"]) == sampling["digest"]


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
