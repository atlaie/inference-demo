# Demo runbook

How to show the verified inference demo: what to prepare, what to do on stage, and what to say.
README.md explains the design; this is the script. Each act also works against the local twin, for
rehearsing, with the differences noted.

## The cast

| Role | In the demo |
|---|---|
| The eval | OpenMined's example receipt (`fixtures/receipt-v3.json`): TinyLlama-1.1B-Chat with the adapter `dbe_adapter`, run on 5 prompts in PySyft's enclave |
| The model owner | We are, holding `owner.pem`, whose public key the enclave's config pins (`MODEL_OWNER_PUBKEY`) |
| The private adapter | What PySyft's model owner uploaded to the eval: the public LoRA [`zjudai/flowertune-general-nlp-lora-tinyllama-1.1b-chat-v1.0`](https://huggingface.co/zjudai/flowertune-general-nlp-lora-tinyllama-1.1b-chat-v1.0) at `fe3854b5`, treated as if it were private. Its dirhash is the receipt's `c2dd2913…` |
| An altered adapter | The same weights with `lora_alpha` 16 instead of 64: a weakened fine-tune, signed by the owner. What a provider serving something other than what was evaluated looks like. Its dirhash is `298ec868…` |
| An outsider | Anyone with a key the config doesn't pin |

## Before the demo

1. **The enclave**, deployed by the runbook in
   [`inference-demo-config`](https://github.com/sg-ai-safety-hub/inference-demo-config), with `owner.pem`
   at hand. For rehearsing: the local twin (README, "Run it locally").
2. **The adapters**, from the registry repo's `demo/inference`:

   ```bash
   ADAPTER=~/.cache/sash-inference-demo/dbe_adapter && mkdir -p $ADAPTER
   for f in adapter_config.json adapter_model.safetensors; do curl -sfL -o $ADAPTER/$f \
     https://huggingface.co/zjudai/flowertune-general-nlp-lora-tinyllama-1.1b-chat-v1.0/resolve/fe3854b53ddf9870047f1eda04ea927c42f1644b/$f; done
   ALTERED=~/.cache/sash-inference-demo/dbe_adapter_altered && mkdir -p $ALTERED
   cp $ADAPTER/adapter_model.safetensors $ALTERED/
   sed 's/"lora_alpha": 64/"lora_alpha": 16/' $ADAPTER/adapter_config.json > $ALTERED/adapter_config.json
   uv run --project service python -m sash_inference.owner keygen ~/.cache/sash-inference-demo/outsider.pem
   ```

3. **Shortcuts** for the terminal, from `demo/inference`. Against the twin, replace
   `--enclave $HOST --repo $REPO` with `--url http://127.0.0.1:8080`, and `https://$HOST` with
   `http://127.0.0.1:8080`.

   ```bash
   HOST=<name>.<org>.containers.tinfoil.dev REPO=sg-ai-safety-hub/inference-demo-config
   upload() { uv run --project service python -m sash_inference.owner upload --key "$1" --enclave $HOST --repo $REPO "$2"; }
   ```

4. **The UI**, on the presenting laptop:
   `MOCK=0 VITE_ENCLAVE_URL=https://$HOST VITE_CONFIG_REPO=$REPO docker compose -f app/compose.yaml up`,
   then http://localhost:5174. Against the twin: `MOCK=0 docker compose -f app/compose.yaml up`.
5. **A fresh enclave**: restart the deployment from Tinfoil's dashboard, so no adapter is loaded
   (twin: `docker compose -f container/compose.yaml restart`).

To rehearse the UI without any enclave, the mock serves each state: `MOCK=waiting`, `MOCK=1` (all
match) and `MOCK=altered-adapter`.

## The demo

### 1. The enclave is real, but serves nothing yet

Open the UI. The pill says **Waiting for the model**; the panel already shows **Hardware attested**,
and that the enclave serves nothing until the model owner uploads their adapter. (If it says the
enclave is loading the model, it has just restarted: give it a minute.)

> Your browser has just checked this server: AMD's hardware says it is a sealed enclave, and it runs
> exactly the code and settings published on GitHub, signed in a public log. But it serves nothing:
> the model owner hasn't handed over their private fine-tune yet.

Expand **Hardware attested**: the config repo and the release it runs.

### 2. Only the model owner can load the model

```bash
upload ~/.cache/sash-inference-demo/outsider.pem ~/.cache/sash-inference-demo/dbe_adapter
```

The enclave refuses: *the model owner's approval does not verify for this adapter*.

> The enclave's published config names exactly one key that may load a model. Anyone can reach the
> enclave; nobody else can choose what it serves.

```bash
upload ~/.cache/sash-inference-demo/owner.pem ~/.cache/sash-inference-demo/dbe_adapter
```

The owner's upload is accepted. Within a few seconds every check in the panel turns green.

> The adapter went to the enclave encrypted: only the enclave saw it. The enclave fingerprinted what
> it loaded and signed the result, and your browser compares that with the eval's receipt.

### 3. It's the evaluated model

Walk through the panel:

- **Base model matches** and **Private adapter matches**: expand them. The fingerprints from the eval
  and from this enclave are the same. The adapter stays secret; only fingerprints are compared.
- **Settings match**: temperature, top-k and token limit as in the eval, and the enclave enforces them.
- **Eval registered**, and *What the eval found*: the results this model got.

Ask something. The answer stops at 48 tokens, the eval's limit.

Show that the settings are enforced, not just suggested:

```bash
curl -s https://$HOST/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "dbe_adapter", "temperature": 0, "messages": [{"role": "user", "content": "Hi"}]}'
```

*temperature must be 0.8, the value the eval used.*

### 4. A different model is caught

Restart the deployment (twin: `docker compose -f container/compose.yaml restart`) and, once it is
up, upload the altered adapter, as the owner:

```bash
upload ~/.cache/sash-inference-demo/owner.pem ~/.cache/sash-inference-demo/dbe_adapter_altered
```

The browser doesn't ask the enclave again until it has a reason to, so the panel still shows the
last check. Send a message. Before showing the answer, the browser notices it came from a restarted
enclave (a new boot has new keys), checks it again, and the answer carries a note that the enclave
restarted. The pill turns to **Differs from the eval**, and **Private adapter differs** turns red.
Expand it: the eval's fingerprint and this enclave's no longer agree. (Against the twin, which has no
keys, the panel checks every few seconds and turns red without a message.)

> Same base, same settings, a model that chats just as well, and signed by the owner. But it isn't
> the fine-tune that was evaluated, so the eval's results don't speak for it, and the user sees that.

### 5. Back to the evaluated model

Restart again and upload `dbe_adapter` as in act 2, so the enclave is left serving the evaluated
model.

## If something goes wrong

| Symptom | Cause |
|---|---|
| The upload answers *vLLM is starting* | The enclave has just restarted: upload again in a minute |
| The panel still shows the previous check after a restart | Send a message: the browser checks the enclave again when an answer comes from a new boot |
| The upload answers *an adapter is already loaded* | The enclave keeps its adapter until it restarts |
| **Hardware not attested**, amber | The UI talks to the twin or the mock, not to an enclave (`VITE_ENCLAVE_URL` unset) |
| **Not verified**, red | The enclave doesn't run the config repo's latest release: check `VITE_CONFIG_REPO` and the deployment's tag |
