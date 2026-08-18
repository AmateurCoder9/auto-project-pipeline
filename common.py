"""
common.py

Shared infrastructure for the auto-project pipeline:

  - Exception hierarchy for typed error handling
  - Structured JSON logging factory
  - Retry/backoff helpers for external API calls

Every module in the pipeline imports from here rather than defining
its own ad-hoc error classes or print()-based logging.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class PipelineError(Exception):
    """Base exception for all pipeline errors."""


class AuthError(PipelineError):
    """Authentication or authorization failure (401/403). Do NOT retry."""


class RateLimitError(PipelineError):
    """Rate limit hit (429). May be retried after backoff."""


class DeploymentTimeoutError(PipelineError):
    """Vercel deployment did not reach READY within the allowed time."""


class ContentValidationError(PipelineError):
    """Gemini-generated content failed validation checks."""


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emits each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger that writes structured JSON to stderr.

    Call once per module:
        from common import get_logger
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, level, logging.INFO))
    return logger


# ---------------------------------------------------------------------------
# Retry / backoff helpers
# ---------------------------------------------------------------------------

class _RetryableHTTPError(Exception):
    """Wraps an HTTP response that should be retried (429, 502, 503, 504)."""
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {body[:300]}")


RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
FATAL_STATUS_CODES = {401, 403}


def check_response(resp: requests.Response, context: str = "") -> None:
    """
    Inspect an HTTP response and raise typed exceptions:
      - AuthError for 401/403 (never retried)
      - _RetryableHTTPError for 429/502/503/504 (retried by tenacity)
      - Nothing for 2xx
    """
    if 200 <= resp.status_code < 300:
        return

    body = resp.text[:500]
    prefix = f"{context}: " if context else ""

    if resp.status_code in FATAL_STATUS_CODES:
        raise AuthError(f"{prefix}HTTP {resp.status_code} — {body}")

    if resp.status_code in RETRYABLE_STATUS_CODES:
        raise _RetryableHTTPError(resp.status_code, f"{prefix}{body}")

    # Non-retryable, non-auth error
    raise PipelineError(f"{prefix}HTTP {resp.status_code} — {body}")


def _is_retryable(exc: BaseException) -> bool:
    """Only retry on transient HTTP errors and network failures."""
    if isinstance(exc, _RetryableHTTPError):
        return True
    if isinstance(exc, requests.ConnectionError):
        return True
    if isinstance(exc, requests.Timeout):
        return True
    return False


# Pre-built tenacity retry decorator for external API calls.
# Usage:
#   @api_retry
#   def my_api_call(...):
#       ...
api_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
