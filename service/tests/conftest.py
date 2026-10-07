import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[2] / "fixtures"
SAMPLING = {"max_new_tokens": 48, "temperature": 0.8, "top_k": 40}


@pytest.fixture(scope="session")
def receipt() -> dict:
    """OpenMined's example receipt/v3 (fixtures/receipt-v3.json)."""
    return json.loads((FIXTURES / "receipt-v3.json").read_text())


def receipt_model(receipt: dict, role: str) -> dict:
    return next(m for m in receipt["predicate"]["evalPipeline"]["models"] if m["role"] == role)
