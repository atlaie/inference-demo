"""Run the service: `python -m inference_service`. Settings come from the environment (settings.py)."""

import logging

import uvicorn

from inference_service.app import create_app
from inference_service.settings import load_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = load_settings()
    # All interfaces of the container: Tinfoil's shim, in the same enclave, is what reaches it.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
