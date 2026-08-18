"""
model_selector.py

Google renames and retires Gemini model IDs on a schedule outside our
control (gemini-2.0-flash was deprecated Feb 2026, retired Mar 3 2026 —
that is almost certainly the "limit: 0" error the old pipeline hit).

Rather than hardcode a model string that will eventually go stale again,
this module asks the API what is available RIGHT NOW and picks the best
usable option. It also does a real (cheap, ~5 token) test call so a dead
quota is caught before the actual generation step, with a clear error
message instead of a mysterious 429/403 mid-pipeline.

Usage:
    from model_selector import pick_working_model
    model_name = pick_working_model(api_key)
"""

import os
import sys

import requests

from common import PipelineError, api_retry, get_logger

logger = get_logger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Ordered by preference: try the most capable free-tier-eligible model
# first, fall back toward lighter/higher-quota models. This list is a
# STARTING GUESS, not a guarantee — the actual filtering happens by
# calling list_models() and test-generating, so if Google renames things
# again next quarter this still finds *something* rather than hardcoding
# one string.
PREFERRED_ORDER_SUBSTRINGS = [
    "flash-lite",   # highest RPD/RPM quota tier historically
    "flash",        # good balance, excludes "-lite" already matched above
    "pro",          # last resort — lowest free RPD historically
]


@api_retry
def list_available_models(api_key: str) -> list[dict]:
    """Ask Google which models this key can actually see."""
    resp = requests.get(
        f"{GEMINI_BASE}/models",
        params={"key": api_key},
        timeout=30,
    )
    if resp.status_code == 400:
        raise PipelineError(
            "Gemini API key rejected as malformed (HTTP 400). "
            "Double-check GEMINI_API_KEY was copied correctly with no "
            "extra spaces or quotes."
        )
    if resp.status_code == 403:
        raise PipelineError(
            "Gemini API key rejected as unauthorized (HTTP 403). "
            "The key may be disabled, or the Generative Language API "
            "is not enabled on its Google Cloud project. Visit "
            "https://aistudio.google.com/apikey to check its status."
        )
    resp.raise_for_status()
    data = resp.json()
    models = data.get("models", [])
    # Only keep models that support generateContent at all
    return [
        m for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]


def _rank(model_name: str) -> int:
    """Lower rank = more preferred. Unknown names sort last."""
    name = model_name.lower()
    for i, key in enumerate(PREFERRED_ORDER_SUBSTRINGS):
        if key in name:
            return i
    return len(PREFERRED_ORDER_SUBSTRINGS)


def _test_generate(api_key: str, model_name: str) -> tuple[bool, str]:
    """
    Fire one minimal real request to confirm this model+key actually
    has quota right now. Returns (ok, message).
    """
    url = f"{GEMINI_BASE}/{model_name}:generateContent"
    body = {"contents": [{"parts": [{"text": "Reply with just: ok"}]}]}
    try:
        resp = requests.post(url, params={"key": api_key}, json=body, timeout=30)
    except requests.RequestException as e:
        return False, f"network error: {e}"

    if resp.status_code == 200:
        return True, "ok"

    if resp.status_code == 429:
        # This is the "limit: 0" case — quota exhausted or model dead
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        return False, f"429 rate/quota limited: {detail}"

    if resp.status_code == 404:
        return False, "404 — model name not found (likely renamed/retired)"

    return False, f"HTTP {resp.status_code}: {resp.text[:300]}"


def pick_working_model(api_key: str, verbose: bool = True) -> str:
    """
    Returns a model name string that is confirmed (via live test call)
    to be callable with this API key right now.

    Raises PipelineError with a clear diagnostic message if NOTHING
    works, so the pipeline fails loud and early instead of silently
    producing nothing.
    """
    models = list_available_models(api_key)
    if not models:
        raise PipelineError(
            "Gemini API returned zero models supporting generateContent "
            "for this key. This usually means the key's Google Cloud "
            "project has the Generative Language API disabled. Enable "
            "it at https://console.cloud.google.com/apis/library/"
            "generativelanguage.googleapis.com for the correct project."
        )

    names = sorted((m["name"] for m in models), key=_rank)

    if verbose:
        logger.info(f"{len(names)} candidate model(s) found, testing in preference order...")

    attempts = []
    for name in names:
        ok, msg = _test_generate(api_key, name)
        attempts.append((name, ok, msg))
        if verbose:
            status = "OK" if ok else "FAIL"
            logger.info(f"  {name}: {status} ({msg})")
        if ok:
            if verbose:
                logger.info(f"Using: {name}")
            return name

    # Nothing worked — build a diagnostic error instead of a generic crash
    lines = ["No Gemini model succeeded with this API key. Attempts:"]
    for name, ok, msg in attempts:
        lines.append(f"  - {name}: {msg}")
    lines.append(
        "\nMost likely causes:\n"
        "  1. This key's Google Cloud project has fully exhausted its\n"
        "     free-tier quota pool (quotas are PER PROJECT, not per key —\n"
        "     a new key on the same project inherits the same exhaustion).\n"
        "     Fix: create a genuinely new Google Cloud project, then a\n"
        "     new key from AI Studio while that new project is selected.\n"
        "  2. Billing has not been enabled and the project's free-tier\n"
        "     window has lapsed. Fix: enable billing at\n"
        "     https://console.cloud.google.com/billing (Gemini Flash\n"
        "     models remain inexpensive even when paid).\n"
    )
    raise PipelineError("\n".join(lines))


if __name__ == "__main__":
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        logger.error("Set GEMINI_API_KEY to test this module standalone.")
        sys.exit(1)
    try:
        chosen = pick_working_model(key)
        logger.info(f"Working model: {chosen}")
    except PipelineError as e:
        logger.error(str(e))
        sys.exit(1)
