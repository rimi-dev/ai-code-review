# =============================================================================
# Dockerfile for AI Code Review Bot - vLLM Inference Server
# =============================================================================
# Serves the fine-tuned code review model via an OpenAI-compatible API.
# Optimized for GPU inference with vLLM.
#
# Build:
#   docker build -t ai-code-review-server:latest -f serving/Dockerfile .
#
# Run:
#   docker run --gpus all -p 8000:8000 ai-code-review-server:latest
#
# Override model path (for volume-mounted models):
#   docker run --gpus all -p 8000:8000 \
#     -v /path/to/model:/models/ai-code-review \
#     ai-code-review-server:latest
# =============================================================================

FROM vllm/vllm-openai:latest

# Labels
LABEL maintainer="AI Code Review Bot Team"
LABEL description="vLLM inference server for the AI Code Review fine-tuned model"
LABEL version="1.0.0"

# Environment configuration with sensible defaults
ENV MODEL_PATH="/models/ai-code-review"
ENV HOST="0.0.0.0"
ENV PORT="8000"
ENV GPU_MEMORY_UTILIZATION="0.90"
ENV MAX_MODEL_LEN="4096"
ENV MAX_NUM_SEQS="64"
ENV DTYPE="auto"
ENV TENSOR_PARALLEL_SIZE="1"
ENV SERVED_MODEL_NAME="ai-code-review"
ENV TRUST_REMOTE_CODE="true"
ENV ENABLE_PREFIX_CACHING="true"

# vLLM-specific tuning
ENV VLLM_ATTENTION_BACKEND="FLASH_ATTN"
ENV VLLM_WORKER_MULTIPROC_METHOD="spawn"

# Create model directory
RUN mkdir -p /models/ai-code-review

# Copy model weights into the image
# NOTE: For large models, prefer volume mounting at runtime instead of COPY.
# Uncomment the line below if you want to bake the model into the image:
# COPY ./output/merged_model/ /models/ai-code-review/

# Copy the serving module for potential custom entrypoint usage
COPY serving/ /app/serving/

# Expose the API port
EXPOSE ${PORT}

# Health check: verify the server is responding
# The /health endpoint is provided by vLLM's OpenAI-compatible server
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Entrypoint: launch vLLM OpenAI API server with configured parameters
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]

CMD ["--model", "/models/ai-code-review", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--gpu-memory-utilization", "0.90", \
     "--max-model-len", "4096", \
     "--max-num-seqs", "64", \
     "--dtype", "auto", \
     "--tensor-parallel-size", "1", \
     "--served-model-name", "ai-code-review", \
     "--trust-remote-code", \
     "--enable-prefix-caching", \
     "--uvicorn-log-level", "info"]
