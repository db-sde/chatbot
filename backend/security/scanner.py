"""
security/scanner.py — Prompt Guard 2 integration.

Provides a single interface: check_prompt_safety(message) -> SafetyResult

Runtime behaviour (confirmed via live API testing 2026-07-03):

  Prompt Guard 2 (86m / 22m) is a TEXT CLASSIFIER, not a chat model.
  API contract:
    - messages list must contain EXACTLY ONE user message.
    - NO system message is allowed.
    - Response content is a plain float string (e.g. "0.9996"), not JSON.
    - Float represents P(injection) — 0.0 = benign, 1.0 = definite attack.

  Old (broken) call sent [system, user] → HTTP 400:
    "messages must contains a single user message for text classification models"

Architecture:
  1. PromptGuardClient.scan() — Groq Prompt Guard 2 86m (primary)
  2. _local_heuristic()       — structural regex fallback

Telemetry constants logged at every call site:
  PROMPT_GUARD_PRIMARY_SUCCESS
  PROMPT_GUARD_PRIMARY_FAILED
  PROMPT_GUARD_FALLBACK_USED

Swap guide:
  Replace PromptGuardClient without touching the public check_prompt_safety()
  interface.
"""
from __future__ import annotations

import logging
import re
from typing import TypedDict

from settings import settings

logger = logging.getLogger(__name__)

# Threshold above which a message is considered an injection attack.
# 0.5 is the standard mid-point; we use 0.7 to reduce false positives on
# edge-case educational queries while still catching clear attacks.
_INJECTION_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class SafetyResult(TypedDict):
    safe: bool
    risk_score: float    # 0.0 (benign) – 1.0 (definite attack)
    reason: str | None   # None when safe
    source: str          # "prompt_guard_2" | "heuristic"


# ---------------------------------------------------------------------------
# Local heuristic fallback
# Used when Groq is unavailable.  Targets structural attack syntax only —
# NOT topic vocabulary, so greetings and education questions always pass.
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|all|your)\s+(instructions?|rules?|prompts?)", re.I),
    re.compile(r"(forget|disregard)\s+(your|all)\s+(instructions?|rules?|prompts?)", re.I),
    re.compile(r"(reveal|show|print|output|display)\s+(your\s+)?(system\s+prompt|instructions?|rules?|config)", re.I),
    re.compile(r"act\s+as\s+(?!a\s+student|an?\s+advisor|a\s+counsellor)", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(chatgpt|gpt|openai|claude|gemini)", re.I),
    re.compile(r"(jailbreak|bypass|override)\s+(your\s+)?(safety|filter|rules?|restrictions?)", re.I),
    re.compile(r"(write|execute|run)\s+sql", re.I),
    re.compile(r"drop\s+table", re.I),
    re.compile(r"developer\s+(instructions?|message|mode)", re.I),
    re.compile(r"what\s+are\s+your\s+(hidden|internal|secret)\s+(instructions?|rules?|prompts?)", re.I),
    re.compile(r"(repeat|tell me|say)\s+.*\s+(system\s+prompt|instructions?)", re.I),
]


def _local_heuristic(message: str) -> SafetyResult:
    """Structural regex fallback — never blocks greetings or education queries."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            return SafetyResult(
                safe=False,
                risk_score=0.92,
                reason="injection_pattern_heuristic",
                source="heuristic",
            )
    return SafetyResult(safe=True, risk_score=0.0, reason=None, source="heuristic")


# ---------------------------------------------------------------------------
# PromptGuardClient — correct API format
# ---------------------------------------------------------------------------

class PromptGuardClient:
    """
    Wraps Meta Llama Prompt Guard 2 via Groq's inference API.

    Key invariants:
      - messages list = [{"role": "user", "content": <message>}]  (exactly one)
      - No system message (classifier models reject it with HTTP 400)
      - Response is a plain float string, not JSON
      - score >= _INJECTION_THRESHOLD → injection attempt
    """

    MODEL = "meta-llama/llama-prompt-guard-2-86m"

    async def scan(self, message: str) -> SafetyResult | None:
        """
        Returns SafetyResult on success, None on any failure.
        Caller must fall back to heuristic when None is returned.
        """
        if not settings.groq_api_key:
            return None

        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=settings.groq_api_key)

            resp = await client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    # CRITICAL: exactly ONE user message, NO system message.
                    # Classifier models reject any other structure with HTTP 400.
                    {"role": "user", "content": message},
                ],
            )

            raw = (resp.choices[0].message.content or "").strip()

            # Response is a plain probability float (e.g. "0.9996"), not JSON.
            score = float(raw)
            is_injection = score >= _INJECTION_THRESHOLD

            logger.info(
                "PROMPT_GUARD_PRIMARY_SUCCESS score=%.4f injection=%s message_preview=%.60r",
                score, is_injection, message,
            )

            return SafetyResult(
                safe=not is_injection,
                risk_score=round(score, 4),
                reason="prompt_guard_2_injection" if is_injection else None,
                source="prompt_guard_2",
            )

        except Exception as exc:
            logger.warning(
                "PROMPT_GUARD_PRIMARY_FAILED error=%s — falling back to heuristic",
                exc,
            )
            return None


# Module-level singleton
_prompt_guard = PromptGuardClient()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def check_prompt_safety(message: str) -> SafetyResult:
    """
    Primary entry point — always returns a SafetyResult.

    Evaluation order:
      1. Prompt Guard 2 via Groq  (primary)
      2. Local regex heuristic    (fallback when primary fails)

    The system is fail-open on detection errors (falls back to heuristic)
    but never bypasses security entirely — heuristic always runs as a floor.
    """
    result = await _prompt_guard.scan(message)

    if result is not None:
        return result

    # Primary failed — use heuristic as floor
    logger.info("PROMPT_GUARD_FALLBACK_USED for message_preview=%.60r", message)
    return _local_heuristic(message)
