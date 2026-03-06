"""vLLM server launcher and wrapper for the AI Code Review Bot.

Provides a configurable wrapper around vLLM's OpenAI-compatible API server
with health checks, model loading, and optimal serving parameters.

Usage:
    python -m serving.vllm_server \
        --model-path ./output/merged_model \
        --port 8000 \
        --gpu-memory-utilization 0.90
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default server configuration
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_GPU_MEMORY_UTILIZATION = 0.90
DEFAULT_MAX_MODEL_LEN = 4096
DEFAULT_MAX_NUM_SEQS = 64
DEFAULT_DTYPE = "auto"
DEFAULT_TRUST_REMOTE_CODE = True


@dataclass
class ServerConfig:
    """Configuration for the vLLM inference server."""

    model_path: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    gpu_memory_utilization: float = DEFAULT_GPU_MEMORY_UTILIZATION
    max_model_len: int = DEFAULT_MAX_MODEL_LEN
    max_num_seqs: int = DEFAULT_MAX_NUM_SEQS
    dtype: str = DEFAULT_DTYPE
    trust_remote_code: bool = DEFAULT_TRUST_REMOTE_CODE
    tensor_parallel_size: int = 1
    quantization: str | None = None
    served_model_name: str = "ai-code-review"
    api_key: str | None = None
    enable_prefix_caching: bool = True
    disable_log_requests: bool = False
    uvicorn_log_level: str = "info"

    def to_cli_args(self) -> list[str]:
        """Convert config to vLLM CLI arguments."""
        args = [
            "--model", self.model_path,
            "--host", self.host,
            "--port", str(self.port),
            "--gpu-memory-utilization", str(self.gpu_memory_utilization),
            "--max-model-len", str(self.max_model_len),
            "--max-num-seqs", str(self.max_num_seqs),
            "--dtype", self.dtype,
            "--tensor-parallel-size", str(self.tensor_parallel_size),
            "--served-model-name", self.served_model_name,
            "--uvicorn-log-level", self.uvicorn_log_level,
        ]

        if self.trust_remote_code:
            args.append("--trust-remote-code")

        if self.quantization:
            args.extend(["--quantization", self.quantization])

        if self.api_key:
            args.extend(["--api-key", self.api_key])

        if self.enable_prefix_caching:
            args.append("--enable-prefix-caching")

        if self.disable_log_requests:
            args.append("--disable-log-requests")

        return args


class VLLMServer:
    """Manages the vLLM OpenAI-compatible API server lifecycle.

    Handles starting the server subprocess, health checking, and
    graceful shutdown with signal handling.

    Args:
        config: Server configuration.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._process: subprocess.Popen | None = None
        self._started: bool = False

    def start(self, wait_for_ready: bool = True, timeout: int = 300) -> None:
        """Start the vLLM server as a subprocess.

        Args:
            wait_for_ready: Whether to wait for the server health check.
            timeout: Maximum seconds to wait for server readiness.

        Raises:
            RuntimeError: If the model path does not exist.
            TimeoutError: If the server does not become ready within timeout.
        """
        model_path = Path(self.config.model_path)
        if not model_path.exists() and not self.config.model_path.startswith(("http://", "https://")):
            # Allow HuggingFace Hub model names to pass through
            if "/" not in self.config.model_path:
                msg = f"Model path does not exist: {self.config.model_path}"
                raise RuntimeError(msg)

        cli_args = self.config.to_cli_args()
        cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server"] + cli_args

        logger.info("Starting vLLM server: %s", " ".join(cmd))
        logger.info("Serving model: %s as '%s'", self.config.model_path, self.config.served_model_name)
        logger.info("Server will listen on %s:%d", self.config.host, self.config.port)

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if wait_for_ready:
            self._wait_for_ready(timeout)

        self._started = True
        logger.info("vLLM server started successfully (PID: %d)", self._process.pid)

    def _wait_for_ready(self, timeout: int) -> None:
        """Wait for the server to become ready by polling the health endpoint.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If server is not ready within timeout.
            RuntimeError: If the server process terminates unexpectedly.
        """
        health_url = f"http://localhost:{self.config.port}/health"
        start_time = time.monotonic()
        check_interval = 2.0  # seconds between checks

        logger.info("Waiting for server readiness at %s (timeout: %ds)", health_url, timeout)

        while time.monotonic() - start_time < timeout:
            # Check if process is still alive
            if self._process and self._process.poll() is not None:
                returncode = self._process.returncode
                # Read any remaining output
                stdout, _ = self._process.communicate()
                msg = f"vLLM server process terminated unexpectedly with code {returncode}"
                if stdout:
                    msg += f"\nOutput: {stdout[-2000:]}"
                raise RuntimeError(msg)

            try:
                response = httpx.get(health_url, timeout=5.0)
                if response.status_code == 200:
                    logger.info("Server is ready (took %.1fs)", time.monotonic() - start_time)
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

            time.sleep(check_interval)

        msg = f"Server did not become ready within {timeout}s"
        raise TimeoutError(msg)

    def health_check(self) -> dict[str, Any]:
        """Check the server's health status.

        Returns:
            Dict with health status information.
        """
        health_url = f"http://localhost:{self.config.port}/health"
        try:
            response = httpx.get(health_url, timeout=10.0)
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "url": health_url,
            }
        except Exception as e:
            return {
                "status": "unreachable",
                "error": str(e),
                "url": health_url,
            }

    def stop(self, timeout: int = 30) -> None:
        """Stop the vLLM server gracefully.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown.
        """
        if self._process is None:
            return

        logger.info("Stopping vLLM server (PID: %d)", self._process.pid)

        try:
            self._process.terminate()
            self._process.wait(timeout=timeout)
            logger.info("Server stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("Server did not stop gracefully, killing")
            self._process.kill()
            self._process.wait(timeout=5)
            logger.info("Server killed")
        finally:
            self._process = None
            self._started = False

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle termination signals for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s, shutting down server", sig_name)
        self.stop()
        sys.exit(0)

    @property
    def is_running(self) -> bool:
        """Check if the server process is running."""
        return self._process is not None and self._process.poll() is None

    def stream_logs(self) -> None:
        """Stream server logs to stdout. Blocks until server stops."""
        if self._process is None or self._process.stdout is None:
            logger.warning("No process or stdout to stream")
            return

        try:
            for line in self._process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
        except KeyboardInterrupt:
            self.stop()


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="vLLM Server for AI Code Review Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to the model directory or HuggingFace Hub model ID",
    )
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=DEFAULT_GPU_MEMORY_UTILIZATION,
        help="Fraction of GPU memory to use",
    )
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=DEFAULT_MAX_MODEL_LEN,
        help="Maximum model context length",
    )
    parser.add_argument(
        "--max-num-seqs",
        type=int,
        default=DEFAULT_MAX_NUM_SEQS,
        help="Maximum number of concurrent sequences",
    )
    parser.add_argument("--dtype", type=str, default=DEFAULT_DTYPE, help="Model dtype")
    parser.add_argument(
        "--tensor-parallel-size",
        type=int,
        default=1,
        help="Number of GPUs for tensor parallelism",
    )
    parser.add_argument(
        "--quantization",
        type=str,
        default=None,
        choices=[None, "awq", "gptq", "squeezellm"],
        help="Quantization method (if model is pre-quantized)",
    )
    parser.add_argument(
        "--served-model-name",
        type=str,
        default="ai-code-review",
        help="Name of the model in the API",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for authentication (also reads VLLM_API_KEY env)",
    )
    parser.add_argument(
        "--no-prefix-caching",
        action="store_true",
        default=False,
        help="Disable prefix caching",
    )
    parser.add_argument(
        "--disable-log-requests",
        action="store_true",
        default=False,
        help="Disable logging of individual requests",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait for server startup",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the vLLM server."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    api_key = args.api_key or os.environ.get("VLLM_API_KEY")

    config = ServerConfig(
        model_path=args.model_path,
        host=args.host,
        port=args.port,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        max_num_seqs=args.max_num_seqs,
        dtype=args.dtype,
        tensor_parallel_size=args.tensor_parallel_size,
        quantization=args.quantization,
        served_model_name=args.served_model_name,
        api_key=api_key,
        enable_prefix_caching=not args.no_prefix_caching,
        disable_log_requests=args.disable_log_requests,
    )

    server = VLLMServer(config)

    try:
        server.start(wait_for_ready=True, timeout=args.startup_timeout)
        logger.info("Server running. Press Ctrl+C to stop.")
        server.stream_logs()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception:
        logger.exception("Server failed to start")
        sys.exit(1)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
