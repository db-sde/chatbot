"""
agent/guardrail.py — legacy shim kept for backward-compat imports only.

All real security checking (prompt injection, policy, output scan) now lives
in backend/security/.  This module only re-exports the constants and helpers
that graph.py still references by name.
"""
from __future__ import annotations

# Re-export from the new security layer so any legacy import keeps working.
from security.scanner import check_prompt_safety
from security.policy import check_policy

OFF_TOPIC_REDIRECT = (
    "I can help with universities, courses, fees, eligibility, admissions, "
    "and program comparisons available on DegreeBaba. What would you like to know?"
)
