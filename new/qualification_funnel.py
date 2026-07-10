"""
qualification_funnel.py

Deterministic state machine for the DegreeBaba chatbot qualification funnel.

The funnel engine is the core lead-generation logic behind the DegreeBaba
chatbot. The bot does not try to answer every question a visitor asks — its
job is to build trust, qualify the visitor, and hand a well-formed lead off
to a human counsellor. This module is the "brain" that tracks where a given
visitor is in that qualification journey.

Design rules (non-negotiable):
    * Deterministic only — no LLM calls.
    * No database access.
    * No network I/O.
    * Pure state machine: every method is a pure function of the
      ``profile_context`` dict passed in. The engine holds no internal
      state of its own, so a single ``QualificationFunnel`` instance is
      safe to share/reuse across requests, threads, or LangGraph nodes.
    * Easy to extend: adding a new funnel stage means adding one enum
      value, one entry in ``_DATA_STAGE_FIELD_MAP`` (or the action-stage
      handling below), and one entry in ``_QUESTION_BANK``.

Typical caller (e.g. a LangGraph tool):

    funnel = QualificationFunnel()
    state = funnel.get_state(profile)
    question = funnel.get_next_question(profile)
    profile = funnel.update_profile(profile, "desired_program", "MBA")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "FunnelStage",
    "FunnelState",
    "FunnelQuestion",
    "FunnelFieldError",
    "FunnelValueError",
    "QualificationFunnel",
    "REQUIRED_PROFILE_FIELDS",
    "FUNNEL_ORDER",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FunnelStage(str, Enum):
    """Every stage the qualification funnel can be in.

    Inherits from ``str`` so stages serialize cleanly to JSON (e.g. when
    the funnel's state is embedded in a LangGraph state dict or returned
    from an API endpoint) without needing a custom encoder.
    """

    NONE = "NONE"
    PROGRAM = "PROGRAM"
    QUALIFICATION = "QUALIFICATION"
    WORK_STATUS = "WORK_STATUS"
    EXPERIENCE = "EXPERIENCE"
    BUDGET = "BUDGET"
    MODE = "MODE"
    SPECIALIZATION = "SPECIALIZATION"
    TIMELINE = "TIMELINE"
    SHORTLIST = "SHORTLIST"
    CALLBACK = "CALLBACK"
    COMPLETE = "COMPLETE"


# ---------------------------------------------------------------------------
# Profile field names
# ---------------------------------------------------------------------------

# The eight fields counsellors actually need. These are the only fields
# that count toward `completion_percentage` / `missing_fields`.
FIELD_DESIRED_PROGRAM = "desired_program"
FIELD_HIGHEST_QUALIFICATION = "highest_qualification"
FIELD_WORKING_STATUS = "working_status"
FIELD_EXPERIENCE = "experience"
FIELD_BUDGET = "budget"
FIELD_PREFERRED_MODE = "preferred_mode"
FIELD_SPECIALIZATION_INTEREST = "specialization_interest"
FIELD_ADMISSION_TIMELINE = "admission_timeline"

REQUIRED_PROFILE_FIELDS: List[str] = [
    FIELD_DESIRED_PROGRAM,
    FIELD_HIGHEST_QUALIFICATION,
    FIELD_WORKING_STATUS,
    FIELD_EXPERIENCE,
    FIELD_BUDGET,
    FIELD_PREFERRED_MODE,
    FIELD_SPECIALIZATION_INTEREST,
    FIELD_ADMISSION_TIMELINE,
]

# Action fields drive the two lead-conversion prompts (SHORTLIST / CALLBACK).
# They are deliberately excluded from REQUIRED_PROFILE_FIELDS: they aren't
# counsellor-facing data, they're funnel-progression signals.
FIELD_SHORTLIST_RESPONSE = "shortlist_response"
FIELD_CALLBACK_RESPONSE = "callback_response"

ALL_VALID_FIELDS = set(REQUIRED_PROFILE_FIELDS) | {
    FIELD_SHORTLIST_RESPONSE,
    FIELD_CALLBACK_RESPONSE,
}


# ---------------------------------------------------------------------------
# Output objects
# ---------------------------------------------------------------------------


@dataclass
class FunnelState:
    """Snapshot of where a visitor currently stands in the funnel."""

    current_stage: FunnelStage
    next_stage: FunnelStage
    is_complete: bool
    ready_for_shortlist: bool
    ready_for_callback: bool
    completion_percentage: int
    missing_fields: List[str]


@dataclass
class FunnelQuestion:
    """A single question the bot should ask next, plus its valid answers."""

    stage: FunnelStage
    field_name: str
    question: str
    options: List[str]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FunnelFieldError(ValueError):
    """Raised when update_profile() is called with an unrecognized field."""


class FunnelValueError(ValueError):
    """Raised when update_profile() is called with a value that is not one
    of the permitted options for that field's stage."""


# ---------------------------------------------------------------------------
# Funnel ordering + question bank
# ---------------------------------------------------------------------------

# Stages that correspond to collecting one counsellor-facing profile field.
_DATA_STAGE_FIELD_MAP: Dict[FunnelStage, str] = {
    FunnelStage.PROGRAM: FIELD_DESIRED_PROGRAM,
    FunnelStage.QUALIFICATION: FIELD_HIGHEST_QUALIFICATION,
    FunnelStage.WORK_STATUS: FIELD_WORKING_STATUS,
    FunnelStage.EXPERIENCE: FIELD_EXPERIENCE,
    FunnelStage.BUDGET: FIELD_BUDGET,
    FunnelStage.MODE: FIELD_PREFERRED_MODE,
    FunnelStage.SPECIALIZATION: FIELD_SPECIALIZATION_INTEREST,
    FunnelStage.TIMELINE: FIELD_ADMISSION_TIMELINE,
}

# Ordered list of the eight data-collection stages.
_DATA_STAGE_ORDER: List[FunnelStage] = [
    FunnelStage.PROGRAM,
    FunnelStage.QUALIFICATION,
    FunnelStage.WORK_STATUS,
    FunnelStage.EXPERIENCE,
    FunnelStage.BUDGET,
    FunnelStage.MODE,
    FunnelStage.SPECIALIZATION,
    FunnelStage.TIMELINE,
]

# The complete funnel order: data collection, then the two lead-conversion
# action stages, then the terminal COMPLETE stage.
FUNNEL_ORDER: List[FunnelStage] = _DATA_STAGE_ORDER + [
    FunnelStage.SHORTLIST,
    FunnelStage.CALLBACK,
    FunnelStage.COMPLETE,
]

_QUESTION_BANK: Dict[FunnelStage, FunnelQuestion] = {
    FunnelStage.PROGRAM: FunnelQuestion(
        stage=FunnelStage.PROGRAM,
        field_name=FIELD_DESIRED_PROGRAM,
        question="Which program are you interested in?",
        options=["MBA", "MCA", "BBA", "BCA", "MCom", "Other"],
    ),
    FunnelStage.QUALIFICATION: FunnelQuestion(
        stage=FunnelStage.QUALIFICATION,
        field_name=FIELD_HIGHEST_QUALIFICATION,
        question="What is your highest qualification?",
        options=["12th Pass", "Diploma", "Graduate", "Postgraduate"],
    ),
    FunnelStage.WORK_STATUS: FunnelQuestion(
        stage=FunnelStage.WORK_STATUS,
        field_name=FIELD_WORKING_STATUS,
        question="Are you currently working?",
        options=["No", "Yes"],
    ),
    FunnelStage.EXPERIENCE: FunnelQuestion(
        stage=FunnelStage.EXPERIENCE,
        field_name=FIELD_EXPERIENCE,
        question="How many years of work experience do you have?",
        options=["0", "1-3", "3-5", "5+"],
    ),
    FunnelStage.BUDGET: FunnelQuestion(
        stage=FunnelStage.BUDGET,
        field_name=FIELD_BUDGET,
        question="What is your budget?",
        options=["Under ₹1 lakh", "₹1-2 lakh", "₹2-4 lakh", "Above ₹4 lakh"],
    ),
    FunnelStage.MODE: FunnelQuestion(
        stage=FunnelStage.MODE,
        field_name=FIELD_PREFERRED_MODE,
        question="Which study mode do you prefer?",
        options=["Online", "Distance", "No Preference"],
    ),
    FunnelStage.SPECIALIZATION: FunnelQuestion(
        stage=FunnelStage.SPECIALIZATION,
        field_name=FIELD_SPECIALIZATION_INTEREST,
        question="Which specialization interests you?",
        options=[
            "Marketing",
            "Finance",
            "HR",
            "Operations",
            "Business Analytics",
            "No Preference",
        ],
    ),
    FunnelStage.TIMELINE: FunnelQuestion(
        stage=FunnelStage.TIMELINE,
        field_name=FIELD_ADMISSION_TIMELINE,
        question="When are you planning to take admission?",
        options=[
            "Immediately",
            "Within 3 Months",
            "Within 6 Months",
            "Just Exploring",
        ],
    ),
    FunnelStage.SHORTLIST: FunnelQuestion(
        stage=FunnelStage.SHORTLIST,
        field_name=FIELD_SHORTLIST_RESPONSE,
        question=(
            "Would you like a counsellor to prepare a detailed shortlist "
            "for you?"
        ),
        options=["Yes", "No"],
    ),
    FunnelStage.CALLBACK: FunnelQuestion(
        stage=FunnelStage.CALLBACK,
        field_name=FIELD_CALLBACK_RESPONSE,
        question=(
            "Would you like a counsellor to call you back and walk you "
            "through next steps?"
        ),
        options=["Yes", "No"],
    ),
}

# Completion rules -----------------------------------------------------------

_SHORTLIST_REQUIRED_FIELDS: List[str] = [
    FIELD_DESIRED_PROGRAM,
    FIELD_BUDGET,
    FIELD_WORKING_STATUS,
]

_CALLBACK_REQUIRED_FIELDS: List[str] = _SHORTLIST_REQUIRED_FIELDS + [
    FIELD_ADMISSION_TIMELINE,
]


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class QualificationFunnel:
    """Deterministic, stateless qualification funnel engine.

    Every method takes ``profile_context`` — a plain dict accumulated over
    the course of a conversation — and derives fresh results from it. The
    engine itself never stores anything, which makes it trivially testable,
    thread-safe, and framework-agnostic (drop it into a LangGraph tool node,
    a REST handler, or a unit test with zero setup).

    This class explicitly does NOT generate recommendations or copy — it
    only manages funnel state. Recommendation/copy generation belongs in
    the response layer (e.g. ``response_strategy.py``), which decides how
    to phrase things around the question this engine returns.
    """

    # -- internal helpers ----------------------------------------------

    @staticmethod
    def _is_answered(profile_context: Dict[str, Any], field_name: str) -> bool:
        value = profile_context.get(field_name)
        return value is not None and str(value).strip() != ""

    def _current_stage(self, profile_context: Dict[str, Any]) -> FunnelStage:
        for stage in _DATA_STAGE_ORDER:
            field_name = _DATA_STAGE_FIELD_MAP[stage]
            if not self._is_answered(profile_context, field_name):
                return stage

        if not self._is_answered(profile_context, FIELD_SHORTLIST_RESPONSE):
            return FunnelStage.SHORTLIST

        if not self._is_answered(profile_context, FIELD_CALLBACK_RESPONSE):
            return FunnelStage.CALLBACK

        return FunnelStage.COMPLETE

    @staticmethod
    def _next_stage(current_stage: FunnelStage) -> FunnelStage:
        if current_stage == FunnelStage.COMPLETE:
            return FunnelStage.COMPLETE
        index = FUNNEL_ORDER.index(current_stage)
        return FUNNEL_ORDER[index + 1]

    @staticmethod
    def _question_for_field(field_name: str) -> Optional[FunnelQuestion]:
        for question in _QUESTION_BANK.values():
            if question.field_name == field_name:
                return question
        return None

    # -- public API ------------------------------------------------------

    def get_state(self, profile_context: Dict[str, Any]) -> FunnelState:
        """Return the full derived state for the given profile context."""
        missing_fields = [
            f
            for f in REQUIRED_PROFILE_FIELDS
            if not self._is_answered(profile_context, f)
        ]
        answered_count = len(REQUIRED_PROFILE_FIELDS) - len(missing_fields)
        completion_percentage = round(
            answered_count / len(REQUIRED_PROFILE_FIELDS) * 100
        )

        current_stage = self._current_stage(profile_context)
        next_stage = self._next_stage(current_stage)

        return FunnelState(
            current_stage=current_stage,
            next_stage=next_stage,
            is_complete=current_stage == FunnelStage.COMPLETE,
            ready_for_shortlist=self.is_ready_for_shortlist(profile_context),
            ready_for_callback=self.is_ready_for_callback(profile_context),
            completion_percentage=completion_percentage,
            missing_fields=missing_fields,
        )

    def get_next_question(
        self, profile_context: Dict[str, Any]
    ) -> Optional[FunnelQuestion]:
        """Return the next question to ask, or None once the funnel is
        COMPLETE."""
        state = self.get_state(profile_context)
        if state.current_stage == FunnelStage.COMPLETE:
            return None
        return _QUESTION_BANK[state.current_stage]

    def update_profile(
        self,
        profile_context: Dict[str, Any],
        field_name: str,
        value: Any,
    ) -> Dict[str, Any]:
        """Return a NEW profile dict with ``field_name`` set to ``value``.

        ``profile_context`` is never mutated in place, so callers (e.g. a
        LangGraph node) can diff old vs. new state cleanly. Values are
        validated against the option list for that field's stage where one
        exists; a close case-insensitive match is normalized to the
        canonical option, anything else raises ``FunnelValueError``.

        Raises:
            FunnelFieldError: if ``field_name`` is not a recognized
                qualification-funnel field.
            FunnelValueError: if ``value`` is not one of the field's
                permitted options.
        """
        if field_name not in ALL_VALID_FIELDS:
            raise FunnelFieldError(
                f"'{field_name}' is not a recognized qualification-funnel "
                f"field. Valid fields: {sorted(ALL_VALID_FIELDS)}"
            )

        question = self._question_for_field(field_name)
        normalized_value: Any = value
        if question is not None and question.options:
            candidate = str(value).strip()
            if candidate not in question.options:
                match = next(
                    (o for o in question.options if o.lower() == candidate.lower()),
                    None,
                )
                if match is None:
                    raise FunnelValueError(
                        f"'{value}' is not a valid answer for '{field_name}'. "
                        f"Expected one of: {question.options}"
                    )
                candidate = match
            normalized_value = candidate

        updated_profile = dict(profile_context)
        updated_profile[field_name] = normalized_value
        return updated_profile

    def is_ready_for_shortlist(self, profile_context: Dict[str, Any]) -> bool:
        """True once desired_program, budget, and working_status are known
        — enough for a counsellor to build a rough shortlist even if the
        rest of the funnel isn't finished."""
        return all(
            self._is_answered(profile_context, f)
            for f in _SHORTLIST_REQUIRED_FIELDS
        )

    def is_ready_for_callback(self, profile_context: Dict[str, Any]) -> bool:
        """True once desired_program, budget, working_status, and
        admission_timeline are known — enough for a counsellor callback to
        be worthwhile."""
        return all(
            self._is_answered(profile_context, f)
            for f in _CALLBACK_REQUIRED_FIELDS
        )


# ---------------------------------------------------------------------------
# Example usage / progression demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    funnel = QualificationFunnel()
    profile: Dict[str, Any] = {}

    print("=== Empty profile ===")
    state = funnel.get_state(profile)
    print(state)
    print(funnel.get_next_question(profile))

    # Simulate a full conversation, one answer at a time, in strict
    # FUNNEL_ORDER.
    answers = [
        (FIELD_DESIRED_PROGRAM, "MBA"),
        (FIELD_HIGHEST_QUALIFICATION, "Graduate"),
        (FIELD_WORKING_STATUS, "Yes"),
        (FIELD_EXPERIENCE, "1-3"),
        (FIELD_BUDGET, "₹1-2 lakh"),
        (FIELD_PREFERRED_MODE, "Online"),
        (FIELD_SPECIALIZATION_INTEREST, "Marketing"),
        (FIELD_ADMISSION_TIMELINE, "Within 3 Months"),
        (FIELD_SHORTLIST_RESPONSE, "Yes"),
        (FIELD_CALLBACK_RESPONSE, "Yes"),
    ]

    for field_name, value in answers:
        profile = funnel.update_profile(profile, field_name, value)
        state = funnel.get_state(profile)
        print(f"\n--- After answering {field_name}='{value}' ---")
        print(
            f"current_stage={state.current_stage.value:<14} "
            f"next_stage={state.next_stage.value:<14} "
            f"completion={state.completion_percentage:>3}%  "
            f"ready_for_shortlist={state.ready_for_shortlist!s:<5} "
            f"ready_for_callback={state.ready_for_callback!s:<5} "
            f"is_complete={state.is_complete}"
        )

    assert state.is_complete is True
    assert state.completion_percentage == 100
    assert state.missing_fields == []
    print("\nFunnel reached COMPLETE with a fully qualified lead profile.")

    # --- Error handling demo ------------------------------------------
    print("\n=== Error handling ===")
    try:
        funnel.update_profile({}, "not_a_real_field", "x")
    except FunnelFieldError as exc:
        print(f"FunnelFieldError: {exc}")

    try:
        funnel.update_profile({}, FIELD_WORKING_STATUS, "Maybe")
    except FunnelValueError as exc:
        print(f"FunnelValueError: {exc}")