"""
intent.py
=========

DegreeBaba — Rule-Based Intent Classifier
------------------------------------------

Stage 1 of the pipeline:

    User Message -> [Intent Classifier] -> Entity Resolver -> Decision Engine -> Route

This module is the FIRST, and ONLY the first, stage of that pipeline. It is a pure,
deterministic, pattern-matching engine with no side effects.

Hard constraints (do not violate these when editing this file):
    * No LLM calls.
    * No database calls.
    * No network calls.
    * No entity resolution (that is the next stage's job).
    * No use of prior session / conversation context.
    * Target execution time: < 5ms per call.

Business context:
    DegreeBaba is an online university admission & counselling platform (think
    CarDekho / PolicyBazaar, but for higher education). The chatbot's job is NOT
    to reason about everything with an LLM — it is to:
        1. Build trust
        2. Qualify the user
        3. Capture leads
        4. Route qualified leads to human counsellors
    Most questions can be answered directly from structured DB records once the
    entity (university / course / specialization) is known. This classifier's
    only job is to figure out *what* the user wants and *how hot a lead* they
    are — never *who* they are asking about.

Editing patterns:
    Everything a business/growth team would want to tune lives in the
    ALL-CAPS pattern tables near the top of the file (INTENT_PATTERNS,
    FOLLOWUP_PATTERNS, HIGH_INTENT_PATTERNS, MEDIUM_INTENT_PATTERNS,
    LOW_INTENT_PATTERNS). Adding/removing a keyword there does not require
    touching any classifier logic below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Pattern, Tuple


# =============================================================================
# ENUMS
# =============================================================================


class Intent(Enum):
    """The complete, closed set of intents this classifier can produce."""

    # --- Factual / DB-lookup intents -----------------------------------
    OVERVIEW = "OVERVIEW"
    FEES = "FEES"
    ELIGIBILITY = "ELIGIBILITY"
    PROGRAMS = "PROGRAMS"
    SPECIALIZATIONS = "SPECIALIZATIONS"
    PLACEMENTS = "PLACEMENTS"
    FACULTY = "FACULTY"
    ACCREDITATION = "ACCREDITATION"
    REVIEWS = "REVIEWS"
    FAQS = "FAQS"
    ADMISSION = "ADMISSION"

    # --- Lead funnel intents ---------------------------------------------
    RECOMMENDATION = "RECOMMENDATION"
    CAREER_GUIDANCE = "CAREER_GUIDANCE"
    LEAD_CAPTURE = "LEAD_CAPTURE"

    # --- Other -------------------------------------------------------------
    COMPARISON = "COMPARISON"
    KNOWLEDGE = "KNOWLEDGE"
    UNKNOWN = "UNKNOWN"


class RouteType(Enum):
    FACTUAL = "FACTUAL"
    LEAD_FUNNEL = "LEAD_FUNNEL"
    ADVISORY = "ADVISORY"
    COMPARISON = "COMPARISON"
    KNOWLEDGE = "KNOWLEDGE"
    UNKNOWN = "UNKNOWN"


class LeadPriority(Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# RESULT OBJECT
# =============================================================================


@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    route_type: RouteType
    is_follow_up: bool
    requires_entity: bool
    is_lead_intent: bool
    lead_priority: LeadPriority
    lead_score: int
    matched_patterns: List[str] = field(default_factory=list)


# =============================================================================
# CONFIGURATION — business team edits these tables only
# =============================================================================
#
# Pattern conventions:
#   * All patterns are matched against a lower-cased, whitespace-normalized
#     version of the user message.
#   * Patterns are plain regular expressions. Use \b for word boundaries on
#     single tokens. Multi-word phrases should use \s+ between words so
#     variable spacing still matches.
#   * Order within a list does not matter — all patterns for an intent are
#     tried and their hits are summed into a score.

INTENT_PATTERNS: Dict[Intent, List[str]] = {
    Intent.OVERVIEW: [
        r"\btell\s+me\s+about\b",
        r"\bwhat\s+is\b(?!\s+mba|\s+bba|\s+bca|\s+distance\s+learning|\s+online\s+education)",
        r"\boverview\b",
        r"\babout\b",
        r"\bdetails\s+of\b",
        r"\binfo(?:rmation)?\s+about\b",
    ],
    Intent.FEES: [
        r"\bfees?\b",
        r"\bfee\s+structure\b",
        r"\bcost\b",
        r"\bprice\b",
        r"\btuition\b",
        r"\bhow\s+much\s+does\s+it\s+cost\b",
    ],
    Intent.ELIGIBILITY: [
        r"\beligib\w*\b",
        r"\brequirements?\b",
        r"\bcriteria\b",
        r"\bcan\s+i\s+apply\b",
        r"\bam\s+i\s+eligible\b",
        r"\bqualif\w*\b",
    ],
    Intent.PROGRAMS: [
        r"\bcourses?\b",
        r"\bprograms?\b",
        r"\bdegrees?\b",
        r"\bavailable\s+courses\b",
    ],
    Intent.SPECIALIZATIONS: [
        r"\bspeciali[sz]ations?\b",
        r"\bmarketing\s+mba\b",
        r"\bfinance\s+mba\b",
        r"\bhr\s+mba\b",
        r"\bstreams?\b",
        r"\bmajors?\b",
    ],
    Intent.PLACEMENTS: [
        r"\bplacements?\b",
        r"\bjobs?\b",
        r"\bsalary\b",
        r"\bcareer\s+opportunit\w*\b",
        r"\bpackages?\b",
        r"\bctc\b",
        r"\bhiring\b",
    ],
    Intent.FACULTY: [
        r"\bfaculty\b",
        r"\bteachers?\b",
        r"\bprofessors?\b",
        r"\bmentors?\b",
        r"\bdean\b",
        r"\binstructors?\b",
    ],
    Intent.ACCREDITATION: [
        r"\bugc\b",
        r"\bnaac\b",
        r"\bapproved\b",
        r"\bapproval\b",
        r"\brecogni[sz]ed\b",
        r"\baccreditation\b",
        r"\baicte\b",
    ],
    Intent.REVIEWS: [
        r"\breviews?\b",
        r"\bstudent\s+reviews?\b",
        r"\bratings?\b",
        r"\bfeedback\b",
        r"\bexperience\s+of\s+students\b",
    ],
    Intent.FAQS: [
        r"\bfaqs?\b",
        r"\bcommon\s+questions\b",
        r"\bfrequently\s+asked\b",
    ],
    Intent.ADMISSION: [
        r"\badmissions?\b",
        r"\bapply\b",
        r"\bapplication\b",
        r"\benrol+\b",
        r"\bregistration\b",
        r"\blast\s+date\b",
        r"\bdeadline\b",
        r"\bhow\s+to\s+join\b",
    ],
    Intent.RECOMMENDATION: [
        r"\bwhich\s+mba\s+should\s+i\s+choose\b",
        r"\bbest\s+mba\b",
        r"\bbest\s+university\b",
        r"\bsuggest\s+(?:a\s+)?university\b",
        r"\bhelp\s+me\s+choose\b",
        r"\bi\s+am\s+confused\b",
        r"\bi'?m\s+confused\b",
        r"\bneed\s+guidance\b",
        r"\bwhich\s+university\s+is\s+best\b",
        r"\brecommend\b",
        r"\bsuggest\s+(?:me\s+)?(?:a\s+)?(?:course|program|university|college)\b",
    ],
    Intent.CAREER_GUIDANCE: [
        r"\bwhich\s+speciali[sz]ation\s+should\s+i\s+take\b",
        r"\bfuture\s+scope\b",
        r"\bcareer\s+advice\b",
        r"\bwhich\s+course\s+is\s+best\s+for\s+me\b",
        r"\bwhat\s+should\s+i\s+study\b",
        r"\bcareer\s+guidance\b",
        r"\bcareer\s+path\b",
    ],
    Intent.LEAD_CAPTURE: [
        r"\bcall\s+me\b",
        r"\bcallback\b",
        r"\bcall\s+back\b",
        r"\btalk\s+to\s+(?:a\s+)?counsel?lor\b",
        r"\bcontact\s+me\b",
        r"\bneed\s+(?:a\s+)?counsel?lor\b",
        r"\badvisor\s+call\b",
        r"\bconnect\s+me\s+with\b",
        r"\bschedule\s+a\s+call\b",
    ],
    Intent.COMPARISON: [
        r"\bvs\b",
        r"\bversus\b",
        r"\bcompare\b",
        r"\bcomparison\b",
        r"\bwhich\s+is\s+better\b",
        r"\bdifference\s+between\b",
        r"\bor\b.{0,30}\bbetter\b",
    ],
    Intent.KNOWLEDGE: [
        r"\bwhat\s+is\s+mba\b",
        r"\bwhat\s+is\s+bba\b",
        r"\bwhat\s+is\s+bca\b",
        r"\bwhat\s+is\s+online\s+education\b",
        r"\bwhat\s+is\s+distance\s+learning\b",
        r"\bdistance\s+learning\b",
        r"\bonline\s+education\b",
        r"\bwhat\s+does\s+\w+\s+mean\b",
    ],
}

FOLLOWUP_PATTERNS: List[str] = [
    r"^what\s+about\b",
    r"^and\s+\w+",
    r"\btell\s+me\s+more\b",
    r"^what\s+else\b",
    r"^also\b",
    r"^hmm\s+what\s+about\b",
    r"^ok(?:ay)?\s+what\s+about\b",
]

HIGH_INTENT_PATTERNS: List[str] = [
    r"\bapply\b",
    r"\badmission\b",
    r"\bcallback\b",
    r"\bcall\s+back\b",
    r"\bcall\s+me\b",
    r"\bphone\b",
    r"\bcontact\b",
    r"\bcounsel?lor\b",
    r"\badvisor\b",
    r"\blast\s+date\b",
    r"\bscholarship\b",
    r"\bregistration\b",
    r"\bdeadline\b",
]

MEDIUM_INTENT_PATTERNS: List[str] = [
    r"\bfees?\b",
    r"\beligib\w*\b",
    r"\bplacements?\b",
    r"\breviews?\b",
    r"\bcompar\w*\b",
    r"\bvs\b",
]

LOW_INTENT_PATTERNS: List[str] = [
    r"\bwhat\s+is\s+mba\b",
    r"\bwhat\s+is\s+bba\b",
    r"\bwhat\s+is\s+bca\b",
    r"\bwhat\s+is\s+distance\s+learning\b",
    r"\bwhat\s+is\s+online\s+education\b",
]


# =============================================================================
# DERIVED / STATIC MAPPINGS (logic, not business config — leave alone)
# =============================================================================

INTENT_ROUTE_MAP: Dict[Intent, RouteType] = {
    Intent.OVERVIEW: RouteType.FACTUAL,
    Intent.FEES: RouteType.FACTUAL,
    Intent.ELIGIBILITY: RouteType.FACTUAL,
    Intent.PROGRAMS: RouteType.FACTUAL,
    Intent.SPECIALIZATIONS: RouteType.FACTUAL,
    Intent.PLACEMENTS: RouteType.FACTUAL,
    Intent.FACULTY: RouteType.FACTUAL,
    Intent.ACCREDITATION: RouteType.FACTUAL,
    Intent.REVIEWS: RouteType.FACTUAL,
    Intent.FAQS: RouteType.FACTUAL,
    Intent.ADMISSION: RouteType.FACTUAL,
    Intent.RECOMMENDATION: RouteType.LEAD_FUNNEL,
    Intent.CAREER_GUIDANCE: RouteType.LEAD_FUNNEL,
    Intent.LEAD_CAPTURE: RouteType.LEAD_FUNNEL,
    Intent.COMPARISON: RouteType.COMPARISON,
    Intent.KNOWLEDGE: RouteType.KNOWLEDGE,
    Intent.UNKNOWN: RouteType.UNKNOWN,
}

INTENT_LEAD_PRIORITY: Dict[Intent, LeadPriority] = {
    Intent.LEAD_CAPTURE: LeadPriority.HIGH,
    Intent.ADMISSION: LeadPriority.HIGH,
    Intent.RECOMMENDATION: LeadPriority.MEDIUM,
    Intent.CAREER_GUIDANCE: LeadPriority.MEDIUM,
    Intent.COMPARISON: LeadPriority.MEDIUM,
    Intent.FEES: LeadPriority.MEDIUM,
    Intent.ELIGIBILITY: LeadPriority.MEDIUM,
    Intent.PLACEMENTS: LeadPriority.MEDIUM,
    Intent.REVIEWS: LeadPriority.LOW,
    Intent.PROGRAMS: LeadPriority.LOW,
    Intent.SPECIALIZATIONS: LeadPriority.LOW,
    Intent.FACULTY: LeadPriority.LOW,
    Intent.ACCREDITATION: LeadPriority.LOW,
    Intent.FAQS: LeadPriority.LOW,
    Intent.OVERVIEW: LeadPriority.LOW,
    Intent.KNOWLEDGE: LeadPriority.NONE,
    Intent.UNKNOWN: LeadPriority.NONE,
}

# Base lead score awarded purely by which intent fired, before keyword signal
# adjustments. Tuned so HIGH-priority intents sit in the "hot lead" band,
# MEDIUM in "warm", LOW in "cold-but-engaged", NONE near the floor.
_BASE_SCORE_BY_PRIORITY: Dict[LeadPriority, int] = {
    LeadPriority.HIGH: 80,
    LeadPriority.MEDIUM: 50,
    LeadPriority.LOW: 25,
    LeadPriority.NONE: 8,
}

# Tie-break order when two intents score equally on pattern hits. Earlier
# entries win. This encodes business priority: a lead-capture / admission
# signal should never lose out to a generic factual keyword collision.
_INTENT_PRIORITY_ORDER: Tuple[Intent, ...] = (
    Intent.LEAD_CAPTURE,
    Intent.ADMISSION,
    Intent.COMPARISON,
    Intent.RECOMMENDATION,
    Intent.CAREER_GUIDANCE,
    Intent.FEES,
    Intent.ELIGIBILITY,
    Intent.PLACEMENTS,
    Intent.ACCREDITATION,
    Intent.REVIEWS,
    Intent.FACULTY,
    Intent.FAQS,
    Intent.PROGRAMS,
    Intent.SPECIALIZATIONS,
    Intent.OVERVIEW,
    Intent.KNOWLEDGE,
    Intent.UNKNOWN,
)

# Route types for which the Entity Resolver stage downstream will need a
# university / course / specialization to be identified. COMPARISON needs
# (at least) two entities; FACTUAL needs at least one. Lead-funnel / advisory
# conversation, and generic KNOWLEDGE definitions, do not depend on an entity.
_ENTITY_REQUIRED_ROUTES = frozenset({RouteType.FACTUAL, RouteType.COMPARISON})


def _compile(patterns: List[str]) -> List[Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _compile_map(mapping: Dict[Intent, List[str]]) -> Dict[Intent, List[Pattern[str]]]:
    return {intent: _compile(patterns) for intent, patterns in mapping.items()}


# Compiled once at import time so `classify()` never pays regex-compilation
# cost at request time (keeps us well under the 5ms budget).
_COMPILED_INTENT_PATTERNS: Dict[Intent, List[Pattern[str]]] = _compile_map(INTENT_PATTERNS)
_COMPILED_FOLLOWUP_PATTERNS: List[Pattern[str]] = _compile(FOLLOWUP_PATTERNS)
_COMPILED_HIGH_PATTERNS: List[Pattern[str]] = _compile(HIGH_INTENT_PATTERNS)
_COMPILED_MEDIUM_PATTERNS: List[Pattern[str]] = _compile(MEDIUM_INTENT_PATTERNS)
_COMPILED_LOW_PATTERNS: List[Pattern[str]] = _compile(LOW_INTENT_PATTERNS)

_WHITESPACE_RE = re.compile(r"\s+")


# =============================================================================
# CLASSIFIER
# =============================================================================


class IntentClassifier:
    """
    Deterministic, rule-based intent classifier for DegreeBaba.

    This class deliberately does not:
        * call an LLM
        * call a database
        * resolve which university/course the user means
        * remember anything about previous turns in the conversation

    It only answers: "given this single message, what does the user want,
    and how strong a lead signal is it?"
    """

    __slots__ = ()

    # -- public API -----------------------------------------------------

    def classify(self, message: str) -> IntentResult:
        normalized = self._normalize(message)

        if not normalized:
            return IntentResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                route_type=RouteType.UNKNOWN,
                is_follow_up=False,
                requires_entity=False,
                is_lead_intent=False,
                lead_priority=LeadPriority.NONE,
                lead_score=0,
                matched_patterns=[],
            )

        is_follow_up, followup_hits = self._detect_follow_up(normalized)

        intent, confidence, intent_hits = self._match_intent(normalized)

        route_type = INTENT_ROUTE_MAP[intent]
        requires_entity = route_type in _ENTITY_REQUIRED_ROUTES
        lead_priority = INTENT_LEAD_PRIORITY[intent]
        is_lead_intent = lead_priority is not LeadPriority.NONE

        lead_score, signal_hits = self._score_lead(normalized, lead_priority)

        matched_patterns = (
            [f"intent:{p}" for p in intent_hits]
            + [f"followup:{p}" for p in followup_hits]
            + [f"signal:{p}" for p in signal_hits]
        )

        return IntentResult(
            intent=intent,
            confidence=confidence,
            route_type=route_type,
            is_follow_up=is_follow_up,
            requires_entity=requires_entity,
            is_lead_intent=is_lead_intent,
            lead_priority=lead_priority,
            lead_score=lead_score,
            matched_patterns=matched_patterns,
        )

    # -- internal helpers -------------------------------------------------

    @staticmethod
    def _normalize(message: str) -> str:
        """Lower-case, trim, and collapse internal whitespace. No unicode
        normalization or stemming is performed — this stage is intentionally
        cheap and mechanical."""
        if not message:
            return ""
        text = message.strip().lower()
        text = _WHITESPACE_RE.sub(" ", text)
        return text

    @staticmethod
    def _pattern_weight(pattern_source: str) -> int:
        """Multi-word phrase patterns are more specific / intentional than a
        single bare keyword, so they count for more when scoring which
        intent 'wins'."""
        # Rough heuristic: count literal word-ish tokens in the pattern source.
        word_tokens = re.findall(r"[a-z]+", pattern_source)
        return 2 if len(word_tokens) > 1 else 1

    def _match_intent(self, text: str) -> Tuple[Intent, float, List[str]]:
        best_intent = Intent.UNKNOWN
        best_score = 0
        best_hits: List[str] = []

        # Rank by explicit business priority so ties resolve predictably
        # (design rule: explicit / higher business-value message wins).
        for intent in _INTENT_PRIORITY_ORDER:
            patterns = _COMPILED_INTENT_PATTERNS.get(intent)
            if not patterns:
                continue

            score = 0
            hits: List[str] = []
            for compiled, source in zip(patterns, INTENT_PATTERNS[intent]):
                if compiled.search(text):
                    score += self._pattern_weight(source)
                    hits.append(source)

            if score > best_score:
                best_score = score
                best_intent = intent
                best_hits = hits
            # NOTE: if score == best_score > 0 we keep the earlier (higher
            # priority) intent found via _INTENT_PRIORITY_ORDER — this is
            # what implements "multiple matches -> highest-confidence /
            # highest-priority intent wins".

        if best_score == 0:
            return Intent.UNKNOWN, 0.15, []

        confidence = min(0.98, 0.5 + best_score * 0.12)
        return best_intent, round(confidence, 2), best_hits

    def _detect_follow_up(self, text: str) -> Tuple[bool, List[str]]:
        hits = [
            source
            for compiled, source in zip(_COMPILED_FOLLOWUP_PATTERNS, FOLLOWUP_PATTERNS)
            if compiled.search(text)
        ]
        return (bool(hits), hits)

    def _score_lead(self, text: str, priority: LeadPriority) -> Tuple[int, List[str]]:
        base = _BASE_SCORE_BY_PRIORITY[priority]

        high_hits = [s for c, s in zip(_COMPILED_HIGH_PATTERNS, HIGH_INTENT_PATTERNS) if c.search(text)]
        medium_hits = [s for c, s in zip(_COMPILED_MEDIUM_PATTERNS, MEDIUM_INTENT_PATTERNS) if c.search(text)]
        low_hits = [s for c, s in zip(_COMPILED_LOW_PATTERNS, LOW_INTENT_PATTERNS) if c.search(text)]

        score = base + (len(high_hits) * 10) + (len(medium_hits) * 5) - (len(low_hits) * 8)
        score = max(0, min(100, score))

        return score, (high_hits + medium_hits + low_hits)


# =============================================================================
# TESTS / DEMO
# =============================================================================

if __name__ == "__main__":
    classifier = IntentClassifier()

    samples = [
        "NMIMS MBA fees",
        "Which MBA should I choose?",
        "Talk to a counsellor",
        "NMIMS vs Amity",
        "What is MBA?",
        "What about eligibility?",
    ]

    for sample in samples:
        result = classifier.classify(sample)
        print(f"Message:            {sample!r}")
        print(f"  intent:            {result.intent.value}")
        print(f"  confidence:        {result.confidence}")
        print(f"  route_type:        {result.route_type.value}")
        print(f"  is_follow_up:      {result.is_follow_up}")
        print(f"  requires_entity:   {result.requires_entity}")
        print(f"  is_lead_intent:    {result.is_lead_intent}")
        print(f"  lead_priority:     {result.lead_priority.value}")
        print(f"  lead_score:        {result.lead_score}")
        print(f"  matched_patterns:  {result.matched_patterns}")
        print("-" * 70)