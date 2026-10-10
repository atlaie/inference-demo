"""What runs outside the enclave, next to its service: the model owner's adapter upload (owner.py)
and the comparison of an eval receipt with the enclave's statement (compare.py).

They reuse the service's definitions (inference_service), so both sides hash, sign and verify the
same way, but none of this is in the enclave's image.
"""
