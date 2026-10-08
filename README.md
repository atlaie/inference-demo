# Verified inference demo: enclave config

The measured configuration of the verified inference demo's Tinfoil enclave: TinyLlama plus a
private adapter, behind the service in
[`sg-ai-safety-hub/double-blind-eval-registry`](https://github.com/sg-ai-safety-hub/double-blind-eval-registry)
(`demo/inference/`), whose README describes the design.

This repo holds only configuration. Tinfoil's SDKs verify an enclave against this repo's **latest
GitHub release**: its Sigstore-signed measurement covers `tinfoil-config.yml` byte for byte, including
the image digest, the base model's pack, the model owner's public key and every setting. So the
model owner, before uploading the adapter, and the browser, before chatting, both check that the
enclave runs exactly this file.

| Path | Contents |
|---|---|
| `tinfoil-config.yml` | The enclave: the service image, the base pack, the attested key and the settings |
| `.github/workflows/` | Tinfoil's release workflows, unchanged from [`tinfoil-containers-template`](https://github.com/tinfoilsh/tinfoil-containers-template) |

## Deploying

Needs a Tinfoil Containers account with a host for CPU workloads on AMD SEV-SNP, the GitHub CLI,
and, for the model owner, uv and a checkout of the registry repo.

1. **The image.** In the registry repo, run the image workflow:
   `gh workflow run inference-demo-image.yml -R sg-ai-safety-hub/double-blind-eval-registry -f tag=v0.1.0`.
   Its run summary prints `ghcr.io/sg-ai-safety-hub/inference-demo@sha256:…`: put that into
   `tinfoil-config.yml`. The first time, make the GHCR package public, so Tinfoil's host can pull it.
2. **The model owner's key.** The model owner makes it and keeps the private half:
   `uv run --project demo/inference/service python -m sash_inference.owner keygen owner.pem`
   prints the public key for `MODEL_OWNER_PUBKEY`.
3. **The base pack on the host.**
   `tinfoil model wrap --host <host> TinyLlama/TinyLlama-1.1B-Chat-v1.0 --commit fe8a4ea1ffedaf415f4da2f062534de366a451e6 --wait`
   prints the pack's reference. Root hash `bb6889fc…` means pack schema 2, the receipt's: the config
   is right as it is. Root hash `436f503a…` means schema 1: use the printed reference for `mpk` and in
   `BASE_MODEL_DIR`, and set `BASE_MODEL_SCHEMA` to `"1"`. Either way the base still matches the eval
   by its dirhash and its Hugging Face revision.
4. **The release.** Commit the config, then `gh workflow run tinfoil-release.yml -f version=v0.0.1`.
   It tags the commit, measures the config, and publishes the measurement as a Sigstore-signed GitHub
   release.
5. **The deployment.** In the [dashboard](https://dash.tinfoil.sh): Containers → Deploy, this repo and
   the release tag. The enclave is served at `<name>.<org>.containers.tinfoil.dev`.
6. **The adapter.** The model owner verifies the enclave and uploads, from the registry repo:
   `uv run --project demo/inference/service python -m sash_inference.owner upload --key owner.pem --enclave <host> --repo sg-ai-safety-hub/inference-demo-config <adapter dir>`.
   The enclave serves nothing until then, and needs the upload again after every restart.
7. **The UI**, from the registry repo:
   `MOCK=0 VITE_ENCLAVE_URL=https://<host> VITE_CONFIG_REPO=sg-ai-safety-hub/inference-demo-config docker compose -f demo/inference/app/compose.yaml up`,
   then http://localhost:5174.

To change anything, edit `tinfoil-config.yml`, release a new version, and update the deployment in
the dashboard. Each release is a new entry in Sigstore's public log.
