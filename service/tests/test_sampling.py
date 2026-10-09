import pytest
from conftest import SAMPLING

from sash_inference.sampling import SamplingError, check_sampling, enforce

MESSAGES = [{"role": "user", "content": "hi"}]


def test_fills_in_the_eval_sampling():
    assert enforce({"model": "m", "messages": MESSAGES}, SAMPLING) == {
        "model": "m", "messages": MESSAGES, "max_tokens": 48, "temperature": 0.8, "top_k": 40, "top_p": 1.0}


def test_accepts_the_eval_values_under_either_token_field():
    assert enforce({"messages": MESSAGES, "temperature": 0.8, "max_completion_tokens": 48}, SAMPLING)["max_tokens"] == 48


@pytest.mark.parametrize("field, value", [("temperature", 0.0), ("max_tokens", 100), ("top_k", 1), ("top_p", 0.9)])
def test_refuses_other_values(field, value):
    with pytest.raises(SamplingError, match=field):
        enforce({"messages": MESSAGES, field: value}, SAMPLING)


@pytest.mark.parametrize("field", ["presence_penalty", "min_p", "n", "stop", "logit_bias"])
def test_refuses_fields_the_eval_didnt_set(field):
    with pytest.raises(SamplingError, match="not part of the evaluated configuration"):
        enforce({"messages": MESSAGES, field: 1}, SAMPLING)


def test_keeps_neutral_fields_and_drops_the_router_cache_secret():
    body = {"messages": MESSAGES, "stream": True, "seed": 7, "user_cache_secret": "x"}
    forwarded = enforce(body, SAMPLING)
    assert forwarded["stream"] is True and forwarded["seed"] == 7 and "user_cache_secret" not in forwarded


def test_both_token_fields_is_ambiguous():
    with pytest.raises(SamplingError):
        enforce({"messages": MESSAGES, "max_tokens": 48, "max_completion_tokens": 48}, SAMPLING)


def test_unenforceable_params_are_refused_at_startup():
    with pytest.raises(ValueError, match="repetition_penalty"):
        check_sampling({"repetition_penalty": 1.1})


def test_a_param_the_eval_didnt_set_is_left_alone_and_refused():
    sampling = {k: v for k, v in SAMPLING.items() if k != "top_p"}
    assert "top_p" not in enforce({"messages": MESSAGES}, sampling)
    with pytest.raises(SamplingError, match="not part of the evaluated configuration"):
        enforce({"messages": MESSAGES, "top_p": 1.0}, sampling)
