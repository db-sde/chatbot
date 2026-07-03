"""
security/policy.py — DegreeBaba-specific policy checks.

Three independent checks run after Prompt Guard 2:

  check_identity_attack()       — tries to make the bot deny being DegreeBaba AI
  check_prompt_extraction()     — tries to expose system prompt / instructions
  check_competitor_impersonation() — tries to get the bot to impersonate another AI

Each returns a PolicyResult.  The caller aggregates them.

Design principles:
  - Checks are structural (pattern-based), not keyword whitelists.
  - Patterns target the *attack structure*, not topic vocabulary.
  - New policies can be added by appending to the relevant list.
"""
from __future__ import annotations

import re
from typing import TypedDict


class PolicyResult(TypedDict):
    passed: bool
    rule: str | None   # Which rule fired; None when passed


# ---------------------------------------------------------------------------
# Pattern sets
# ---------------------------------------------------------------------------

_IDENTITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(you\s+are\s+not|you('re|\s+are)\s+really|your\s+true\s+name\s+is)", re.I),
    re.compile(r"(stop\s+being|don't\s+act\s+as)\s+(degreebaba|an?\s+(ai|assistant|bot))", re.I),
    re.compile(r"(reveal|admit|confess)\s+(you\s+are|that\s+you('re|\s+are))\s+(actually|really)", re.I),
    re.compile(r"who\s+(really\s+)?made\s+you.{0,30}(openai|google|anthropic|meta)", re.I),
]

_EXTRACTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(show|print|output|display|repeat|tell me|reveal|leak)\s+(your\s+)?(system\s+prompt|instructions?|config(uration)?|rules?)", re.I),
    re.compile(r"what\s+(do\s+your|are\s+your)\s+(hidden|internal|secret|initial|original)\s+(instructions?|rules?|prompts?)", re.I),
    re.compile(r"(developer|admin|debug)\s+(mode|instructions?|access|override)", re.I),
    re.compile(r"(ignore|bypass|skip|disregard|forget)\s+(previous|all|your)?\s*(instructions?|rules?|guidelines?|prompts?)", re.I),
    re.compile(r"(print|output)\s+everything\s+(above|before|prior)", re.I),
]

_IMPERSONATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"pretend\s+(you('re|\s+are)|to\s+be)\s+(chatgpt|gpt[-\s]?\d|openai|claude|gemini|bard|copilot)", re.I),
    re.compile(r"act\s+as\s+(chatgpt|gpt[-\s]?\d|openai|claude|gemini|bard|copilot)", re.I),
    re.compile(r"(you\s+are|now\s+you('re|\s+are))\s+(chatgpt|gpt[-\s]?\d|openai|claude|gemini|bard|copilot)", re.I),
    re.compile(r"(switch|change|transform)\s+(to|into)\s+(chatgpt|gpt|claude|gemini)", re.I),
]


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def check_identity_attack(message: str) -> PolicyResult:
    """Detects attempts to make the bot deny its DegreeBaba identity."""
    for pattern in _IDENTITY_PATTERNS:
        if pattern.search(message):
            return PolicyResult(passed=False, rule="identity_attack")
    return PolicyResult(passed=True, rule=None)


def check_prompt_extraction(message: str) -> PolicyResult:
    """Detects attempts to extract system prompt, instructions, or config."""
    for pattern in _EXTRACTION_PATTERNS:
        if pattern.search(message):
            return PolicyResult(passed=False, rule="prompt_extraction")
    return PolicyResult(passed=True, rule=None)


def check_competitor_impersonation(message: str) -> PolicyResult:
    """Detects attempts to make the bot impersonate a competitor AI."""
    for pattern in _IMPERSONATION_PATTERNS:
        if pattern.search(message):
            return PolicyResult(passed=False, rule="competitor_impersonation")
    return PolicyResult(passed=True, rule=None)


# ---------------------------------------------------------------------------
# Aggregate check
# ---------------------------------------------------------------------------

class PolicyCheckResult(TypedDict):
    passed: bool
    rule: str | None


def check_policy(message: str) -> PolicyCheckResult:
    """
    Run all policy checks in sequence.
    Returns on the first violation found.
    """
    for check in (check_identity_attack, check_prompt_extraction, check_competitor_impersonation):
        result = check(message)
        if not result["passed"]:
            return PolicyCheckResult(passed=False, rule=result["rule"])
    return PolicyCheckResult(passed=True, rule=None)
