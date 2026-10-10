"""Compare an eval receipt with an inference statement, component by component.

This is what the demo's side panel shows (app/src/lib/compare.ts follows it), for checking a
statement without the UI.

    python -m inference_tools.compare receipt.json statement.json

`receipt.json` is a receipt's in-toto Statement, or its DSSE envelope (whose signature the registry
checks, not this). `statement.json` is the enclave's /v1/statement response; its signature is
checked against the key in it, which the browser gets over the channel it has verified.
"""

import argparse
import base64
import json
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from inference_service.statement import PAYLOAD_TYPE, pae

WEIGHT_ROLES = ("base", "adapter")


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


def identifiers(component: dict) -> set[tuple[str, str]]:
    """Every (scheme, value) a component is known by: its digest and its aliases."""
    ids = {(component["scheme"], component["digest"])}
    for alias in component.get("alsoKnownAs") or []:
        ids.add((alias["scheme"], alias.get("digest") or alias.get("ref")))
    return ids


def compare(receipt: dict, statement: dict) -> list[dict]:
    """One row per component: `match`, `differs`, `not served`, `not evaluated` or `eval only`."""
    evaluated = receipt["predicate"]["evalPipeline"]
    served = statement["predicate"]["servingPipeline"]
    served_models = {m["role"]: m for m in served["models"]}
    rows = []
    for model in evaluated["models"]:
        row = {"id": model["id"], "role": model["role"], "name": model.get("name")}
        if model["role"] not in WEIGHT_ROLES:  # e.g. the safety classifier that graded the eval
            rows.append(row | {"verdict": "eval only"})
        elif (counterpart := served_models.get(model["role"])) is None:
            rows.append(row | {"verdict": "not served"})
        else:
            shared = identifiers(model) & identifiers(counterpart)
            rows.append(row | {"verdict": "match" if shared else "differs", "on": sorted(s for s, _ in shared)})
    evaluated_roles = {m["role"] for m in evaluated["models"]}
    rows += [{"id": m["id"], "role": role, "name": m.get("name"), "verdict": "not evaluated"}
             for role, m in served_models.items() if role not in evaluated_roles]

    served_config = {c["id"]: c for c in served["config"]}
    for config in evaluated.get("config", []):
        counterpart = served_config.get(config["id"])
        row = {"id": config["id"], "role": config.get("kind"), "params": config.get("params")}
        if counterpart is None:
            rows.append(row | {"verdict": "not served"})
        else:
            same = (counterpart["scheme"], counterpart["digest"]) == (config["scheme"], config["digest"])
            rows.append(row | {"verdict": "match" if same else "differs", "on": [config["scheme"]] if same else [],
                               "enforced": counterpart.get("enforced", False)})
    return rows


def load_receipt(path: str) -> dict:
    document = json.loads(open(path).read())
    if "payload" in document:  # a DSSE envelope
        return json.loads(base64.b64decode(document["payload"]))
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("receipt")
    parser.add_argument("statement")
    args = parser.parse_args()
    response = json.loads(open(args.statement).read())
    statement = open_envelope(response["envelope"], bytes.fromhex(response["publicKey"]))
    rows = compare(load_receipt(args.receipt), statement)
    for row in rows:
        detail = ", ".join(row.get("on", [])) or ""
        print(f"{row['verdict']:<14} {row['role'] or '':<18} {row.get('name') or row['id']:<45} {detail}")
    sys.exit(0 if all(r["verdict"] in ("match", "eval only") for r in rows) else 1)


if __name__ == "__main__":
    main()
