import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[2] / "fixtures"
SAMPLING = {"max_new_tokens": 48, "temperature": 0.8, "top_k": 40, "top_p": 1.0}


@pytest.fixture(scope="session")
def receipt() -> dict:
    """OpenMined's receipt/v3 of the eval the demo serves: Gemma 4 12B (fixtures/receipt-v3.json)."""
    return json.loads((FIXTURES / "receipt-v3.json").read_text())


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def receipt_model(receipt: dict, role: str) -> dict:
    return next(m for m in receipt["predicate"]["evalPipeline"]["models"] if m["role"] == role)
