"""
lead_detector.py
=================

DegreeBaba — Lead Intelligence Engine
--------------------------------------

Stage 3 of the pipeline:

    User Message -> Intent Classifier -> Entity Resolver -> [Lead Detector] -> Decision Engine -> Route

This module is a pure, deterministic scoring engine with no side effects. It
does not decide *what the user is asking about* (that is intent.py's job) or
*which university/course they mean* (that is resolve.py's job). It answers a
different, business-critical question:

    How likely is this user to become a counselling lead, and what should
    we do about it right now?

Business context:
    DegreeBaba is not a chatbot company — it is a lead generation company.
    The chatbot exists to build trust, qualify users, capture leads, and
    connect them with human counsellors. The primary KPI this file serves
    is:

        Qualified Leads Generated

    NOT chat accuracy. Every scoring decision below is written with that in
    mind: a technically correct, well-answered question that produces no
    lead is worth less to the business than a slightly rougher interaction
    that surfaces a callback request.

User classes this detector distinguishes:
    Type 1 — Information Seeker   (score ~10-50)  e.g. "NMIMS fees"
    Type 2 — Decision Seeker      (score ~60-85)  e.g. "Which MBA should I choose?"
    Type 3 — Admission Ready      (score ~85-100) e.g. "Apply now", "Call me"

Hard constraints (do not violate these when editing this file):
    * No LLM calls.
    * No database calls.
    * No network calls.
    * No tool calls.
    * Deterministic only — same inputs must always produce the same output.
    * Target execution time: < 5ms per call.

Editing patterns:
    Everything a growth/business team would want to tune lives in the
    ALL-CAPS pattern tables near the top of the file (HIGH_INTENT_PATTERNS,
    MEDIUM_INTENT_PATTERNS, LOW_INTENT_PATTERNS, RECOMMENDATION_PATTERNS,
    CALLBACK_PATTERNS, ADMISSION_PATTERNS). Adding/removing a keyword there
    does not require touching any classifier logic below.

Upstream integration:
    intent.py already computes a rough `lead_score` / `lead_priority` from
    intent alone (no entities, no session, no callback/admission-specific
    detection). This module treats that as one input signal among several —
    it is blended with this file's own message-level pattern scoring, then
    layered with entity bonuses, session bonuses, and explicit
    callback/recommendation/admission detection — rather than being
    ignored or being treated as the final answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Tuple

# ---------------------------------------------------------------------------
# Upstream types (Stage 1 / Stage 2 of the pipeline).
#
# IntentResult is produced by intent.py. We import the real thing so this
# file stays in sync with whatever intent.py actually returns. A minimal
# fallback is provided so this module can still be imported/tested in
# isolation (e.g. in a scratch environment where intent.py isn't on the
# path yet).
# ---------------------------------------------------------------------------
try:
    from intent import IntentResult, LeadPriority  # type: ignore
except ImportError:  # pragma: no cover - standalone fallback only

    class LeadPriority(Enum):  # type: ignore[no-redef]
        NONE = "NONE"
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"

    @dataclass
    class IntentResult:  # type: ignore[no-redef]
        intent: str
        confidence: float
        route_type: str
        lead_score: int
        lead_priority: "LeadPriority"


# ---------------------------------------------------------------------------
# EntityResult / SessionContext are produced by the Entity Resolver
# (resolve.py) and the conversation/graph state (graph.py) respectively.
# They are declared here to match the agreed contract; if resolve.py /
# graph.py already export equivalent dataclasses in the real codebase,
# import those instead of these and remove this block.
# ---------------------------------------------------------------------------


@dataclass
class EntityResult:
    universities: List[str] = field(default_factory=list)
    courses: List[str] = field(default_factory=list)
    specializations: List[str] = field(default_factory=list)


@dataclass
class SessionContext:
    current_university_slug: Optional[str] = None
    current_course_slug: Optional[str] = None
    current_specialization_slug: Optional[str] = None
    comparison_context: Dict[str, Any] = field(default_factory=dict)
    profile_context: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# ENUMS
# =============================================================================


class LeadLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    HOT = "HOT"


class LeadAction(Enum):
    NONE = "NONE"
    SHOW_CTA = "SHOW_CTA"
    START_FUNNEL = "START_FUNNEL"
    OFFER_CALLBACK = "OFFER_CALLBACK"
    CAPTURE_LEAD = "CAPTURE_LEAD"
    URGENT_COUNSELLOR = "URGENT_COUNSELLOR"


# =============================================================================
# RESULT OBJECT
# =============================================================================


@dataclass
class LeadSignal:
    score: int
    level: LeadLevel
    action: LeadAction
    should_start_funnel: bool
    should_offer_callback: bool
    should_capture_lead: bool
    should_escalate_to_counsellor: bool
    reasons: List[str] = field(default_factory=list)


# =============================================================================
# CONFIGURATION — business team edits these tables only
# =============================================================================
#
# Pattern conventions (same as intent.py):
#   * All patterns are matched against a lower-cased, whitespace-normalized
#     version of the user message.
#   * Patterns are plain regular expressions. Use \b for word boundaries on
#     single tokens. Multi-word phrases use \s+ between words so variable
#     spacing still matches.
#   * A message can hit patterns in more than one table — that is expected.
#     Each table drives a different piece of the scoring/decision logic.

HIGH_INTENT_PATTERNS: List[str] = [
    r"\badmission\b",
    r"\bapply\b",
    r"\bapplication\b",
    r"\benrol+\b",
    r"\bregistration\b",
    r"\bscholarship\b",
    r"\blast\s+date\b",
    r"\bdeadline\b",
    r"\bcall\s+me\b",
    r"\bcallback\b",
    r"\bcall\s+back\b",
    r"\bphone\b",
    r"\bcontact\b",
    r"\badvisor\b",
    r"\bcounsel?lor\b",
]

MEDIUM_INTENT_PATTERNS: List[str] = [
    r"\bfees?\b",
    r"\beligib\w*\b",
    r"\bplacements?\b",
    r"\breviews?\b",
    r"\bcompar\w*\b",
    r"\bspeciali[sz]ations?\b",
]

LOW_INTENT_PATTERNS: List[str] = [
    r"\bwhat\s+is\s+mba\b",
    r"\bwhat\s+is\s+bba\b",
    r"\bwhat\s+is\s+distance\s+learning\b",
    r"\bwhat\s+is\s+ugc\b",
]

# Recommendation / decision-seeker language. These users are often valuable
# leads (Type 2) even though they aren't asking anything admission-specific.
RECOMMENDATION_PATTERNS: List[str] = [
    r"\bwhich\s+mba\s+should\s+i\s+choose\b",
    r"\bbest\s+mba\b",
    r"\bsuggest\s+(?:a\s+)?university\b",
    r"\bsuggest\s+(?:me\s+)?(?:a\s+)?college\b",
    r"\bhelp\s+me\s+choose\b",
    r"\bi\s*(?:'m|am)\s+confused\b",
    r"\bneed\s+guidance\b",
    r"\bwhich\s+university\b",
    r"\bwhich\s+speciali[sz]ation\s+should\s+i\s+take\b",
]

# Explicit "get a human on the phone" requests.
CALLBACK_PATTERNS: List[str] = [
    r"\bcall\s+me\b",
    r"\bcall\s+back\b",
    r"\bcallback\b",
    r"\bcontact\s+me\b",
    r"\btalk\s+to\s+(?:a\s+)?counsel?lor\b",
    r"\bspeak\s+(?:with|to)\s+(?:a\s+)?(?:counsel?lor|advisor|someone)\b",
    r"\badvisor\s+call\b",
    r"\bneed\s+(?:a\s+)?counsel?lor\b",
]

# Signals that the user is at (or past) the point of actually applying.
ADMISSION_PATTERNS: List[str] = [
    r"\badmission\s+process\b",
    r"\blast\s+date\b",
    r"\bapply\s+now\b",
    r"\bhow\s+to\s+apply\b",
    r"\bregistration\b",
    r"\bscholarship\b",
]


# =============================================================================
# COMPILED PATTERNS (compiled once at import time to stay under the
# per-call latency budget)
# =============================================================================


def _compile(patterns: List[str]) -> List[Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_COMPILED_HIGH: List[Pattern[str]] = _compile(HIGH_INTENT_PATTERNS)
_COMPILED_MEDIUM: List[Pattern[str]] = _compile(MEDIUM_INTENT_PATTERNS)
_COMPILED_LOW: List[Pattern[str]] = _compile(LOW_INTENT_PATTERNS)
_COMPILED_RECOMMENDATION: List[Pattern[str]] = _compile(RECOMMENDATION_PATTERNS)
_COMPILED_CALLBACK: List[Pattern[str]] = _compile(CALLBACK_PATTERNS)
_COMPILED_ADMISSION: List[Pattern[str]] = _compile(ADMISSION_PATTERNS)

_WHITESPACE_RE = re.compile(r"\s+")

# Score bands -> LeadLevel. Matches the business definition of the three
# user types (Info Seeker / Decision Seeker / Admission Ready), with the
# boundary between "engaged but cold" and "warm" placed at 30.
_LEVEL_BANDS: Tuple[Tuple[int, int, LeadLevel], ...] = (
    (0, 29, LeadLevel.LOW),
    (30, 59, LeadLevel.MEDIUM),
    (60, 84, LeadLevel.HIGH),
    (85, 100, LeadLevel.HOT),
)

# Score floors applied when an explicit business signal fires, so the
# numeric score and the resulting level/action never contradict each other
# (e.g. a message that says "call me" should never end up scored LOW).
_ADMISSION_READY_FLOOR = 85
_CALLBACK_FLOOR = 90
_RECOMMENDATION_FLOOR = 60


# =============================================================================
# MAIN CLASS
# =============================================================================


class LeadDetector:
    """
    Deterministic lead-scoring engine for DegreeBaba.

    Converts (raw_message, IntentResult, EntityResult, SessionContext) into
    a single LeadSignal describing how hot the lead is and what the system
    should do next.

    This class deliberately does not:
        * call an LLM
        * call a database
        * call any external tool or service
    It only answers: "given everything we know about this turn, how strong
    a lead is this, and what's the next best action?"
    """

    __slots__ = ()

    # -- public API -------------------------------------------------------

    def evaluate(
        self,
        message: str,
        intent: IntentResult,
        entities: EntityResult,
        session: SessionContext,
    ) -> LeadSignal:
        normalized = self._normalize(message)
        reasons: List[str] = []

        base_score, base_reasons = self._calculate_base_score(normalized, intent)
        reasons.extend(base_reasons)

        entity_bonus, entity_reasons = self._apply_entity_bonus(entities)
        reasons.extend(entity_reasons)

        session_bonus, session_reasons = self._apply_session_bonus(session)
        reasons.extend(session_reasons)

        score = base_score + entity_bonus + session_bonus

        callback_requested, callback_hits = self._detect_callback_request(normalized)
        recommendation_detected, recommendation_hits = self._detect_recommendation_intent(normalized)
        admission_ready, admission_hits = self._detect_admission_ready(normalized)

        if callback_hits:
            reasons.append(f"explicit callback request detected: {', '.join(callback_hits)}")
        if recommendation_hits:
            reasons.append(f"decision-seeker / recommendation language detected: {', '.join(recommendation_hits)}")
        if admission_hits:
            reasons.append(f"admission-ready signal detected: {', '.join(admission_hits)}")

        # Floors: an explicit business signal must never be undercut by a
        # low raw score (e.g. a very short "call me" message).
        if recommendation_detected and score < _RECOMMENDATION_FLOOR:
            reasons.append(f"score floored to {_RECOMMENDATION_FLOOR} due to recommendation intent")
            score = _RECOMMENDATION_FLOOR
        if admission_ready and score < _ADMISSION_READY_FLOOR:
            reasons.append(f"score floored to {_ADMISSION_READY_FLOOR} due to admission-ready signal")
            score = _ADMISSION_READY_FLOOR
        if callback_requested and score < _CALLBACK_FLOOR:
            reasons.append(f"score floored to {_CALLBACK_FLOOR} due to explicit callback request")
            score = _CALLBACK_FLOOR

        score = max(0, min(100, score))

        level = self._determine_level(score)
        action = self._determine_action(
            level=level,
            callback_requested=callback_requested,
            recommendation_detected=recommendation_detected,
            admission_ready=admission_ready,
        )

        reasons.append(f"final: score={score} level={level.value} action={action.value}")

        return LeadSignal(
            score=score,
            level=level,
            action=action,
            should_start_funnel=action is LeadAction.START_FUNNEL,
            should_offer_callback=action in (LeadAction.OFFER_CALLBACK, LeadAction.URGENT_COUNSELLOR),
            should_capture_lead=action in (LeadAction.CAPTURE_LEAD, LeadAction.URGENT_COUNSELLOR)
            or callback_requested,
            should_escalate_to_counsellor=action is LeadAction.URGENT_COUNSELLOR,
            reasons=reasons,
        )

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _normalize(message: str) -> str:
        """Lower-case, trim, and collapse internal whitespace. Mirrors
        intent.py's normalization so pattern matching behaves identically
        across both stages."""
        if not message:
            return ""
        text = message.strip().lower()
        text = _WHITESPACE_RE.sub(" ", text)
        return text

    def _calculate_base_score(
        self, normalized_message: str, intent: IntentResult
    ) -> Tuple[int, List[str]]:
        """Blend intent.py's own upstream lead_score with this file's
        message-level keyword scoring. Neither signal is treated as
        authoritative on its own: intent.py sees only the message; this
        method adds its own independent read before entity/session
        context is layered on top."""
        reasons: List[str] = []

        high_hits = [s for c, s in zip(_COMPILED_HIGH, HIGH_INTENT_PATTERNS) if c.search(normalized_message)]
        medium_hits = [s for c, s in zip(_COMPILED_MEDIUM, MEDIUM_INTENT_PATTERNS) if c.search(normalized_message)]
        low_hits = [s for c, s in zip(_COMPILED_LOW, LOW_INTENT_PATTERNS) if c.search(normalized_message)]
        recommendation_hits = [
            s for c, s in zip(_COMPILED_RECOMMENDATION, RECOMMENDATION_PATTERNS) if c.search(normalized_message)
        ]

        pattern_score = 0
        pattern_score += len(high_hits) * 12
        pattern_score += len(medium_hits) * 6
        pattern_score -= len(low_hits) * 10
        pattern_score += len(recommendation_hits) * 18
        pattern_score = max(0, min(100, pattern_score))

        if high_hits:
            reasons.append(f"high-intent keywords matched (+{len(high_hits) * 12}): {', '.join(high_hits)}")
        if medium_hits:
            reasons.append(f"medium-intent keywords matched (+{len(medium_hits) * 6}): {', '.join(medium_hits)}")
        if low_hits:
            reasons.append(f"low-intent/definitional keywords matched (-{len(low_hits) * 10}): {', '.join(low_hits)}")
        if recommendation_hits:
            reasons.append(
                f"recommendation-seeking language matched (+{len(recommendation_hits) * 18}): "
                f"{', '.join(recommendation_hits)}"
            )

        upstream_score = max(0, min(100, getattr(intent, "lead_score", 0)))
        blended = round(0.5 * upstream_score + 0.5 * pattern_score)
        reasons.append(
            f"blended upstream intent.lead_score ({upstream_score}) with message-pattern "
            f"score ({pattern_score}) -> base {blended}"
        )

        return blended, reasons

    def _apply_entity_bonus(self, entities: EntityResult) -> Tuple[int, List[str]]:
        """Users discussing specific programs convert better than users
        asking generic questions, so resolved entities push the score up."""
        bonus = 0
        reasons: List[str] = []

        if entities.universities:
            bonus += 10
            reasons.append(f"university entity resolved ({', '.join(entities.universities)}): +10")
        if entities.courses:
            bonus += 15
            reasons.append(f"course entity resolved ({', '.join(entities.courses)}): +15")
        if entities.specializations:
            bonus += 10
            reasons.append(f"specialization entity resolved ({', '.join(entities.specializations)}): +10")

        return bonus, reasons

    def _apply_session_bonus(self, session: SessionContext) -> Tuple[int, List[str]]:
        """Users who have already shared profile details (program interest,
        budget, working status) are deeper in the funnel than a first-turn
        visitor, regardless of what this specific message says."""
        bonus = 0
        reasons: List[str] = []
        profile = session.profile_context or {}

        if profile.get("desired_program"):
            bonus += 5
            reasons.append("session profile has desired_program: +5")
        if profile.get("budget"):
            bonus += 5
            reasons.append("session profile has budget: +5")
        if profile.get("working_status"):
            bonus += 5
            reasons.append("session profile has working_status: +5")

        return bonus, reasons

    def _detect_callback_request(self, normalized_message: str) -> Tuple[bool, List[str]]:
        hits = [s for c, s in zip(_COMPILED_CALLBACK, CALLBACK_PATTERNS) if c.search(normalized_message)]
        return bool(hits), hits

    def _detect_recommendation_intent(self, normalized_message: str) -> Tuple[bool, List[str]]:
        hits = [
            s for c, s in zip(_COMPILED_RECOMMENDATION, RECOMMENDATION_PATTERNS) if c.search(normalized_message)
        ]
        return bool(hits), hits

    def _detect_admission_ready(self, normalized_message: str) -> Tuple[bool, List[str]]:
        hits = [s for c, s in zip(_COMPILED_ADMISSION, ADMISSION_PATTERNS) if c.search(normalized_message)]
        return bool(hits), hits

    def _determine_level(self, score: int) -> LeadLevel:
        for low, high, level in _LEVEL_BANDS:
            if low <= score <= high:
                return level
        return LeadLevel.LOW  # unreachable given the 0-100 clamp, kept for safety

    def _determine_action(
        self,
        level: LeadLevel,
        callback_requested: bool,
        recommendation_detected: bool,
        admission_ready: bool,
    ) -> LeadAction:
        # Priority order encodes business value: an explicit ask for a human
        # always wins, then admission-readiness, then a qualification-flow
        # trigger, then a generic level-based default.
        if callback_requested:
            return LeadAction.CAPTURE_LEAD

        if admission_ready:
            return LeadAction.URGENT_COUNSELLOR if level is LeadLevel.HOT else LeadAction.OFFER_CALLBACK

        if recommendation_detected:
            return LeadAction.START_FUNNEL

        if level is LeadLevel.HOT:
            return LeadAction.OFFER_CALLBACK
        if level in (LeadLevel.HIGH, LeadLevel.MEDIUM):
            return LeadAction.SHOW_CTA
        return LeadAction.NONE


# =============================================================================
# TESTS / DEMO
# =============================================================================

if __name__ == "__main__":
    try:
        from intent import IntentClassifier  # type: ignore

        _classifier: Optional["IntentClassifier"] = IntentClassifier()
    except ImportError:  # pragma: no cover
        _classifier = None

    def _fake_intent_result(message: str) -> IntentResult:
        """Used only if intent.py is not importable, so this file can still
        run standalone for a quick sanity check."""
        return IntentResult(
            intent="UNKNOWN",  # type: ignore[arg-type]
            confidence=0.5,
            route_type="UNKNOWN",  # type: ignore[arg-type]
            lead_score=20,
            lead_priority=LeadPriority.LOW,
        )

    detector = LeadDetector()

    samples: List[Tuple[str, EntityResult, SessionContext]] = [
        ("NMIMS MBA fees", EntityResult(universities=["nmims"]), SessionContext()),
        ("Which MBA should I choose?", EntityResult(), SessionContext()),
        ("Call me", EntityResult(), SessionContext()),
        ("Need admission guidance", EntityResult(), SessionContext()),
        (
            "NMIMS admission process",
            EntityResult(universities=["nmims"]),
            SessionContext(profile_context={"desired_program": "MBA", "budget": "2-4L"}),
        ),
        ("What is MBA?", EntityResult(), SessionContext()),
    ]

    for message, entities, session in samples:
        intent_result = _classifier.classify(message) if _classifier else _fake_intent_result(message)
        signal = detector.evaluate(message, intent_result, entities, session)

        print(f"Message:                    {message!r}")
        print(f"  score:                     {signal.score}")
        print(f"  level:                     {signal.level.value}")
        print(f"  action:                    {signal.action.value}")
        print(f"  should_start_funnel:       {signal.should_start_funnel}")
        print(f"  should_offer_callback:     {signal.should_offer_callback}")
        print(f"  should_capture_lead:       {signal.should_capture_lead}")
        print(f"  should_escalate_to_counsellor: {signal.should_escalate_to_counsellor}")
        print("  reasons:")
        for reason in signal.reasons:
            print(f"    - {reason}")
        print("-" * 78)