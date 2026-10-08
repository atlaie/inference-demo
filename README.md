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
   the adapter's files to `POST /v1/adapter` with EHBP: the body is encrypted with HPKE to the
   enclave's public key, which Tinfoil's shim makes inside the enclave at boot and the attestation
   report binds, so only this enclave can decrypt it. With the files goes an Ed25519 signature over
   the adapter's dirhash. The owner's tool, `sash_inference.owner upload --enclave <host> --repo
   <config repo>`, verifies the enclave with Tinfoil's Python SDK and uploads over HTTPS pinned to the
   attested TLS key; to the local twin (`--url`) it uploads in plain HTTP. The config pins the owner's public key (`MODEL_OWNER_PUBKEY`), so only an
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

### What ties an answer to the model

The same thing that ties it in Tinfoil's own chat: the channel. The browser verifies the enclave's
attestation once, and every request then goes over EHBP to the HPKE key that attestation binds, so
only that enclave can read a request and only it can produce a response the browser accepts. The
statement and the chat answers come over that one channel: an answer the browser accepts comes from
the enclave whose statement it checked, and that enclave's measured code serves only the stated
weights with the stated sampling.

The enclave's keys are made at each boot, and the adapter can only change with a restart, so the key
also says which statement applies. After a restart the old key stops working; `tinfoil-js` verifies
the enclave again and retries the request, and its verification document then carries the new key.
The UI compares the key each answer came over with the key the statement came over, before showing
the answer; when they differ, it fetches the new boot's statement first and notes the restart on the
answer. So every answer is shown with the statement of the boot that wrote it, with no polling. The
UI only fetches the statement every few seconds while the enclave isn't serving yet, and against the
twin, which has no keys.

This binds answers for the user in the browser, not for a third party later: answers aren't signed
one by one. The local twin has none of it: plain HTTP, no attestation.

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

- **Upload** (this demo): the owner sends the adapter to the running enclave, as above.
- **Encrypted pack + own key server**: the owner packs the adapter with modelwrap's `--encrypt`, the
  config pins the pack (`emwp`), and at boot the owner's
  [`keyserver`](https://github.com/tinfoilsh/keyserver) releases its key only to an enclave whose
  attestation matches the release it pins (repo, tag and domain). Tinfoil decrypts the pack and mounts
  it read-only with dm-verity, like the base. Tinfoil's
  [`confidential-private-lora-demo`](https://github.com/tinfoilsh/confidential-private-lora-demo) does
  this.
- **Encrypted pack + Tinfoil's secret store**: the same, with the key in Tinfoil's dashboard instead
  of a key server.

An encrypted pack has the same root hash as a plain one of the same files, identity and schema, since
dm-verity covers the plaintext (checked with the demo adapter).

| | Upload (this demo) | Encrypted pack + own key server | Encrypted pack + Tinfoil's secret store |
|---|---|---|---|
| Infrastructure | none | a public VM, a domain, a CA-issued certificate | none: the key is a dashboard secret |
| Who could see the adapter | only the enclave | only the enclave | Tinfoil: it holds the key and the pack |
| Adapter pinned in the measured config | no, only named in the statement | yes | yes |
| Which adapter a release serves, on record | no: a release pins the owner's key, not the adapter | yes, in the Sigstore-logged release | yes, in the Sigstore-logged release |
| Who checks the adapter's bytes while it runs | the service: it hashes, then loads | the kernel: dm-verity on every read | the kernel: dm-verity on every read |
| After an enclave restart | the owner uploads again | automatic, while the key server is up | automatic |

#### Upload versus the key server

Both keep the adapter's plaintext inside the enclave, serve only an adapter the owner approved, and
lead to the same statement and the same match. They differ in where the guarantee comes from:

- **Where the adapter is named.** With the key server, the adapter's root hash is in the measured
  config, so every release says which adapter it serves, on Sigstore's public log, before it boots.
  With upload, a release only pins whose adapter it accepts (`MODEL_OWNER_PUBKEY`); which adapter it
  serves is attested at runtime, by the statement.
- **What enforces the bytes.** With the key server, the kernel checks every read against the root
  hash (dm-verity). With upload, this service hashes the files and loads exactly those; that holds
  because its code is measured, not because the kernel enforces it.
- **What the owner approves.** The key server releases the key to a release it pins: the owner
  approves the code that will serve the adapter, once per release. With upload, the owner verifies
  the enclave in Tinfoil's SDK at upload time and signs the adapter's dirhash: they approve the bytes,
  at each boot.
- **Changing the adapter.** With the key server, a different adapter needs a new release, visible in
  the log. With upload, a restart and a new signed upload are enough; only the new statement shows it.
- **Running it.** The key server must be online at every boot, on a public domain with a CA-issued
  certificate, and must terminate TLS itself. Upload needs the owner at every restart, and nothing
  else.
- **Tinfoil's [model identity post](https://tinfoil.sh/blog/2026-02-03-proving-model-identity).** There,
  the weights' root hash is part of the measurement: the key server variant follows it for the
  adapter, as both variants do for the base. With upload, the adapter's identity rests on the
  statement instead.

Upload needs no infrastructure and keeps the adapter from Tinfoil, as the eval does, which is why the
demo uses it.

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
| `DEMO.md` | The demo runbook: preparing, the script, and what to say |
| `app/` | The chat UI with our verification panel (Vite, React, Tailwind); `vite.mock.ts` is a stand-in enclave for UI work |
| `service/` | The enclave service (`sash_inference`) and the owner's tool (`sash_inference.owner`), with tests and a `Dockerfile` |
| `container/compose.yaml` | A local twin of the enclave |
| `scripts/crosswalk.py` | The base pack: packs a public revision with modelwrap and prints its identities |
| `fixtures/crosswalk.json` | The TinyLlama base's identities, from `crosswalk.py` |
| `fixtures/receipt-v3.json` | OpenMined's example receipt/v3: `notebooks/enclave/double-blind-eval-w-receipts/receipt.json` on PySyft's `dev` at `37e8834f` |
| `fixtures/statement-local.json` | A `/v1/statement` response from the local twin, signed with its dev key: what the mock serves |
| `fixtures/statement-altered-adapter.json` | The same, after uploading the demo adapter with `lora_alpha` 16: the mock's `altered-adapter` state |

The enclave's `tinfoil-config.yml` lives in its own repo: Tinfoil's SDKs verify against that repo's
latest GitHub release, so it can't share releases with the registry. It pins the service image, the
base pack, the owner's public key, the attested key and the service's other settings.

## Run it locally

### The UI alone

For working on the UI: no Docker, no model. The dev server stands in for the enclave, serving
`fixtures/statement-local.json` and a canned answer. Needs Node 22; `npx pnpm@11.27.0` runs pnpm 11
without installing it.

```bash
cd demo/inference/app
npx pnpm@11.27.0 install
MOCK=1 npx pnpm@11.27.0 dev   # http://localhost:5174
```

Without Node, in Docker: `docker compose -f demo/inference/app/compose.yaml up`. With `MOCK=0` it
talks to the twin instead. Other mock states: `MOCK=waiting` (no adapter uploaded yet) and
`MOCK=altered-adapter` (another adapter than the eval's).

### The UI against a Tinfoil enclave

```bash
VITE_ENCLAVE_URL=https://<host> VITE_CONFIG_REPO=<owner/repo> npx pnpm@11.27.0 dev
```

The app then goes through `tinfoil-js` (`app/src/lib/enclave.ts`): before any request it verifies
the enclave's AMD SEV-SNP report and that it runs the measurement Sigstore-signed for the config
repo's latest release, then encrypts every request body to the enclave's attested key (EHBP), the
statement and the chat alike. The panel's hardware check shows that verification. The requests go to
the page's own origin, which the dev server proxies to the enclave, so the enclave needs no CORS.
Checked against Tinfoil's public router: the attestation verifies in the browser, and the encrypted
requests reach it through the proxy.

### Everything

Needs Docker and uv. Outside an enclave there is no attested key: the twin signs with a key it makes
at startup (`ALLOW_DEV_KEY=1`), so its statements have `"keyBinding": null`.

```bash
cd demo/inference

# 1. The base (about 2.2 GB). On Linux: pack TinyLlama with modelwrap and extract the pack
curl -LO https://github.com/tinfoilsh/modelwrap/releases/download/v0.3.0/modelwrap
echo "ecdaa47f6571621268ae3e9b66040259290084bb65fb6a14ef3f3978afcfd66e  modelwrap" | sha256sum -c && chmod +x modelwrap
uv run scripts/crosswalk.py --modelwrap ./modelwrap \
  TinyLlama/TinyLlama-1.1B-Chat-v1.0@fe8a4ea1ffedaf415f4da2f062534de366a451e6
#    Elsewhere (modelwrap's launcher is a Linux binary): the same files, straight from Hugging Face
BASE=~/.cache/sash-inference-demo/extracted/TinyLlama__TinyLlama-1.1B-Chat-v1.0@fe8a4ea1ffedaf415f4da2f062534de366a451e6
uvx --from huggingface_hub hf download TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
  --revision fe8a4ea1ffedaf415f4da2f062534de366a451e6 --local-dir $BASE && rm -rf $BASE/.cache

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

# 5. The UI, at http://127.0.0.1:5174 (it proxies /v1 to the twin on 8080)
cd app && npx pnpm@11.27.0 install && npx pnpm@11.27.0 dev
```

The twin's image (`vllm/vllm-openai-cpu`) has `linux/amd64` and `linux/arm64` builds, so it also
runs on Apple silicon; give Docker at least 8 GB of memory. Locally the UI talks to the twin with plain `fetch` and checks the statement's signature with
WebCrypto; pointed at a Tinfoil enclave, it goes through `tinfoil-js` (above). Until the registry reads
receipt/v3, the UI uses `fixtures/receipt-v3.json`; `VITE_REGISTRY_URL` sets where its registry
links point (`http://localhost:5173` by default).

Service tests: `cd service && uv run pytest`.

## Deploying

The enclave's measured config lives in its own repo, `sg-ai-safety-hub/inference-demo-config`, whose
README is the deployment runbook: the image, the owner's key, the base pack on the host, the
release, the deployment, the adapter upload and the UI. The image is built from `service/` by this
repo's `.github/workflows/inference-demo-image.yml`, which also attests its build provenance, so the
digest the config pins traces back to this source.

## Demoing the UI

The UI is static once built, but it isn't hosted anywhere yet. Ways to show it:

- **Locally, against the deployed enclave** (what the runbook ends with): the dev server in Docker
  proxies to the enclave, and the browser verifies the enclave itself with `tinfoil-js`. Nothing to
  host; the presenter runs it and shares their screen.
- **From the enclave itself**: easy to add (the service serves the built files, same origin, no
  CORS), but the party being checked would serve the page that does the checking, the browser runs
  that page before it has verified anything, and every change to the UI's text would be a new
  measured release. Better kept apart.
- **From a static host later**, such as GitHub Pages, or the registry's own site, which as the
  neutral party is where the checking page belongs: build the app, allow its origin in the config's
  `shim.origins` (CORS), and have the app call the enclave directly instead of through the dev server.

`DEMO.md` is the demo's script, including what the panel catches: an outsider's upload, another
adapter than the eval's, another temperature.

## The base pack

`crosswalk.py` packs a public revision with modelwrap, extracts the pack and hashes its files as
PySyft does. For TinyLlama it reproduces the receipt's `modelwrap/2` alias (`bb6889fc…`) and its
`dirhash-sha256/1` (`d1e29a1a…`): the pack the config pins holds exactly the bytes the eval ran.
Packing must pin `--schema 2`, as PySyft does; modelwrap's default schema 1 gives another root hash.

The packer container writes its downloads and packs (about 3× the model size) under
`~/.cache/sash-inference-demo` as root; `./modelwrap --delete <repo>@<revision> --output
~/.cache/sash-inference-demo/output --cache ~/.cache/sash-inference-demo/cache` removes them.

## Not yet

- The first deployment, following the config repo's runbook.
- Serving the built UI from somewhere other than the dev server (see "Demoing the UI").
- Reading the receipt from the registry instead of the fixture.
