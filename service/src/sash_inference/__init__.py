"""The verified inference demo's enclave service.

It runs inside the inference enclave, in front of vLLM, and mirrors what PySyft's eval enclave does
for a receipt: it hashes the base and the model owner's adapter that Tinfoil mounts, enforces the
eval's sampling, and signs an inference statement with the enclave's attested key. README.md in
demo/inference describes the design.
"""
