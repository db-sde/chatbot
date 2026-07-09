"""
security/scanner.py — Prompt Guard 2 integration with local fallback.

Provides a single interface: check_prompt_safety(message) -> SafetyResult
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import TypedDict
from collections import defaultdict
from enum import Enum

from settings import settings

logger = logging.getLogger(__name__)

# Threshold above which a message is considered an injection attack.
_INJECTION_THRESHOLD = 0.7
_HEURISTIC_THRESHOLD = 0.65  # Below this, heuristic says safe

# Input limits (prevent ReDoS and memory exhaustion)
_MAX_INPUT_LENGTH = 10000

# Circuit breaker config
_CIRCUIT_BREAKER_THRESHOLD = 5   # failures before opening
_CIRCUIT_BREAKER_TIMEOUT = 30    # seconds before half-open


class RiskLevel(Enum):
    BENIGN = "benign"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"


class SafetyResult(TypedDict):
    safe: bool
    risk_score: float    # 0.0 (benign) – 1.0 (definite attack)
    risk_level: str      # "benign" | "suspicious" | "malicious"
    reason: str | None   # None when safe
    source: str          # "prompt_guard_2" | "heuristic"
    details: dict        # Rich diagnostic info for metrics/debugging


@dataclass
class SessionState:
    """Tracks per-session risk for escalation detection."""
    message_count: int = 0
    total_risk_score: float = 0.0
    blocked_count: int = 0
    last_message_time: float = 0.0
    pattern_hits: list[str] = field(default_factory=list)

    @property
    def average_risk(self) -> float:
        return self.total_risk_score / max(self.message_count, 1)

    @property
    def is_escalating(self) -> bool:
        """Detect if user is probing defenses."""
        if self.message_count < 3:
            return False
        block_rate = self.blocked_count / self.message_count
        return block_rate > 0.3 or self.average_risk > 0.4


# ---------------------------------------------------------------------------
# 1. INPUT NORMALIZATION
# ---------------------------------------------------------------------------

_ZERO_WIDTH_CHARS = re.compile(r"[​‌‍﻿⁠᠎]")

_HOMOGLYPH_MAP = str.maketrans({
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c',
    'А': 'A', 'Е': 'E', 'О': 'O', 'Р': 'P', 'С': 'C',
})


def normalize_input(message: str) -> str:
    """Normalize input to prevent obfuscation bypasses."""
    message = _ZERO_WIDTH_CHARS.sub("", message)
    message = unicodedata.normalize("NFKC", message)
    message = message.translate(_HOMOGLYPH_MAP)
    message = " ".join(message.split())
    return message.lower().strip()


def detect_obfuscation(message: str) -> float:
    """Detect common obfuscation techniques. Returns 0.0-1.0 score."""
    score = 0.0

    # Base64 detection
    b64_pattern = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
    if b64_pattern.search(message):
        score += 0.3

    # Excessive spacing (e.g., "i g n o r e")
    if re.search(r"(\w\s){3,}\w", message):
        score += 0.2

    # Leetspeak
    leet_chars = sum(1 for c in message if c in "1337$@&!")
    if leet_chars > 3:
        score += 0.15

    # Mixed scripts (e.g., Cyrillic + Latin)
    scripts = set()
    for char in message:
        if "\u0400" <= char <= "\u04FF":  # Cyrillic
            scripts.add("cyrillic")
        elif char.isalpha():
            scripts.add("latin")
    if len(scripts) > 1:
        score += 0.25

    # URL encoding
    if "%" in message and re.search(r"%[0-9A-Fa-f]{2}", message):
        score += 0.1

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# 2. SCORING-BASED HEURISTIC
# ---------------------------------------------------------------------------

@dataclass
class HeuristicRule:
    """A weighted heuristic rule with context awareness."""
    patterns: list[re.Pattern[str]]
    weight: float
    safe_contexts: list[re.Pattern[str]]  # Patterns that negate this rule
    description: str
    category: str


_HEURISTIC_RULES: list[HeuristicRule] = [
    HeuristicRule(
        patterns=[
            re.compile(r"ignore\s+(previous|all|your)\s+(instructions?|rules?|prompts?)", re.I),
            re.compile(r"(forget|disregard)\s+(your|all)\s+(instructions?|rules?|prompts?)", re.I),
        ],
        weight=0.9,
        safe_contexts=[
            re.compile(r"(essay|paper|article|write|explain)\s+about\s+(prompt|injection|security)", re.I),
            re.compile(r"(how|what|why)\s+(does|is|are)\s+(prompt injection|ignore previous)", re.I),
        ],
        description="instruction_override",
        category="direct_injection",
    ),
    HeuristicRule(
        patterns=[
            re.compile(r"(reveal|show|print|output|display)\s+(your\s+)?(system\s+prompt|instructions?|rules?|config)", re.I),
            re.compile(r"what\s+are\s+your\s+(hidden|internal|secret)\s+(instructions?|rules?|prompts?)", re.I),
            re.compile(r"(repeat|tell me|say)\s+.*\s+(system\s+prompt|instructions?)", re.I),
        ],
        weight=0.85,
        safe_contexts=[
            re.compile(r"(security|research|audit|penetration test)", re.I),
        ],
        description="prompt_exfiltration",
        category="information_leak",
    ),
    HeuristicRule(
        patterns=[
            re.compile(r"(jailbreak|bypass|override)\s+(your\s+)?(safety|filter|rules?|restrictions?)", re.I),
            re.compile(r"developer\s+(instructions?|message|mode)", re.I),
        ],
        weight=0.7,
        safe_contexts=[
            re.compile(r"(explain|describe|what is|how does)\s+(jailbreak|bypass|safety)", re.I),
        ],
        description="safety_override",
        category="jailbreak",
    ),
    HeuristicRule(
        patterns=[
            re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(chatgpt|gpt|openai|claude|gemini)", re.I),
            re.compile(r"act\s+as\s+(?!a\s+student|an?\s+advisor|a\s+counsellor)", re.I),
        ],
        weight=0.6,
        safe_contexts=[
            re.compile(r"(write|create|draft|compose)\s+(as|like|in the style of)", re.I),
        ],
        description="role_impersonation",
        category="social_engineering",
    ),
    HeuristicRule(
        patterns=[
            re.compile(r"(write|execute|run)\s+sql", re.I),
            re.compile(r"drop\s+table", re.I),
        ],
        weight=0.4,
        safe_contexts=[
            re.compile(r"(explain|what is|how does|tutorial|learn)\s+(sql|database|query)", re.I),
        ],
        description="sql_injection",
        category="code_injection",
    ),
    HeuristicRule(
        patterns=[
            re.compile(r"(new\s+instructions?|updated\s+rules?|from\s+now\s+on)\s*[:;]", re.I),
            re.compile(r"\[system\s*:\s*.*\]", re.I),
            re.compile(r"<system>.*</system>", re.I | re.S),
        ],
        weight=0.75,
        safe_contexts=[],
        description="indirect_injection",
        category="indirect_injection",
    ),
]



def _local_heuristic(message: str, session: SessionState | None = None) -> SafetyResult:
    """Scoring-based heuristic fallback."""
    normalized = normalize_input(message)

    if len(message) > _MAX_INPUT_LENGTH:
        return SafetyResult(
            safe=False,
            risk_score=1.0,
            risk_level=RiskLevel.MALICIOUS.value,
            reason="input_too_long",
            source="heuristic",
            details={"max_length": _MAX_INPUT_LENGTH, "actual_length": len(message)}
        )

    obfuscation_score = detect_obfuscation(message)

    total_score = 0.0
    max_single_score = 0.0
    matched_rules = []

    for rule in _HEURISTIC_RULES:
        rule_score = 0.0
        for pattern in rule.patterns:
            if pattern.search(normalized):
                rule_score = rule.weight
                break

        if rule_score > 0:
            for safe_pattern in rule.safe_contexts:
                if safe_pattern.search(normalized):
                    rule_score *= 0.3
                    break

        if rule_score > 0:
            total_score += rule_score
            max_single_score = max(max_single_score, rule_score)
            matched_rules.append({
                "category": rule.category,
                "description": rule.description,
                "score": round(rule_score, 3),
            })

    combined_score = max_single_score + (total_score - max_single_score) * 0.3
    combined_score = max(combined_score, obfuscation_score)
    combined_score = min(combined_score, 1.0)

    escalation_bonus = 0.0
    if session and session.is_escalating:
        escalation_bonus = 0.15
        combined_score = min(combined_score + escalation_bonus, 1.0)

    is_injection = combined_score >= _HEURISTIC_THRESHOLD

    details = {
        "matched_rules": matched_rules,
        "obfuscation_score": round(obfuscation_score, 3),
        "escalation_bonus": round(escalation_bonus, 3),
        "session_message_count": session.message_count if session else 0,
    }

    if is_injection:
        return SafetyResult(
            safe=False,
            risk_score=round(combined_score, 4),
            risk_level=RiskLevel.MALICIOUS.value if combined_score > 0.8 else RiskLevel.SUSPICIOUS.value,
            reason=f"heuristic_combined_score_{combined_score:.2f}",
            source="heuristic",
            details=details,
        )

    return SafetyResult(
        safe=True,
        risk_score=round(combined_score, 4),
        risk_level=RiskLevel.BENIGN.value,
        reason=None,
        source="heuristic",
        details=details,
    )


# ---------------------------------------------------------------------------
# 3. CIRCUIT BREAKER
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker for external API calls."""

    def __init__(self):
        self._failures = 0
        self._last_failure = 0.0
        self._state = "closed"

    def can_call(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.time() - self._last_failure > _CIRCUIT_BREAKER_TIMEOUT:
                self._state = "half-open"
                return True
            return False
        return True

    def record_success(self):
        self._failures = 0
        self._state = "closed"

    def record_failure(self):
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= _CIRCUIT_BREAKER_THRESHOLD:
            self._state = "open"


# ---------------------------------------------------------------------------
# 4. SESSION ESCALATION MANAGER
# ---------------------------------------------------------------------------

class SessionManager:
    """Manages session state for escalation detection."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = defaultdict(SessionState)

    def get(self, session_id: str) -> SessionState:
        return self._sessions[session_id]

    def update(self, session_id: str, result: SafetyResult):
        session = self._sessions[session_id]
        session.message_count += 1
        session.total_risk_score += result["risk_score"]
        if not result["safe"]:
            session.blocked_count += 1
        session.last_message_time = time.time()
        if result["reason"]:
            session.pattern_hits.append(result["reason"])

        # Prevent unbounded memory growth by running O(N) cleanup occasionally
        if len(self._sessions) > 1000:
            self.cleanup()


    def cleanup(self, max_age: float = 3600):
        now = time.time()
        stale = [sid for sid, s in self._sessions.items() if now - s.last_message_time > max_age]
        for sid in stale:
            del self._sessions[sid]


# ---------------------------------------------------------------------------
# 5. PromptGuardClient
# ---------------------------------------------------------------------------

class PromptGuardClient:
    """Wraps Meta Llama Prompt Guard 2 via Groq's inference API."""

    def __init__(self):
        self._circuit_breaker = CircuitBreaker()

    async def scan(
        self,
        message: str,
        timeout: float = 5.0,
        max_retries: int = 2,
    ) -> SafetyResult | None:
        if not settings.groq_api_key:
            return None

        if not self._circuit_breaker.can_call():
            logger.info("PROMPT_GUARD_CIRCUIT_OPEN — skipping API call")
            return None

        for attempt in range(max_retries + 1):
            try:
                from llm.provider import get_prompt_guard_model
                from langchain_core.messages import HumanMessage

                model = get_prompt_guard_model()

                resp = await asyncio.wait_for(
                    model.ainvoke([HumanMessage(content=message)]),
                    timeout=timeout,
                )
                raw = (resp.content or "").strip()
                score = float(raw)
                is_injection = score >= _INJECTION_THRESHOLD

                self._circuit_breaker.record_success()

                logger.info(
                    "PROMPT_GUARD_PRIMARY_SUCCESS score=%.4f injection=%s attempt=%d",
                    score, is_injection, attempt,
                )

                return SafetyResult(
                    safe=not is_injection,
                    risk_score=round(score, 4),
                    risk_level=RiskLevel.MALICIOUS.value if is_injection else RiskLevel.BENIGN.value,
                    reason="prompt_guard_2_injection" if is_injection else None,
                    source="prompt_guard_2",
                    details={"attempt": attempt, "timeout": timeout},
                )

            except asyncio.TimeoutError:
                logger.warning("PROMPT_GUARD_TIMEOUT attempt=%d", attempt)
                if attempt == max_retries:
                    self._circuit_breaker.record_failure()
                    return None
                await asyncio.sleep(0.5 * (2 ** attempt))

            except Exception as exc:
                logger.warning("PROMPT_GUARD_PRIMARY_FAILED error=%s attempt=%d", exc, attempt)
                if attempt == max_retries:
                    self._circuit_breaker.record_failure()
                    return None
                await asyncio.sleep(0.5 * (2 ** attempt))

        return None


_prompt_guard = PromptGuardClient()
_session_manager = SessionManager()


# ---------------------------------------------------------------------------
# 6. Public interface
# ---------------------------------------------------------------------------

async def check_prompt_safety(
    message: str,
    session_id: str | None = None,
) -> SafetyResult:
    """
    Multi-layer prompt safety defense pipeline:
      1. Normalization + obfuscation checks
      2. Prompt Guard 2 via Groq (primary, with circuit breaker + retries)
      3. Scoring-based local heuristic fallback (with context whitelisting)
      4. Session escalation tracking
    """
    start_time = time.time()

    # 1. Normalization & input length check
    if len(message) > _MAX_INPUT_LENGTH:
        return SafetyResult(
            safe=False,
            risk_score=1.0,
            risk_level=RiskLevel.MALICIOUS.value,
            reason="input_too_long",
            source="heuristic",
            details={"max_length": _MAX_INPUT_LENGTH},
        )

    session = _session_manager.get(session_id) if session_id else None

    # 2. Local checks are immediate. A definite local block does not need to
    # wait through external retries; this preserves the stricter outcome while
    # avoiding avoidable attack-path latency.
    heuristic_result = _local_heuristic(message, session)
    if not heuristic_result["safe"]:
        _session_manager.update(session_id, heuristic_result) if session_id else None
        heuristic_result["details"]["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
        logger.info("PROMPT_GUARD_SKIPPED_LOCAL_BLOCK")
        return heuristic_result

    # Only benign local input needs the remote classifier.
    pg_result = await _prompt_guard.scan(message)

    if pg_result is None:
        logger.info("PROMPT_GUARD_FALLBACK_USED")
        result = heuristic_result
    else:
        # Combine results: block if either detector blocks
        safe = pg_result["safe"] and heuristic_result["safe"]
        risk_score = max(pg_result["risk_score"], heuristic_result["risk_score"])
        
        # Risk level: use the more severe level
        def get_severity(level: str) -> int:
            if level == "malicious":
                return 2
            if level == "suspicious":
                return 1
            return 0

        pg_level = pg_result.get("risk_level", "benign")
        h_level = heuristic_result.get("risk_level", "benign")
        risk_level = pg_level if get_severity(pg_level) >= get_severity(h_level) else h_level

        # Reason & source determination
        reason = pg_result["reason"] or heuristic_result["reason"]
        if not pg_result["safe"] and not heuristic_result["safe"]:
            source = "combined"
        elif not pg_result["safe"]:
            source = "prompt_guard_2"
        elif not heuristic_result["safe"]:
            source = "heuristic"
        else:
            # Both detectors ran and both passed: primary detector gets credit
            source = "prompt_guard_2"

        result = SafetyResult(
            safe=safe,
            risk_score=risk_score,
            risk_level=risk_level,
            reason=reason,
            source=source,
            details={
                "prompt_guard": pg_result.get("details") or {},
                "heuristic": heuristic_result.get("details") or {},
            },
        )

    # 4. Session escalation tracking
    if session_id:
        _session_manager.update(session_id, result)
        session = _session_manager.get(session_id)

        # Session escalation override
        if result["safe"] and session.is_escalating:
            result = SafetyResult(
                safe=False,
                risk_score=min(result["risk_score"] + 0.2, 1.0),
                risk_level=RiskLevel.SUSPICIOUS.value,
                reason="session_escalation_detected",
                source="heuristic",
                details={**result.get("details", {}), "session_avg_risk": session.average_risk},
            )

    # Add execution elapsed time
    elapsed = time.time() - start_time
    result["details"]["elapsed_ms"] = round(elapsed * 1000, 2)

    return result
