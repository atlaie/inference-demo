# The inference enclave's container: stock vLLM CPU with this service in front of it.
# Nothing is installed: the service runs on the image's own Python and packages, the versions
# pyproject.toml pins for tests.
FROM vllm/vllm-openai-cpu@sha256:495c84fe30f3572b83a78100a1e8ba423dbb77fc532ecefebe114e6b77327bd9

COPY src/sash_inference /opt/sash-inference/sash_inference
ENV PYTHONPATH=/opt/sash-inference
ENTRYPOINT ["python3", "-m", "sash_inference"]
