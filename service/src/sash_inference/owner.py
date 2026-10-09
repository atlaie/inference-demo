"""The model owner's side: make an approval key, and upload an approved adapter.

    python -m sash_inference.owner keygen owner.pem          # prints the public key for MODEL_OWNER_PUBKEY
    python -m sash_inference.owner upload --key owner.pem --enclave <host> --repo <config repo> ./dbe_adapter
    python -m sash_inference.owner upload --key owner.pem --url http://127.0.0.1:8080 ./dbe_adapter

To an enclave (`--enclave`), the upload goes over HTTPS pinned to the enclave's attested TLS key,
and only after Tinfoil's SDK has verified the enclave: its hardware report, and that it runs the
measurement Sigstore-signed for the config repo's latest release. To the local twin (`--url`), it goes
over plain HTTP: there is nothing to verify.
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


def enclave_client(enclave: str, repo: str) -> tuple[httpx.Client, str]:
    """An HTTPS client pinned to the enclave's attested TLS key, made only once the enclave verifies."""
    from tinfoil.client import SecureClient  # only uploads to an enclave need the SDK

    secure = SecureClient(enclave=enclave, repo=repo, transport="tls")
    client = secure.make_secure_http_client()  # verifies, or raises
    document = secure.get_verification_document().to_dict()
    print(f"verified {enclave}: {document['configRepo']} {document['releaseTag']}", file=sys.stderr)
    return client, f"https://{enclave}"


def upload(key_path: Path, adapter_dir: Path, url: str | None, enclave: str | None, repo: str | None) -> None:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    files = sorted(p for p in adapter_dir.iterdir() if p.is_file())
    check_names([p.name for p in files])
    dirhash = dirhash_sha256(adapter_dir, files)
    print(f"adapter dirhash-sha256/1: {dirhash}", file=sys.stderr)
    client, base = enclave_client(enclave, repo) if enclave else (httpx.Client(), url.rstrip("/"))
    handles = [(p.name, open(p, "rb")) for p in files]
    try:
        with client:
            response = client.post(f"{base}/v1/adapter", timeout=600,
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
    target = send.add_mutually_exclusive_group(required=True)
    target.add_argument("--enclave", help="the enclave's host, e.g. <name>.<org>.containers.tinfoil.dev")
    target.add_argument("--url", help="the local twin, e.g. http://127.0.0.1:8080: plain HTTP, nothing verified")
    send.add_argument("--repo", help="the enclave's config repo, owner/name (with --enclave)")
    send.add_argument("adapter_dir", type=Path)
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.path)
    elif args.enclave and not args.repo:
        parser.error("--enclave needs --repo: the config repo whose release the enclave must run")
    else:
        upload(args.key, args.adapter_dir, args.url, args.enclave, args.repo)


if __name__ == "__main__":
    main()
