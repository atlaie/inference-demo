"""Enforcing the eval's sampling on every chat request.

The receipt records sampling with the names PySyft's job passes to Hugging Face `generate`. A
request may leave those fields out or repeat the eval's values; anything else that could change
what the model generates is refused, so a completion from this service was sampled exactly as the
eval's completions were.
"""

# Receipt sampling param -> its chat completions request field.
REQUEST_FIELDS = {"max_new_tokens": "max_tokens", "temperature": "temperature", "top_k": "top_k",
                  "top_p": "top_p"}
# Request fields that don't change what is generated.
NEUTRAL_FIELDS = {"model", "messages", "stream", "stream_options", "seed", "user"}
# Request fields some clients add that are dropped before forwarding: tinfoil-js adds a prompt
# cache secret meant for Tinfoil's router.
DROPPED_FIELDS = {"user_cache_secret"}


class SamplingError(ValueError):
    """The request asks for sampling the eval didn't use (HTTP 400)."""


def check_sampling(sampling: dict) -> None:
    """Refuse sampling params this service can't enforce, so it never claims to enforce them."""
    unknown = set(sampling) - set(REQUEST_FIELDS)
    if unknown:
        raise ValueError(f"SAMPLING has params this service can't enforce: {sorted(unknown)}")


def enforce(body: dict, sampling: dict) -> dict:
    """The request to forward: `body` with the eval's sampling set, or SamplingError."""
    forwarded = {k: v for k, v in body.items() if k not in DROPPED_FIELDS}
    if "max_completion_tokens" in forwarded:  # the newer name for max_tokens
        if "max_tokens" in forwarded:
            raise SamplingError("set max_tokens or max_completion_tokens, not both")
        forwarded["max_tokens"] = forwarded.pop("max_completion_tokens")

    enforced = {REQUEST_FIELDS[param]: value for param, value in sampling.items()}
    for field in set(forwarded) - NEUTRAL_FIELDS:
        if field not in enforced:
            raise SamplingError(f"{field!r} is not part of the evaluated configuration")
        if forwarded[field] != enforced[field]:
            raise SamplingError(f"{field} must be {enforced[field]!r}, the value the eval used")
    return forwarded | enforced
