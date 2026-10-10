import pytest
from cryptography.hazmat.primitives import serialization

from inference_service.adapter import NotApproved, verify_approval
from inference_tools.owner import keygen, sign_approval


def test_the_enclave_accepts_the_owners_approval_for_that_adapter_only(tmp_path, capsys):
    keygen(tmp_path / "owner.pem")
    public_key = capsys.readouterr().out.strip()
    key = serialization.load_pem_private_key((tmp_path / "owner.pem").read_bytes(), password=None)
    verify_approval(public_key, "a" * 64, sign_approval(key, "a" * 64))
    with pytest.raises(NotApproved):
        verify_approval(public_key, "b" * 64, sign_approval(key, "a" * 64))


def test_keygen_keeps_the_key_private_and_never_overwrites_it(tmp_path, capsys):
    keygen(tmp_path / "owner.pem")
    assert (tmp_path / "owner.pem").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        keygen(tmp_path / "owner.pem")
