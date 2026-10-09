#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""One model revision's identity under each digest scheme the demo matches on.

Packs `repo@revision` with modelwrap (the launcher runs its pinned packer image in Docker), extracts
the pack's files, and hashes them the way PySyft's eval job does. Prints one JSON entry:

    hf-revision/1     repo@revision
    modelwrap/2       the pack's dm-verity root hash, which tinfoil-config.yml pins (`mpk`)
    dirhash-sha256/1  sha256 of the canonical JSON of {relative path: file sha256}

The dirhash is computed over the files inside the pack, so it names exactly the bytes that a
container mounting this pack serves. Open weights only: anyone can rerun this and get the same entry.

    uv run scripts/crosswalk.py --modelwrap ./modelwrap TinyLlama/TinyLlama-1.1B-Chat-v1.0@fe8a4ea…
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_WORK = Path.home() / ".cache" / "sash-inference-demo"
# The schema PySyft's eval job packs with (`modelwrap --local --schema 2`). modelwrap's default is 1.
SCHEMA = "2"
MPK_REFERENCE = r"[0-9a-f]{64}_[0-9]+_[0-9a-f-]{36}"  # ROOTHASH_OFFSET_UUID, as tinfoil-config.yml's `mpk`
# fsck.erofs extracts the pack without a mount, so without root on the host.
EXTRACT_IMAGE = "debian:trixie-slim"


def pack(modelwrap: Path, model: str, work: Path) -> tuple[Path, str]:
    """Run modelwrap; return the .mpk and its `ROOTHASH_OFFSET_UUID` reference.

    The reference is modelwrap's last line of output: the packer container writes the .info file
    as root, mode 0600, so the host user can't read it.
    """
    run = subprocess.run([modelwrap, "--schema", SCHEMA, "--output", work / "output", "--cache", work / "cache",
                          model], check=True, stdout=subprocess.PIPE, text=True)
    reference = run.stdout.strip().splitlines()[-1]
    if not re.fullmatch(MPK_REFERENCE, reference):
        sys.exit(f"modelwrap printed no pack reference, got: {reference!r}")
    repo, revision = model.split("@")
    return work / "output" / repo / f"{revision}.mpk", reference


def extract(mpk: Path, dest: Path) -> None:
    """Extract the pack's EROFS filesystem into `dest`, owned by the current user."""
    dest.mkdir(parents=True, exist_ok=True)
    script = ("apt-get update -qq && apt-get install -qq -y erofs-utils >/dev/null"
              f" && fsck.erofs --extract=/out /in/{mpk.name} && chown -R {os.getuid()}:{os.getgid()} /out")
    subprocess.run(["docker", "run", "--rm", "-e", "DEBIAN_FRONTEND=noninteractive", "-v", f"{mpk.parent}:/in:ro",
                    "-v", f"{dest}:/out", EXTRACT_IMAGE, "sh", "-c", script], check=True)


def dirhash_sha256(root: Path) -> str:
    """dirhash-sha256/1, as PySyft's job computes it: sha256 of the canonical JSON of
    {relative path: file sha256}, over every file under `root`."""
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        with open(path, "rb") as f:
            files[str(path.relative_to(root))] = hashlib.file_digest(f, "sha256").hexdigest()
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("model", help="Hugging Face repo@revision")
    parser.add_argument("--modelwrap", type=Path, required=True, help="the modelwrap launcher binary")
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK, help=f"download and pack directory ({DEFAULT_WORK})")
    args = parser.parse_args()
    if "@" not in args.model:
        sys.exit("pin the revision: repo@revision")

    mpk, reference = pack(args.modelwrap.resolve(), args.model, args.work)
    files = args.work / "extracted" / args.model.replace("/", "__")
    if not files.exists():
        extract(mpk, files)
    print(json.dumps({
        "hf-revision/1": args.model,
        "modelwrap/2": reference.split("_")[0],
        "mpk": reference,
        "dirhash-sha256/1": dirhash_sha256(files),
    }, indent=2))


if __name__ == "__main__":
    main()
