"""
decision_engine.py
==================

DegreeBaba — Decision Engine
-----------------------------

Stage 3 of the pipeline:

    User Message -> Intent Classifier -> Entity Resolver -> [Decision Engine] -> Route

The Decision Engine is the central business brain. Given what the user asked
(IntentResult), what entities were resolved for this turn (EntityResult), and
what the session already knows about this user (SessionContext), it decides:

    * Should we answer directly (deterministic DB lookup) or hand off to an LLM?
    * Should we start, continue, or skip the lead-qualification funnel?
    * Should we ask a qualification question, or ask for a callback?
    * How hot a lead is this, right now?

It does NOT generate any text, prompts, or UI. It returns one RouteDecision —
a pure business decision — and nothing else.

Hard constraints (do not violate these when editing this file):
    * No LLM calls.
    * No database calls.
    * No network calls.
    * No entity resolution — that already happened upstream (resolve.py).
    * Deterministic: same inputs -> same output, every time.

On IntentResult / Intent / RouteType:
    This module imports `Intent`, `IntentResult`, and `RouteType` directly
    from `intent.py` (the classifier built earlier in this pipeline) rather
    than redefining a parallel, string-typed copy of them. That is
    deliberate: importing the real types means this file can never silently
    drift out of sync with what the classifier actually produces, and lets
    every intent comparison below be checked by the type checker instead of
    relying on string literals.

    `intent.py` also defines its own `LeadPriority` (NONE/LOW/MEDIUM/HIGH).
    This module needs a *different*, three-value `LeadPriority` (LOW/MEDIUM/
    HIGH — no NONE, since the Decision Engine always renders *some* priority
    for routing purposes). To avoid a name collision, the classifier's enum
    is imported under an alias (`ClassifierLeadPriority`) and used as one of
    several signals feeding `DecisionEngine._calculate_priority`.

On EntityResult / SessionContext:
    Per the brief, these already exist elsewhere in the real system (the
    Entity Resolver / `resolve.py`, and the session-context layer). They are
    mirrored here as plain dataclasses with the exact shape described, so
    this module is self-contained and independently testable. In the real
    codebase, replace these two class definitions with:
        from resolve import EntityResult
        from session import SessionContext
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from intent import Intent, IntentResult, RouteType
from intent import LeadPriority as ClassifierLeadPriority


# =============================================================================
# ENUMS
# =============================================================================


class DecisionRoute(Enum):
    FACTUAL = "FACTUAL"
    LEAD_FUNNEL = "LEAD_FUNNEL"
    COMPARISON = "COMPARISON"
    ADVISORY = "ADVISORY"
    KNOWLEDGE = "KNOWLEDGE"
    UNKNOWN = "UNKNOWN"


class FunnelStage(Enum):
    NONE = "NONE"
    PROGRAM = "PROGRAM"
    QUALIFICATION = "QUALIFICATION"
    BUDGET = "BUDGET"
    WORK_STATUS = "WORK_STATUS"
    SPECIALIZATION = "SPECIALIZATION"
    TIMELINE = "TIMELINE"
    SHORTLIST = "SHORTLIST"
    CALLBACK = "CALLBACK"
    CAPTURE = "CAPTURE"


class LeadPriority(Enum):
    """Decision Engine's own priority tier. Deliberately has no NONE value —
    by the time a RouteDecision is produced, every conversation gets *some*
    priority so downstream systems always have a value to sort/act on."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# INPUT CONTRACTS
# (mirrors of dataclasses owned by other modules — see the module docstring
# for why these are defined locally here rather than imported)
# =============================================================================


@dataclass
class EntityResult:
    """Mirror of the real dataclass produced by the Entity Resolver
    (`resolve.py`). Replace with `from resolve import EntityResult` in the
    actual codebase."""

    universities: list[str]
    courses: list[str]
    specializations: list[str]
    confidence: float


@dataclass
class SessionContext:
    """Mirror of the real session-context dataclass. Replace with
    `from session import SessionContext` in the actual codebase.

    `profile_context` may contain: desired_program, budget, experience,
    working_status, specialization_interest, admission_timeline. Of these,
    only desired_program / budget / working_status / specialization_interest
    / admission_timeline are consulted by the funnel-stage logic below —
    `experience` is part of the broader profile shape but isn't gated on by
    this engine, since it isn't part of the qualification sequence the
    business rules define."""

    current_university_slug: str | None
    current_course_slug: str | None
    current_specialization_slug: str | None
    comparison_context: dict[str, Any]
    profile_context: dict[str, Any]


# =============================================================================
# OUTPUT CONTRACT
# =============================================================================


@dataclass
class RouteDecision:
    route: DecisionRoute
    deterministic_route: str | None
    start_funnel: bool
    continue_funnel: bool
    funnel_stage: FunnelStage
    ask_qualification_question: bool
    ask_callback: bool
    ask_contact_details: bool
    use_llm: bool
    use_deterministic_route: bool
    lead_priority: LeadPriority
    lead_score: int
    reason: str


# =============================================================================
# BUSINESS-TUNABLE CONFIGURATION
# Business/growth teams can edit these tables without touching any logic
# below. Keep the intents referenced here in sync with intent.py's Intent enum.
# =============================================================================

# Confidence below this floor means "don't trust this classification".
CONFIDENCE_FLOOR: float = 0.40

# Fresh entity-resolution confidence below this floor is treated as "not
# resolved" even if a candidate slug came back, to avoid guessing wrong.
ENTITY_CONFIDENCE_FLOOR: float = 0.50

# lead_score fallbacks used only when an intent isn't in one of the explicit
# priority sets below (belt-and-suspenders — see _calculate_priority).
SCORE_FLOOR_HIGH: int = 80
SCORE_FLOOR_MEDIUM: int = 45

# RULE 8 — these intents are always a HIGH-priority lead.
HIGH_LEAD_INTENTS: frozenset[Intent] = frozenset({
    Intent.ADMISSION,
    Intent.LEAD_CAPTURE,
})

# RULE 7 (plus comparison/recommendation/career guidance, which are
# inherently lead-funnel-adjacent) — at least a MEDIUM-priority lead.
MEDIUM_LEAD_INTENTS: frozenset[Intent] = frozenset({
    Intent.FEES,
    Intent.ELIGIBILITY,
    Intent.PLACEMENTS,
    Intent.REVIEWS,
    Intent.COMPARISON,
    Intent.RECOMMENDATION,
    Intent.CAREER_GUIDANCE,
})

# RULE 3 — intents that should resume an in-progress qualification funnel
# rather than restart it, on top of the low-confidence fallback below.
FUNNEL_CONTINUATION_INTENTS: frozenset[Intent] = frozenset({
    Intent.RECOMMENDATION,
    Intent.CAREER_GUIDANCE,
})

# RULE 4 / RULE 5 — deterministic (non-LLM) route names per intent. These are
# opaque strings handed to whatever downstream service executes the DB
# lookup; this engine never dereferences them itself.
DETERMINISTIC_ROUTE_MAP: dict[Intent, str] = {
    Intent.FEES: "ROUTE_FEE",
    Intent.ELIGIBILITY: "ROUTE_ELIGIBILITY",
    Intent.PLACEMENTS: "ROUTE_PLACEMENTS",
    Intent.REVIEWS: "ROUTE_REVIEWS",
    Intent.ACCREDITATION: "ROUTE_ACCREDITATION",
    Intent.SPECIALIZATIONS: "ROUTE_SPECIALIZATIONS",
    Intent.ADMISSION: "ROUTE_ADMISSION",
    # Filled in for full FACTUAL coverage — intent.py can legitimately emit
    # these too, and an unmapped FACTUAL intent would be a production bug.
    Intent.OVERVIEW: "ROUTE_OVERVIEW",
    Intent.PROGRAMS: "ROUTE_PROGRAMS",
    Intent.FACULTY: "ROUTE_FACULTY",
    Intent.FAQS: "ROUTE_FAQS",
    # Comparison is deterministic too (RULE 5), just not "FACTUAL".
    Intent.COMPARISON: "ROUTE_COMPARISON",
}

# RULE 9 / RULE 10 — required fields for a completed qualification, in the
# order they're asked. specialization_interest/admission_timeline are
# optional refinement signals: useful if volunteered, but not gating.
FUNNEL_REQUIRED_FIELDS: tuple[str, ...] = ("desired_program", "budget", "working_status")
FUNNEL_OPTIONAL_FIELDS: tuple[str, ...] = ("specialization_interest", "admission_timeline")
FUNNEL_FIELD_ORDER: tuple[str, ...] = FUNNEL_REQUIRED_FIELDS + FUNNEL_OPTIONAL_FIELDS

FIELD_TO_STAGE: dict[str, FunnelStage] = {
    "desired_program": FunnelStage.PROGRAM,
    "budget": FunnelStage.BUDGET,
    "working_status": FunnelStage.WORK_STATUS,
    "specialization_interest": FunnelStage.SPECIALIZATION,
    "admission_timeline": FunnelStage.TIMELINE,
}


# =============================================================================
# DECISION ENGINE
# =============================================================================


class DecisionEngine:
    """
    Deterministic business-rules engine for DegreeBaba.

    Converts (IntentResult, EntityResult, SessionContext) into a single
    RouteDecision. Contains no LLM calls, no DB calls, and no network calls —
    every decision is a pure function of its three inputs.
    """

    __slots__ = ()

    # -- public API ---------------------------------------------------------

    def decide(
        self,
        intent: IntentResult,
        entities: EntityResult,
        session: SessionContext,
    ) -> RouteDecision:
        profile: dict[str, Any] = session.profile_context or {}
        funnel_active = self._funnel_has_any_data(profile)
        funnel_complete = self._is_funnel_complete(profile)

        # RULE 1 — Lead capture always wins, unconditionally, before anything else.
        if intent.intent is Intent.LEAD_CAPTURE:
            return self._lead_capture_decision(intent)

        low_confidence = intent.confidence < CONFIDENCE_FLOOR

        # RULE 3 / RULE 9 — an in-progress funnel outranks a shaky
        # classification: a low-confidence reply ("50000", "yes") mid-funnel
        # is almost always the answer to our last qualification question (or
        # an explicit re-engagement with choosing/guidance) — not noise.
        # Don't restart what's already in progress.
        if funnel_active and not funnel_complete and (
            low_confidence or intent.intent in FUNNEL_CONTINUATION_INTENTS or intent.is_follow_up
        ):
            return self._funnel_progress_decision(
                intent, profile,
                reason="Continuing an in-progress qualification funnel rather than restarting it.",
            )

        # RULE 10 — already qualified (shortlist-ready): keep nudging toward
        # a callback even if this turn's message is itself ambiguous.
        if funnel_complete and (low_confidence or intent.intent in FUNNEL_CONTINUATION_INTENTS):
            return self._funnel_progress_decision(
                intent, profile,
                reason="Required profile fields are already collected — enough information for a counsellor callback.",
            )

        if low_confidence:
            return self._unknown_decision(
                intent,
                reason=f"Classifier confidence {intent.confidence:.2f} is below the {CONFIDENCE_FLOOR:.2f} floor.",
            )

        if intent.intent is Intent.RECOMMENDATION:
            return self._recommendation_start_decision(intent)

        if intent.intent is Intent.CAREER_GUIDANCE:
            return self._career_guidance_decision(intent)

        if intent.intent is Intent.COMPARISON:
            return self._comparison_decision(intent, entities, session, profile, funnel_complete)

        if intent.intent is Intent.KNOWLEDGE:
            return self._knowledge_decision(intent, profile, funnel_complete)

        if intent.route_type is RouteType.FACTUAL:
            return self._factual_decision(intent, entities, session, profile, funnel_complete)

        return self._unknown_decision(
            intent,
            reason=f"Intent '{intent.intent.value}' has no mapped business route.",
        )

    # -- rule-branch builders -------------------------------------------------

    def _lead_capture_decision(self, intent: IntentResult) -> RouteDecision:
        """RULE 1."""
        return RouteDecision(
            route=DecisionRoute.LEAD_FUNNEL,
            deterministic_route=None,
            start_funnel=True,
            continue_funnel=False,
            funnel_stage=FunnelStage.CALLBACK,
            ask_qualification_question=False,
            ask_callback=False,
            ask_contact_details=True,
            use_llm=False,
            use_deterministic_route=False,
            lead_priority=LeadPriority.HIGH,
            lead_score=max(intent.lead_score, 90),
            reason=(
                "Explicit callback/counsellor request — highest-priority signal; "
                "bypass the funnel and capture contact details immediately."
            ),
        )

    def _recommendation_start_decision(self, intent: IntentResult) -> RouteDecision:
        """RULE 2 (fresh start — no funnel data yet)."""
        priority = self._calculate_priority(intent, funnel_complete=False)
        return RouteDecision(
            route=DecisionRoute.LEAD_FUNNEL,
            deterministic_route=None,
            start_funnel=True,
            continue_funnel=False,
            funnel_stage=FunnelStage.PROGRAM,
            ask_qualification_question=True,
            ask_callback=False,
            ask_contact_details=False,
            use_llm=False,
            use_deterministic_route=False,
            lead_priority=priority,
            lead_score=self._calculate_lead_score(intent, priority, funnel_complete=False),
            reason="Explicit 'help me choose / best option' request — start the qualification funnel from the top.",
        )

    def _career_guidance_decision(self, intent: IntentResult) -> RouteDecision:
        """Fresh CAREER_GUIDANCE: softer than RECOMMENDATION. Give a genuine
        advisory answer (use_llm=True) and invite qualification generically
        (FunnelStage.QUALIFICATION) rather than forcing the rigid, field-by-
        field funnel immediately — that only kicks in once the user commits
        via RECOMMENDATION or keeps engaging (see _funnel_progress_decision)."""
        priority = self._calculate_priority(intent, funnel_complete=False)
        return RouteDecision(
            route=DecisionRoute.ADVISORY,
            deterministic_route=None,
            start_funnel=False,
            continue_funnel=False,
            funnel_stage=FunnelStage.QUALIFICATION,
            ask_qualification_question=True,
            ask_callback=False,
            ask_contact_details=False,
            use_llm=True,
            use_deterministic_route=False,
            lead_priority=priority,
            lead_score=self._calculate_lead_score(intent, priority, funnel_complete=False),
            reason=(
                "Open-ended career/specialization guidance — give a genuinely helpful "
                "answer first, then softly invite qualification rather than forcing "
                "the rigid funnel immediately."
            ),
        )

    def _funnel_progress_decision(
        self, intent: IntentResult, profile: dict[str, Any], reason: str,
    ) -> RouteDecision:
        """RULE 3 / RULE 9 / RULE 10 — continue an already-started funnel:
        ask about the next missing required field, or move to SHORTLIST +
        ask_callback once all required fields are present."""
        complete = self._is_funnel_complete(profile)
        stage = FunnelStage.SHORTLIST if complete else self._get_funnel_stage(profile)
        priority = self._calculate_priority(intent, funnel_complete=complete)
        is_shortlist = stage is FunnelStage.SHORTLIST
        return RouteDecision(
            route=DecisionRoute.LEAD_FUNNEL,
            deterministic_route=None,
            start_funnel=False,
            continue_funnel=True,
            funnel_stage=stage,
            ask_qualification_question=not is_shortlist,
            ask_callback=is_shortlist,
            ask_contact_details=False,
            use_llm=False,
            use_deterministic_route=False,
            lead_priority=priority,
            lead_score=self._calculate_lead_score(intent, priority, funnel_complete=complete),
            reason=reason,
        )

    def _comparison_decision(
        self,
        intent: IntentResult,
        entities: EntityResult,
        session: SessionContext,
        profile: dict[str, Any],
        funnel_complete: bool,
    ) -> RouteDecision:
        """RULE 5."""
        priority = self._calculate_priority(intent, funnel_complete)
        entity_ok = self._has_sufficient_entity(intent, entities, session)
        funnel_active = self._funnel_has_any_data(profile)
        stage = self._get_funnel_stage(profile) if funnel_active else FunnelStage.NONE
        ask_callback = self._should_offer_callback(intent, priority, funnel_complete)
        lead_score = self._calculate_lead_score(intent, priority, funnel_complete)

        if not entity_ok:
            return RouteDecision(
                route=DecisionRoute.COMPARISON,
                deterministic_route=None,
                start_funnel=False,
                continue_funnel=funnel_active,
                funnel_stage=stage,
                ask_qualification_question=False,
                ask_callback=ask_callback,
                ask_contact_details=False,
                use_llm=True,
                use_deterministic_route=False,
                lead_priority=priority,
                lead_score=lead_score,
                reason=(
                    "Comparison intent detected but fewer than two universities/courses "
                    "are confidently resolved; falling back to an LLM-assisted clarifying "
                    "question to find out which two options to compare."
                ),
            )

        return RouteDecision(
            route=DecisionRoute.COMPARISON,
            deterministic_route=self._map_deterministic_route(intent.intent),
            start_funnel=False,
            continue_funnel=funnel_active,
            funnel_stage=stage,
            ask_qualification_question=False,
            ask_callback=ask_callback,
            ask_contact_details=False,
            use_llm=False,
            use_deterministic_route=True,
            lead_priority=priority,
            lead_score=lead_score,
            reason="Deterministic side-by-side comparison route; comparison shoppers are a warm lead signal.",
        )

    def _knowledge_decision(
        self, intent: IntentResult, profile: dict[str, Any], funnel_complete: bool,
    ) -> RouteDecision:
        """RULE 6."""
        priority = self._calculate_priority(intent, funnel_complete)
        funnel_active = self._funnel_has_any_data(profile)
        stage = self._get_funnel_stage(profile) if funnel_active else FunnelStage.NONE
        return RouteDecision(
            route=DecisionRoute.KNOWLEDGE,
            deterministic_route=None,
            start_funnel=False,
            continue_funnel=funnel_active,
            funnel_stage=stage,
            ask_qualification_question=False,
            ask_callback=self._should_offer_callback(intent, priority, funnel_complete),
            ask_contact_details=False,
            use_llm=True,
            use_deterministic_route=False,
            lead_priority=priority,
            lead_score=self._calculate_lead_score(intent, priority, funnel_complete),
            reason="Generic subject-matter definition — answered conversationally via LLM, not tied to a specific university.",
        )

    def _factual_decision(
        self,
        intent: IntentResult,
        entities: EntityResult,
        session: SessionContext,
        profile: dict[str, Any],
        funnel_complete: bool,
    ) -> RouteDecision:
        """RULE 4, with RULE 7 (medium-lead factual) / RULE 8 (high-lead
        factual, e.g. admission) folded into the shared priority/callback
        helpers so there's a single source of truth for both."""
        priority = self._calculate_priority(intent, funnel_complete)
        entity_ok = self._has_sufficient_entity(intent, entities, session)
        funnel_active = self._funnel_has_any_data(profile)
        stage = self._get_funnel_stage(profile) if funnel_active else FunnelStage.NONE
        ask_callback = self._should_offer_callback(intent, priority, funnel_complete)
        lead_score = self._calculate_lead_score(intent, priority, funnel_complete)
        deterministic_route = self._map_deterministic_route(intent.intent)

        if not entity_ok:
            return RouteDecision(
                route=DecisionRoute.FACTUAL,
                deterministic_route=None,
                start_funnel=False,
                continue_funnel=funnel_active,
                funnel_stage=stage,
                ask_qualification_question=False,
                ask_callback=ask_callback,
                ask_contact_details=False,
                use_llm=True,
                use_deterministic_route=False,
                lead_priority=priority,
                lead_score=lead_score,
                reason=(
                    f"{intent.intent.value} is a factual question but no university, course, "
                    "or specialization is resolved yet (neither this turn's entities nor the "
                    "session anchor); deferring to an LLM-assisted clarifying question rather "
                    "than guessing which entity to look up."
                ),
            )

        return RouteDecision(
            route=DecisionRoute.FACTUAL,
            deterministic_route=deterministic_route,
            start_funnel=False,
            continue_funnel=funnel_active,
            funnel_stage=stage,
            ask_qualification_question=False,
            ask_callback=ask_callback,
            ask_contact_details=False,
            use_llm=False,
            use_deterministic_route=True,
            lead_priority=priority,
            lead_score=lead_score,
            reason=f"Deterministic factual lookup for {intent.intent.value} via {deterministic_route}.",
        )

    def _unknown_decision(self, intent: IntentResult, reason: str) -> RouteDecision:
        return RouteDecision(
            route=DecisionRoute.UNKNOWN,
            deterministic_route=None,
            start_funnel=False,
            continue_funnel=False,
            funnel_stage=FunnelStage.NONE,
            ask_qualification_question=False,
            # A message we can't classify is still, per the platform's KPI
            # (qualified leads over questions answered), worth a gentle
            # human-assisted offer rather than silently failing.
            ask_callback=True,
            ask_contact_details=False,
            use_llm=False,
            use_deterministic_route=False,
            lead_priority=LeadPriority.LOW,
            lead_score=max(intent.lead_score, 20),
            reason=reason,
        )

    # -- required helper methods ----------------------------------------------

    def _get_funnel_stage(self, profile: dict[str, Any]) -> FunnelStage:
        """RULE 9 — walk the profile fields in collection order and return
        the stage for the first one that's still missing."""
        for field_name in FUNNEL_FIELD_ORDER:
            if not profile.get(field_name):
                return FIELD_TO_STAGE[field_name]
        return FunnelStage.SHORTLIST

    def _should_offer_callback(
        self, intent: IntentResult, priority: LeadPriority, funnel_complete: bool,
    ) -> bool:
        """RULE 7 / RULE 8 / RULE 10 — offer a callback for HIGH-priority
        moments or once the funnel is complete; stay quiet for MEDIUM/LOW so
        we don't nag someone who just asked a routine factual question."""
        if funnel_complete:
            return True
        return priority is LeadPriority.HIGH

    def _is_funnel_complete(self, profile: dict[str, Any]) -> bool:
        """RULE 10 — the funnel is 'complete' once the three required
        fields are present; specialization_interest/admission_timeline are
        optional refinements and don't gate this."""
        return all(bool(profile.get(f)) for f in FUNNEL_REQUIRED_FIELDS)

    def _map_deterministic_route(self, intent_value: Intent) -> str | None:
        """RULE 4 / RULE 5 — look up the deterministic route name for a
        given intent, or None if this intent has no deterministic route."""
        return DETERMINISTIC_ROUTE_MAP.get(intent_value)

    def _calculate_priority(self, intent: IntentResult, funnel_complete: bool) -> LeadPriority:
        """Combine the classifier's own signal (intent, lead_priority,
        lead_score, is_lead_intent) with session state (funnel_complete)
        into the Decision Engine's own three-tier priority."""
        if funnel_complete:
            return LeadPriority.HIGH
        if not intent.is_lead_intent:
            return LeadPriority.LOW
        if (
            intent.intent in HIGH_LEAD_INTENTS
            or intent.lead_priority is ClassifierLeadPriority.HIGH
            or intent.lead_score >= SCORE_FLOOR_HIGH
        ):
            return LeadPriority.HIGH
        if intent.intent in MEDIUM_LEAD_INTENTS or intent.lead_score >= SCORE_FLOOR_MEDIUM:
            return LeadPriority.MEDIUM
        return LeadPriority.LOW

    # -- additional private helpers --------------------------------------------

    def _calculate_lead_score(
        self, intent: IntentResult, priority: LeadPriority, funnel_complete: bool,
    ) -> int:
        """RULE 7 — 'increase lead score' after a medium-intent factual
        answer; also floors the score sensibly for HIGH priority / a
        completed funnel, without ever lowering a score the classifier
        already computed."""
        score = intent.lead_score
        if funnel_complete:
            score = max(score, 90)
        elif priority is LeadPriority.HIGH:
            score = max(score, 75)
        elif priority is LeadPriority.MEDIUM:
            score = max(score, 45) + 5
        return max(0, min(100, score))

    @staticmethod
    def _funnel_has_any_data(profile: dict[str, Any]) -> bool:
        return any(bool(profile.get(f)) for f in FUNNEL_FIELD_ORDER)

    def _has_sufficient_entity(
        self, intent: IntentResult, entities: EntityResult, session: SessionContext,
    ) -> bool:
        """Is there enough resolved entity information to actually run a
        deterministic DB lookup for this intent? Uses both this turn's
        freshly-resolved entities and the session's sticky entity anchor."""
        if not intent.requires_entity:
            return True

        fresh_count = len(entities.universities) + len(entities.courses) + len(entities.specializations)
        fresh_is_confident = fresh_count > 0 and entities.confidence >= ENTITY_CONFIDENCE_FLOOR
        has_session_anchor = bool(
            session.current_university_slug
            or session.current_course_slug
            or session.current_specialization_slug
        )

        if intent.intent is Intent.COMPARISON:
            return (fresh_count >= 2 and fresh_is_confident) or bool(session.comparison_context)

        return fresh_is_confident or has_session_anchor


# =============================================================================
# TESTS / DEMO
# =============================================================================

if __name__ == "__main__":
    from intent import IntentClassifier

    classifier = IntentClassifier()
    engine = DecisionEngine()

    empty_session = SessionContext(
        current_university_slug=None,
        current_course_slug=None,
        current_specialization_slug=None,
        comparison_context={},
        profile_context={},
    )
    no_entities = EntityResult(universities=[], courses=[], specializations=[], confidence=0.0)
    nmims_entities = EntityResult(universities=["nmims"], courses=["mba"], specializations=[], confidence=0.93)
    comparison_entities = EntityResult(universities=["nmims", "amity"], courses=[], specializations=[], confidence=0.9)

    scenarios: list[tuple[str, EntityResult, SessionContext]] = [
        ("NMIMS MBA fees", nmims_entities, empty_session),
        ("Which MBA should I choose?", no_entities, empty_session),
        ("Call me", no_entities, empty_session),
        ("NMIMS vs Amity", comparison_entities, empty_session),
        ("What is MBA?", no_entities, empty_session),
        ("Admission process for NMIMS", nmims_entities, empty_session),
    ]

    print("=" * 78)
    print("CORE SCENARIOS")
    print("=" * 78)
    for message, entities, session in scenarios:
        intent_result = classifier.classify(message)
        decision = engine.decide(intent_result, entities, session)
        print(f"Message:                {message!r}")
        print(f"  classified intent:    {intent_result.intent.value} (confidence={intent_result.confidence})")
        print(f"  route:                {decision.route.value}")
        print(f"  deterministic_route:  {decision.deterministic_route}")
        print(f"  start_funnel:         {decision.start_funnel}")
        print(f"  continue_funnel:      {decision.continue_funnel}")
        print(f"  funnel_stage:         {decision.funnel_stage.value}")
        print(f"  ask_qualification_q:  {decision.ask_qualification_question}")
        print(f"  ask_callback:         {decision.ask_callback}")
        print(f"  ask_contact_details:  {decision.ask_contact_details}")
        print(f"  use_llm:              {decision.use_llm}")
        print(f"  use_deterministic_rt: {decision.use_deterministic_route}")
        print(f"  lead_priority:        {decision.lead_priority.value}")
        print(f"  lead_score:           {decision.lead_score}")
        print(f"  reason:               {decision.reason}")
        print("-" * 78)

    print()
    print("=" * 78)
    print("BONUS SCENARIOS — funnel continuation & shortlist (Rules 3, 9, 10)")
    print("=" * 78)

    mid_funnel_session = SessionContext(
        current_university_slug=None,
        current_course_slug=None,
        current_specialization_slug=None,
        comparison_context={},
        profile_context={"desired_program": "MBA"},
    )
    shortlisted_session = SessionContext(
        current_university_slug=None,
        current_course_slug=None,
        current_specialization_slug=None,
        comparison_context={},
        profile_context={"desired_program": "MBA", "budget": "50000", "working_status": "working"},
    )

    bonus_scenarios = [
        ("Mid-funnel re-engagement", "Which MBA should I choose?", no_entities, mid_funnel_session),
        ("Shortlist reached", "Which MBA should I choose?", no_entities, shortlisted_session),
    ]

    for label, message, entities, session in bonus_scenarios:
        intent_result = classifier.classify(message)
        decision = engine.decide(intent_result, entities, session)
        print(f"[{label}] Message: {message!r} | profile={session.profile_context}")
        print(
            f"  funnel_stage: {decision.funnel_stage.value} | continue_funnel: {decision.continue_funnel} "
            f"| ask_qualification_question: {decision.ask_qualification_question} | ask_callback: {decision.ask_callback}"
        )
        print(f"  lead_priority: {decision.lead_priority.value} | lead_score: {decision.lead_score}")
        print(f"  reason: {decision.reason}")
        print("-" * 78)