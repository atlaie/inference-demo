# The inference enclave's container: stock vLLM with this service in front of it. The enclave runs
# vLLM's CUDA build; the local twin builds this on vLLM's CPU build (container/compose.yaml).
# Nothing is installed: the service runs on the image's own Python and packages, which both builds
# ship in the versions pyproject.toml pins for tests.
ARG VLLM_IMAGE=vllm/vllm-openai@sha256:c1c9f6fd5c109ba7f0546a59f5b2f15fb87f64c77782e90a27b648b42a8e67c3
FROM ${VLLM_IMAGE}

COPY src/inference_service /opt/inference-service/inference_service
ENV PYTHONPATH=/opt/inference-service
ENTRYPOINT ["python3", "-m", "inference_service"]
