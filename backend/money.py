"""Shared rupee parsing for catalog ingestion and conversational budgets."""
from __future__ import annotations

import math
import re
from typing import Any

# The optional trailing "/-" is the standard Indian rupee suffix ("INR 1,00,000 /-"),
# the form the parser's source documents actually use. It marks a whole amount, so it
# is safe to accept; per-period text ("... /- Semester", "per month") still does not
# match, which keeps the importer from guessing a total out of an instalment.
MONEY_PATTERN = r"(?:₹\s*|(?:rs\.?|inr)\s*)?([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)\s*(crores?|lakhs?|lacs?|thousands?|k)?\b(?:\s*/\s*-)?"
_MULTIPLIERS = {"crore": 10_000_000, "lakh": 100_000, "lac": 100_000, "thousand": 1_000, "k": 1_000}


def parse_money(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        text = str(value).strip().lower()
        if text.startswith("-"):
            return None
        match = re.search(MONEY_PATTERN, text, re.IGNORECASE)
        if not match:
            return None
        unit = (match.group(2) or "").removesuffix("s")
        amount = float(match.group(1).replace(",", "")) * _MULTIPLIERS.get(unit, 1)
    return amount if math.isfinite(amount) and amount >= 0 else None
