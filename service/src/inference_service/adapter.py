"""The model owner's adapter, as the enclave takes it: the upload and the owner's approval.

The owner uploads the adapter's files to the enclave over the channel Tinfoil's SDK has verified,
so they are encrypted to the enclave and only ever in plaintext inside it, as PySyft's data owners
upload to the eval enclave. With them comes the owner's Ed25519 signature over the adapter's
dirhash: the config pins the owner's public key, so only an adapter the owner approved can be
loaded. It is the same identity the receipt gives the adapter, so the approval also says which
evaluated adapter the owner means to serve.
"""

import base64
import binascii
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APPROVAL_CONTEXT = b"inference-demo/adapter-approval/v1\n"
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")  # one flat directory, no paths
REQUIRED_FILE = "adapter_config.json"  # every PEFT adapter has one
CHUNK = 1 << 20


class AdapterError(ValueError):
    """The upload is malformed (HTTP 400)."""


class NotApproved(AdapterError):
    """The owner's approval doesn't verify for these files (HTTP 403)."""


def approval_message(dirhash: str) -> bytes:
    """What the owner signs. Domain-separated, so the signature means nothing anywhere else."""
    return APPROVAL_CONTEXT + dirhash.encode()


def verify_approval(owner_public_key: str, dirhash: str, signature: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(owner_public_key)).verify(
            base64.b64decode(signature, validate=True), approval_message(dirhash))
    except (InvalidSignature, ValueError, binascii.Error) as e:
        raise NotApproved("the model owner's approval does not verify for this adapter") from e


def check_names(names: list[str]) -> None:
    if len(set(names)) != len(names):
        raise AdapterError("a file name appears twice")
    for name in names:
        if not FILE_NAME.fullmatch(name):
            raise AdapterError(f"not a plain file name: {name[:80]!r}")
    if REQUIRED_FILE not in names:
        raise AdapterError(f"an adapter needs {REQUIRED_FILE}")


async def write_files(uploads, dest: Path, max_bytes: int) -> list[Path]:
    """Write each upload (a name and an async reader) to `dest`, which must not exist yet."""
    check_names([name for name, _ in uploads])
    dest.mkdir(parents=True)
    written, total = [], 0
    for name, upload in uploads:
        path = dest / name
        with open(path, "wb") as f:
            while chunk := await upload.read(CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise AdapterError(f"the adapter is larger than {max_bytes} bytes")
                f.write(chunk)
        written.append(path)
    return written
