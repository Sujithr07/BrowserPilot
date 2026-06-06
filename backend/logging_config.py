"""
Structured logging for AgentFlow.

Emits one JSON object per line (timestamp, level, logger, message, plus any
`extra=` fields), which is greppable in dev and ingestable by log shippers in
prod. Call `configure_logging()` once at process start (API and worker both do).
Use `get_logger(__name__)` and pass structured context via `extra=`:

    log = get_logger(__name__)
    log.info("job.enqueued", extra={"task_id": tid, "goal": goal})
"""
import os
import sys
import json
import logging
import time

# Keys always present on a LogRecord — everything else the caller passed via
# `extra=` is treated as structured context and merged into the JSON line.
_RESERVED = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge structured context from `extra=`.
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_CONFIGURED = False


def configure_logging() -> None:
    """Idempotently install the JSON formatter on the root logger."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Keep noisy third parties at WARNING unless LOG_LEVEL is DEBUG.
    if level != "DEBUG":
        for noisy in ("httpx", "httpcore", "LiteLLM", "arq", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
