# Verified inference demo

A chat UI on a Tinfoil enclave that serves the model an eval ran on. This is pillar 3 of Four
Pillars: "you are talking to the audited model". A side panel, always open, shows which of the eval's
components this inference used and links to the eval's record in the registry. A demo only: it reads
the registry and never changes it.

## The claim

The inference ran with the same model and configuration as the eval:

- the same **public base** weights,
- the same **private adapter**: the model owner's weights, which nobody outside the two enclaves sees
  (the demo's adapter is public, but it is handled as if it were private),
- the same **sampling**,

and the panel names the eval this corresponds to. Later, the private part may be the whole model
instead of an adapter; nothing in the design depends on there being an adapter.

## How it is proven

Both sides are Tinfoil enclaves, and each signs what it ran with its attested key:

| | Eval (PySyft, OpenMined) | Inference (this demo) |
|---|---|---|
| Measured code | `OpenMined/syft-enclave-tinfoil` | this service, pinned in our config repo |
| Hashes what it loaded | base, adapter, sampling: `evalPipeline` | base, adapter, sampling: `servingPipeline` |
| Signs it with | its attested key, in the receipt | its attested key, in the inference statement |
| Signature is tied to the enclave by | a v3 attestation report listing the key | the same |

The statement uses the receipt's shape and digest schemes (`dirhash-sha256/1`, `jcs-sha256/1`, and
the aliases `modelwrap/2` and `hf-revision/1`), so the two compare component by component. Neither
side needs the other's cooperation, and neither publishes the private weights: only their hashes.

A Tinfoil attested key is made by Tinfoil inside the enclave at boot, from an `attested-keys` entry
in the measured config, and every v3 attestation report lists its public half. So a valid signature
means: this statement comes from an enclave running exactly the measured config, and therefore this
service's code.

### What happens

1. **Boot.** Tinfoil mounts the base weights read-only with dm-verity (`/tinfoil/mpk/mpk-<root hash>`,
   pinned in the config), so the enclave can only read the bytes the root hash names. The service
   hashes them and starts vLLM, which listens on localhost only.
2. **The model owner uploads the adapter.** The owner verifies the enclave with Tinfoil's SDK and sends
   the adapter's files to `POST /v1/adapter`, encrypted to the enclave, with an Ed25519 signature over
   the adapter's dirhash. The config pins the owner's public key (`MODEL_OWNER_PUBKEY`), so only an
   adapter the owner approved is accepted, and only once per boot. The files stay in enclave memory.
   This is how PySyft's data owners get their data into the eval enclave too.
3. **The service loads and states it.** It hashes the files, checks the approval, loads exactly those
   files into vLLM, and signs the inference statement.
4. **The browser checks.** It verifies the enclave with `tinfoil-js` (AMD SEV-SNP report plus the
   Sigstore-signed release of the config repo), fetches the statement with `POST /v1/statement` over
   that verified channel, gets the receipt from the registry, and compares them.
5. **Chat.** Requests go through the service, which enforces the eval's sampling: a request may leave
   the sampling fields out or repeat the eval's values, and anything else that changes what is
   generated is refused.

`POST /v1/statement` is a POST because Tinfoil's request encryption (EHBP) only authenticates the
response to a request with a body. The statement also carries the v3 report that lists the signing
key (`keyBinding`), as receipts do, so the registry or anyone else can check it without the browser.

### What the service guarantees, and where

| Guarantee | How | Code |
|---|---|---|
| The stated base is the served base | dm-verity mount pinned by the config; hashed before vLLM starts | `app.create_app` |
| Only the owner's adapter is served | approval checked against the pinned key; one upload per boot | `adapter.py`, `app.upload_adapter` |
| The hashed adapter is the loaded adapter | vLLM loads the files the service hashed; its adapter endpoints are not exposed | `vllm.py` |
| The eval's sampling is used | every chat request goes through `enforce` | `sampling.py` |
| The statement comes from this enclave | signed with the attested key, which the v3 report lists | `statement.py` |

### Getting the adapter into the enclave

Three ways work with Tinfoil. The statement, the comparison and the panel are the same for all three,
so the demo can switch later.

| | Upload (this demo) | Encrypted pack + Tinfoil's secret store | Encrypted pack + own key server |
|---|---|---|---|
| Infrastructure | none | none: the key is a dashboard secret | a public VM, a domain, a CA-issued certificate |
| Who could see the adapter | only the enclave | Tinfoil: it holds the key and the pack | only the enclave |
| Adapter pinned in the measured config | no, only in the statement | yes | yes |
| After an enclave restart | the owner uploads again | automatic | automatic, while the key server is up |

The encrypted pack is modelwrap's: the owner packs the adapter with `--encrypt`, the config pins it
(`emwp`), and Tinfoil decrypts it at boot with a key from its secret store or from the owner's
[`keyserver`](https://github.com/tinfoilsh/keyserver), and mounts it read-only like the base. Tinfoil's
[`confidential-private-lora-demo`](https://github.com/tinfoilsh/confidential-private-lora-demo) serves a
private adapter that way, with a key server. An encrypted pack has the same root hash as a plain one
of the same files, identity and schema (checked with the demo adapter), since dm-verity covers the
plaintext. Upload needs no infrastructure and keeps the adapter from Tinfoil, as the eval does.

### Matching

`sash_inference.compare` is the reference for what the panel shows, one row per component:

| Verdict | Meaning |
|---|---|
| `match` | the two share an identifier (a digest or an alias) under the same scheme |
| `differs` | they share none |
| `not served` | the eval ran it, this inference doesn't (e.g. a base-only deployment) |
| `not evaluated` | this inference serves it, the eval didn't run it |
| `eval only` | used only to grade the eval, such as the safety classifier |

The runtimes differ by design (PySyft runs transformers, the enclave runs vLLM), so the claim is
about the weights and the sampling, not identical completions.

## Layout

| Path | Contents |
|---|---|
| `service/` | The enclave service (`sash_inference`) and the owner's tool (`sash_inference.owner`), with tests and a `Dockerfile` |
| `container/compose.yaml` | A local twin of the enclave |
| `scripts/crosswalk.py` | The base pack: packs a public revision with modelwrap and prints its identities |
| `fixtures/crosswalk.json` | The TinyLlama base's identities, from `crosswalk.py` |
| `fixtures/receipt-v3.json` | OpenMined's example receipt/v3: `notebooks/enclave/double-blind-eval-w-receipts/receipt.json` on PySyft's `dev` at `37e8834f` |

The enclave's `tinfoil-config.yml` lives in its own repo: Tinfoil's SDKs verify against that repo's
latest GitHub release, so it can't share releases with the registry. It pins the service image, the
base pack, the owner's public key, the attested key and the service's other settings.

## Run it locally

Needs Docker and uv. Outside an enclave there is no attested key: the twin signs with a key it makes
at startup (`ALLOW_DEV_KEY=1`), so its statements have `"keyBinding": null`.

```bash
cd demo/inference

# 1. The base pack (about 2.2 GB): pack TinyLlama with modelwrap and extract it
curl -LO https://github.com/tinfoilsh/modelwrap/releases/download/v0.3.0/modelwrap
echo "ecdaa47f6571621268ae3e9b66040259290084bb65fb6a14ef3f3978afcfd66e  modelwrap" | sha256sum -c && chmod +x modelwrap
uv run scripts/crosswalk.py --modelwrap ./modelwrap \
  TinyLlama/TinyLlama-1.1B-Chat-v1.0@fe8a4ea1ffedaf415f4da2f062534de366a451e6

# 2. The model owner's key, and the enclave twin (ready in about a minute on 4 CPUs)
OWNER=~/.cache/sash-inference-demo/owner.pem
uv run --project service python -m sash_inference.owner keygen $OWNER > $OWNER.pub
MODEL_OWNER_PUBKEY=$(cat $OWNER.pub) docker compose -f container/compose.yaml up --build -d

# 3. The owner uploads the adapter: the two files PySyft's model owner uploads to the eval
ADAPTER=~/.cache/sash-inference-demo/dbe_adapter && mkdir -p $ADAPTER
for f in adapter_config.json adapter_model.safetensors; do curl -sfL -o $ADAPTER/$f \
  https://huggingface.co/zjudai/flowertune-general-nlp-lora-tinyllama-1.1b-chat-v1.0/resolve/fe3854b53ddf9870047f1eda04ea927c42f1644b/$f; done
uv run --project service python -m sash_inference.owner upload --key $OWNER --url http://127.0.0.1:8080 $ADAPTER

# 4. Chat, then compare the statement with the receipt
curl -s localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "dbe_adapter", "messages": [{"role": "user", "content": "What is a hardware enclave?"}]}'
curl -s -X POST localhost:8080/v1/statement -H 'Content-Type: application/json' -d '{}' > /tmp/statement.json
uv run --project service python -m sash_inference.compare fixtures/receipt-v3.json /tmp/statement.json
```

Service tests: `cd service && uv run pytest`.

## The base pack

`crosswalk.py` packs a public revision with modelwrap, extracts the pack and hashes its files as
PySyft does. For TinyLlama it reproduces the receipt's `modelwrap/2` alias (`bb6889fc…`) and its
`dirhash-sha256/1` (`d1e29a1a…`): the pack the config pins holds exactly the bytes the eval ran.
Packing must pin `--schema 2`, as PySyft does; modelwrap's default schema 1 gives another root hash.

The packer container writes its downloads and packs (about 3× the model size) under
`~/.cache/sash-inference-demo` as root; `./modelwrap --delete <repo>@<revision> --output
~/.cache/sash-inference-demo/output --cache ~/.cache/sash-inference-demo/cache` removes them.

## Not yet

- The config repo and the Tinfoil deployment, including uploading the adapter through Tinfoil's SDK.
- The chat app with the side panel.
