"""Deterministic ACF adaptation and bounded text extraction. No model/network calls."""
from __future__ import annotations

import copy
import re
from html.parser import HTMLParser
from decimal import Decimal
from typing import Any

from catalog.schema import CatalogError
from money import MONEY_PATTERN, parse_money

TABLES = {"university": "universities", "course": "courses", "specialization": "specializations"}
COMMON_CHILDREN = {
    "faqs": ("question", "answer"),
    "reviews": ("review_text", "reviewer_name", "reviewer_label"),
    "job_profiles": ("job_title", "avg_salary"),
    "highlights": ("highlight_title", "highlight_description"),
}
UNI_CHILDREN = {
    "faculty_members": ("member_name", "member_program", "member_designation", "member_qualification"),
    "accreditations": ("body_name", "body_descriptor", "body_detail"),
    "facts": ("fact_title", "fact_description"),
}
COURSE_CHILDREN = {"fee_plans": ("plan_name", "plan_amount", "plan_total")}
SPEC_CHILDREN = {"other_specs": ("other_spec_name", "other_spec_fee")}
ALIASES = {"university_name": "name", "university_full_name": "full_name", "course_name": "program_name", "specialization_name": "spec_name", "program_validity": "validity"}
PROTECTED = {"id", "slug", "university_id", "course_id", "university_slug", "course_slug", "raw_json", "created_at", "updated_at", "linked_university", "linked_course", "_meta"}
MONEY_FIELDS = {"total_fee", "starting_fee"}
NAME_FIELDS = {"university": "name", "course": "program_name", "specialization": "spec_name"}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: Any, depth: int = 0) -> str:
    if depth > 12:
        raise CatalogError("content_too_deep")
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(f"{k.replace('_', ' ')}: {plain_text(v, depth+1)}" for k, v in value.items() if not k.startswith("_") and v is not None)
    if isinstance(value, list):
        return "\n".join(plain_text(v, depth+1) for v in value)
    extractor = TextExtractor()
    extractor.feed(str(value))
    extractor.close()
    return re.sub(r"\s+", " ", "".join(extractor.parts)).strip()


def child_fields(entity_type):
    return {**COMMON_CHILDREN, **{"university": UNI_CHILDREN, "course": COURSE_CHILDREN, "specialization": SPEC_CHILDREN}[entity_type]}


def adapt_data(entity_type: str, data: dict, baseline: dict, clear_fields: list[str]):
    result = copy.deepcopy(baseline)
    warnings = []
    children = child_fields(entity_type)
    for original_key, value in data.items():
        if original_key in PROTECTED or original_key.startswith("_"):
            continue
        key = ALIASES.get(original_key, original_key)
        if key == "name" and entity_type != "university":
            continue  # course university_name identifies its parent, not its own title
        if value is None or value == "" or value == [] or value == {}:
            continue  # extraction gaps cannot erase existing knowledge
        if key in children:
            if not isinstance(value, list) or len(value) > 1000:
                raise CatalogError("invalid_repeater")
            rows = []
            for item in value:
                if not isinstance(item, dict):
                    raise CatalogError("invalid_repeater_item")
                row = {k: plain_text(item.get(k)) or None for k in children[key]}
                if not any(row.values()):
                    continue
                if key == "faqs" and not (row["question"] and row["answer"]):
                    raise CatalogError("incomplete_faq")
                rows.append(row)
            if rows:
                result[key] = rows
        elif key in MONEY_FIELDS:
            # A range, EMI, or per-period description must not become a guessed total.
            if isinstance(value, bool) or not re.fullmatch(MONEY_PATTERN, str(value).strip(), re.IGNORECASE):
                warnings.append(f"unparsed_{key}")
                result[f"{key}_source_text"] = plain_text(value)
                continue
            amount = parse_money(value)
            if amount is None:
                raise CatalogError("invalid_money")
            result[key] = amount
            result.pop(f"{key}_source_text", None)
        else:
            # Preserve extra ACF fields for the text index as well as supported SQL fields.
            result[key] = copy.deepcopy(value)

    for original_key in clear_fields:
        key = ALIASES.get(original_key, original_key)
        if key in PROTECTED or key.startswith("_") or key in set(NAME_FIELDS.values()) or key not in result:
            raise CatalogError("invalid_clear_field")
        result[key] = [] if key in children else None
        result.pop(f"{key}_source_text", None)

    if not plain_text(result.get(NAME_FIELDS[entity_type])):
        raise CatalogError("missing_entity_name")
    # Importer SQL scalar columns are TEXT (eligibility is an ACF repeater).
    for key, value in list(result.items()):
        if key not in children and key not in MONEY_FIELDS and key not in PROTECTED and value is not None:
            result[key] = value if isinstance(value, str) else plain_text(value)
    # asyncpg returns NUMERIC as Decimal, whose scientific string form is not
    # a rupee expression. Preserve it numerically when a field was omitted.
    for key in MONEY_FIELDS:
        if isinstance(result.get(key), Decimal):
            result[key] = float(result[key])
    return result, warnings


def build_sections(payload: dict) -> list[tuple[str, str]]:
    sections = []
    for key, value in payload.items():
        if key in PROTECTED or key.startswith("_") or key.endswith(("_image", "_heading")) or key in {"brochure", "seo_title", "meta_description"}:
            continue
        text = plain_text(value)
        if not text:
            continue
        title = key.replace("_", " ")
        # Chunks overlap to preserve context at section boundaries, capped per event.
        for start in range(0, len(text), 1400):
            sections.append((title, text[start:start+1600]))
            if len(sections) > 1600:
                raise CatalogError("too_many_sections")
    return sections
