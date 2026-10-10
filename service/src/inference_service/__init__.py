"""The verified inference demo's enclave service.

It runs inside the inference enclave, in front of vLLM, and mirrors what PySyft's eval enclave does
for a receipt: it hashes the base Tinfoil mounts and the adapter the model owner uploads, enforces
the eval's sampling, and signs an inference statement with the enclave's attested key. The repo's
README.md describes the design.

This package is everything the enclave runs besides vLLM. What runs elsewhere, the owner's upload
and the comparison with a receipt, is in tools/.
"""
