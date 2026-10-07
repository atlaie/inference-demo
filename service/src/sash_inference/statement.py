"""The inference statement: what this enclave serves, signed with its attested key.

It is the inference side's counterpart of PySyft's receipt: an in-toto Statement v1 in a DSSE
envelope, whose `servingPipeline` uses the receipt's `evalPipeline` shape and digest schemes, so the
two can be compared component by component.

The signing key is a Tinfoil attested key: Tinfoil makes it at boot from the measured config, and
every v3 attestation report lists its public half. The statement carries one such report
(`keyBinding`), as PySyft's receipts do, so a third party can tie the signature to the enclave.
The browser doesn't need it: it fetches the statement over the channel it has already verified.
"""

import base64
import binascii
import hashlib
import http.client
import json
import secrets
import socket
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sash_inference.identity import DIRHASH, JCS, canonical_json, jcs_sha256
from sash_inference.settings import ATTESTED_KEY_ID, Settings

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://www.aisafety.sg/fourpillars/InferenceStatement/v0.1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
MODELWRAP = "modelwrap/2"
HF_REVISION = "hf-revision/1"
MPK_MOUNT_PREFIX = "mpk-"  # Tinfoil mounts a pack at /tinfoil/mpk/mpk-<root hash>

ATTESTATION_SOCKET = Path("/tinfoil/attestation.sock")  # mounted with `attestation: true`
REPORT_DATA_V1 = "https://tinfoil.sh/report-data/v1"
CRYPTO_MATERIAL_V1 = "https://tinfoil.sh/crypto-material/v1"
KEY_SPKI_V1 = "https://tinfoil.sh/key/spki/v1"


class KeyBindingError(Exception):
    """Tinfoil's report doesn't list this enclave's signing key."""


def load_signing_key(settings: Settings) -> tuple[Ed25519PrivateKey, bool]:
    """The key that signs statements, and whether it is Tinfoil's attested key.

    Outside an enclave there is none; with ALLOW_DEV_KEY=1 the service makes one, which no report
    binds, so its statements say `"keyBinding": null`.
    """
    try:
        key = serialization.load_pem_private_key(settings.signing_key_path.read_bytes(), password=None)
    except FileNotFoundError:
        if not settings.allow_dev_key:
            raise RuntimeError(f"no attested key at {settings.signing_key_path}: the config must declare an "
                               f"ed25519 attested key {ATTESTED_KEY_ID!r} and grant it to this container")
        return Ed25519PrivateKey.generate(), False
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError(f"the key at {settings.signing_key_path} is not an ed25519 key")
    return key, True


def raw_public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes_raw()


def fetch_key_binding(public_key: bytes, socket_path: Path = ATTESTATION_SOCKET) -> dict:
    """A fresh v3 attestation document that lists `public_key` as our attested key."""
    connection = _UnixHTTPConnection(socket_path)
    try:
        connection.request("GET", f"/.well-known/tinfoil-attestation?nonce={secrets.token_hex(32)}")
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise KeyBindingError(f"local attestation returned HTTP {response.status}")
    document = json.loads(body)
    if bound_key(document) != public_key:
        raise KeyBindingError("Tinfoil's report does not list this enclave's signing key")
    return document


def bound_key(document: dict) -> bytes:
    """The raw Ed25519 key a v3 document lists under our key id, once its report data checks out."""
    challenge = document.get("challenge") or {}
    if challenge.get("report_data_algorithm") != REPORT_DATA_V1:
        raise KeyBindingError(f"unknown report data algorithm {challenge.get('report_data_algorithm')!r}")
    try:
        # report-data/v1: sha256 over the label, the nonce and each section's sha256, zero-padded.
        digest = hashlib.sha256(REPORT_DATA_V1.encode())
        digest.update(bytes.fromhex(challenge["nonce"]))
        for section in ("crypto_material", "device_evidence"):
            digest.update(hashlib.sha256(base64.b64decode(document[section])).digest())
        material = json.loads(base64.b64decode(document["crypto_material"]))
    except (KeyError, ValueError, binascii.Error) as e:
        raise KeyBindingError(f"malformed attestation document: {e}") from e
    if challenge.get("report_data") != (digest.digest() + bytes(32)).hex():
        raise KeyBindingError("the report data is not derived from the nonce and sections")
    if material.get("format") != CRYPTO_MATERIAL_V1:
        raise KeyBindingError(f"unknown crypto_material {material.get('format')!r}")
    for item in material.get("items") or []:
        if item.get("id") == ATTESTED_KEY_ID and item.get("format") == KEY_SPKI_V1:
            try:
                key = serialization.load_der_public_key(bytes.fromhex(item.get("data", "")))
            except ValueError as e:
                raise KeyBindingError(f"malformed attested key: {e}") from e
            if not isinstance(key, Ed25519PublicKey):
                raise KeyBindingError("the attested key is not an ed25519 key")
            return key.public_bytes_raw()
    raise KeyBindingError(f"the report lists no attested key {ATTESTED_KEY_ID!r}")


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost", timeout=30)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.socket_path))


def serving_pipeline(settings: Settings, base_dirhash: str, adapter_dirhash: str | None) -> dict:
    """What this enclave serves, in the shape of the receipt's `evalPipeline`."""
    base_aliases = []
    if settings.base_ref:
        base_aliases.append({"scheme": HF_REVISION, "ref": settings.base_ref})
    if settings.base_dir.name.startswith(MPK_MOUNT_PREFIX):  # the config pins this root hash
        base_aliases.append({"scheme": MODELWRAP, "ref": settings.base_dir.name.removeprefix(MPK_MOUNT_PREFIX)})
    models = [{"id": "base", "role": "base", "name": settings.base_name, "scheme": DIRHASH,
               "digest": base_dirhash, "alsoKnownAs": base_aliases}]
    applies_to = ["base"]
    if adapter_dirhash:
        models.append({"id": "adapter", "role": "adapter", "appliesTo": ["base"], "name": settings.adapter_name,
                       "scheme": DIRHASH, "digest": adapter_dirhash})
        applies_to.append("adapter")
    config = [{"id": "sampling", "kind": "sampling", "appliesTo": applies_to, "scheme": JCS,
               "digest": jcs_sha256(settings.sampling), "params": settings.sampling, "enforced": True}]
    return {"models": models, "config": config}


def build_statement(pipeline: dict, execution: dict, approval: dict | None = None) -> dict:
    """The statement for one boot and its adapter: its subject is the pipeline's digest."""
    names = " + ".join(model["name"] for model in pipeline["models"])
    predicate = {"servingPipeline": pipeline, "execution": execution}
    if approval:
        predicate["adapterApproval"] = approval
    return {"_type": STATEMENT_TYPE, "subject": [{"name": names, "digest": {"sha256": jcs_sha256(pipeline)}}],
            "predicateType": PREDICATE_TYPE, "predicate": predicate}


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(), len(payload), payload)


def sign_envelope(statement: dict, key: Ed25519PrivateKey) -> dict:
    payload = canonical_json(statement)
    signature = key.sign(pae(PAYLOAD_TYPE, payload))
    return {"payloadType": PAYLOAD_TYPE, "payload": base64.b64encode(payload).decode(),
            "signatures": [{"sig": base64.b64encode(signature).decode()}]}


def open_envelope(envelope: dict, public_key: bytes) -> dict:
    """The statement in `envelope`, once its one signature verifies under `public_key`."""
    if envelope.get("payloadType") != PAYLOAD_TYPE or len(envelope.get("signatures") or []) != 1:
        raise ValueError("not a single-signature in-toto DSSE envelope")
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signatures"][0]["sig"], validate=True)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, pae(PAYLOAD_TYPE, payload))
    except InvalidSignature as e:
        raise ValueError("the envelope's signature does not verify") from e
    return json.loads(payload)
