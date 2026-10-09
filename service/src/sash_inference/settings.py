"""Settings, from the environment.

In the enclave every one of these is pinned in tinfoil-config.yml, so it is measured: a verifier
reads the values from the release's config, not from this service.
"""

import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from sash_inference.sampling import check_sampling

# Where Tinfoil mounts the attested key the config grants this container (see `attested-keys` in
# https://docs.tinfoil.sh/containers/attested-keys).
ATTESTED_KEY_ID = "enclave-signing-key"
ATTESTED_KEY_PATH = Path("/run/tinfoil/keys") / ATTESTED_KEY_ID / "private_key.pem"
HEX64 = re.compile(r"[0-9a-f]{64}")


class SettingsError(ValueError):
    """A setting is missing or malformed: the service refuses to start."""


@dataclass(frozen=True)
class Settings:
    base_dir: Path  # the base weights, mounted read-only: /tinfoil/mpk/mpk-<root hash> in the enclave
    base_name: str  # the name the receipt gives the base, e.g. TinyLlama/TinyLlama-1.1B-Chat-v1.0
    base_ref: str | None  # its Hugging Face repo@revision, if it has one
    base_schema: int  # the modelwrap pack schema the base was packed with: its root hash is modelwrap/<schema>
    adapter_name: str | None  # None: no adapter, the base is the served model
    owner_public_key: str | None  # Ed25519, 64 hex: the only key whose approval loads an adapter
    sampling: dict  # the eval's sampling params, as the receipt records them
    signing_key_path: Path
    allow_dev_key: bool  # outside an enclave: sign with a key made at startup, bound to no report
    adapter_dir: Path  # where the uploaded adapter is written: a tmpfs, so only enclave memory
    max_adapter_bytes: int
    vllm_args: list[str]  # extra `vllm serve` arguments
    port: int

    @property
    def served_model(self) -> str:
        """The model name clients ask for: the adapter's when there is one, else "base"."""
        return self.adapter_name or "base"


def load_settings(env=os.environ) -> Settings:
    def required(name: str) -> str:
        value = env.get(name, "")
        if not value:
            raise SettingsError(f"{name} is required")
        return value

    adapter_name = env.get("ADAPTER_NAME") or None
    owner_public_key = env.get("MODEL_OWNER_PUBKEY") or None
    if adapter_name and not (owner_public_key and HEX64.fullmatch(owner_public_key)):
        raise SettingsError("an adapter needs MODEL_OWNER_PUBKEY: the owner's Ed25519 key, 64 lowercase hex")
    try:
        sampling = json.loads(required("SAMPLING"))
    except json.JSONDecodeError as e:
        raise SettingsError(f"SAMPLING is not JSON: {e}") from e
    check_sampling(sampling)
    return Settings(
        base_dir=Path(required("BASE_MODEL_DIR")),
        base_name=required("BASE_MODEL_NAME"),
        base_ref=env.get("BASE_MODEL_REF") or None,
        base_schema=int(env.get("BASE_MODEL_SCHEMA") or 2),
        adapter_name=adapter_name,
        owner_public_key=owner_public_key if adapter_name else None,
        sampling=sampling,
        signing_key_path=Path(env.get("SIGNING_KEY_PATH") or ATTESTED_KEY_PATH),
        allow_dev_key=env.get("ALLOW_DEV_KEY") == "1",
        adapter_dir=Path(env.get("ADAPTER_DIR") or "/tmp/adapter"),
        max_adapter_bytes=int(env.get("MAX_ADAPTER_BYTES") or 1 << 30),
        vllm_args=shlex.split(env.get("VLLM_ARGS", "")),
        port=int(env.get("PORT") or 8080),
    )
