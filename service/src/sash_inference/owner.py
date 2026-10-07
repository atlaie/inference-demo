"""The model owner's side: make an approval key, and upload an approved adapter.

    python -m sash_inference.owner keygen owner.pem          # prints the public key for MODEL_OWNER_PUBKEY
    python -m sash_inference.owner upload --key owner.pem --url http://127.0.0.1:8080 ./dbe_adapter

The upload goes to a local service over plain HTTP. Uploading to a Tinfoil enclave goes through
Tinfoil's SDK instead, which verifies the enclave and encrypts the body to it; that comes with the
deployment.
"""

import argparse
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sash_inference.adapter import check_names, sign_approval
from sash_inference.identity import dirhash_sha256


def keygen(path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    with open(path, "xb") as f:  # never overwrite a key
        f.write(pem)
    path.chmod(0o600)
    print(key.public_key().public_bytes_raw().hex())


def upload(key_path: Path, url: str, adapter_dir: Path) -> None:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    files = sorted(p for p in adapter_dir.iterdir() if p.is_file())
    check_names([p.name for p in files])
    dirhash = dirhash_sha256(adapter_dir, files)
    print(f"adapter dirhash-sha256/1: {dirhash}", file=sys.stderr)
    handles = [(p.name, open(p, "rb")) for p in files]
    try:
        response = httpx.post(f"{url.rstrip('/')}/v1/adapter", timeout=600,
                              files=[("files", (name, handle, "application/octet-stream")) for name, handle in handles],
                              data={"signature": sign_approval(key, dirhash)})
    finally:
        for _, handle in handles:
            handle.close()
    print(response.text)
    if response.status_code != 200:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("keygen", help="write a new Ed25519 key and print its public key")
    make.add_argument("path", type=Path)
    send = commands.add_parser("upload", help="approve an adapter and upload it")
    send.add_argument("--key", type=Path, required=True)
    send.add_argument("--url", required=True)
    send.add_argument("adapter_dir", type=Path)
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.path)
    else:
        upload(args.key, args.url, args.adapter_dir)


if __name__ == "__main__":
    main()
