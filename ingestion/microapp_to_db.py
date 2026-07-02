from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncpg

from settings import settings


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    return float(cleaned) if cleaned else None


def detect_type(payload: dict[str, Any]) -> str:
    if "spec_name" in payload or "specialization_name" in payload:
        return "specialization"
    if "program_name" in payload or "course_name" in payload:
        return "course"
    return "university"


def pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


async def rebuild_search_index(conn: asyncpg.Connection, entity_type: str, entity_id: int) -> None:
    table = {"university": "universities", "course": "courses", "specialization": "specializations"}[entity_type]
    if entity_type == "university":
        row = await conn.fetchrow("SELECT name, full_name, slug FROM universities WHERE id = $1", entity_id)
        parts = [row["name"], row["full_name"], row["slug"]]
    elif entity_type == "course":
        row = await conn.fetchrow("SELECT program_name, slug FROM courses WHERE id = $1", entity_id)
        parts = [row["program_name"], row["slug"]]
    else:
        row = await conn.fetchrow("SELECT spec_name, slug FROM specializations WHERE id = $1", entity_id)
        parts = [row["spec_name"], row["slug"]]
    search_text = " ".join(str(part).lower() for part in parts if part)
    await conn.execute(
        """
        INSERT INTO entity_search(entity_type, entity_id, search_text)
        VALUES($1, $2, $3)
        ON CONFLICT (entity_type, entity_id) DO UPDATE SET search_text = EXCLUDED.search_text, embedding = NULL
        """,
        entity_type,
        entity_id,
        search_text,
    )


async def replace_common_children(conn: asyncpg.Connection, entity_type: str, entity_id: int, payload: dict[str, Any]) -> None:
    for table in ("faqs", "reviews", "job_profiles", "highlights"):
        await conn.execute(f"DELETE FROM {table} WHERE entity_type = $1 AND entity_id = $2", entity_type, entity_id)
    for item in payload.get("faqs", []):
        await conn.execute("INSERT INTO faqs(entity_type, entity_id, question, answer) VALUES($1, $2, $3, $4)", entity_type, entity_id, item.get("question"), item.get("answer"))
    for item in payload.get("reviews", []):
        await conn.execute(
            "INSERT INTO reviews(entity_type, entity_id, review_text, reviewer_name, reviewer_label) VALUES($1, $2, $3, $4, $5)",
            entity_type,
            entity_id,
            item.get("review_text"),
            item.get("reviewer_name"),
            item.get("reviewer_label"),
        )
    for item in payload.get("job_profiles", []):
        await conn.execute("INSERT INTO job_profiles(entity_type, entity_id, job_title, avg_salary) VALUES($1, $2, $3, $4)", entity_type, entity_id, item.get("job_title"), item.get("avg_salary"))
    for item in payload.get("highlights", []):
        await conn.execute(
            "INSERT INTO highlights(entity_type, entity_id, highlight_title, highlight_description) VALUES($1, $2, $3, $4)",
            entity_type,
            entity_id,
            item.get("highlight_title"),
            item.get("highlight_description"),
        )


async def upsert_university(conn: asyncpg.Connection, payload: dict[str, Any]) -> tuple[str, int]:
    name = pick(payload, "name", "university_name") or "University"
    slug = payload.get("slug") or slugify(name)
    row = await conn.fetchrow(
        """
        INSERT INTO universities(slug, name, full_name, established_year, naac_grade, ugc_approved, mode_of_learning,
            starting_fee, num_programs, about_content, why_choose_content, admission_steps, admission_fee_note,
            emi_content, exam_content, faculty_intro, placement_content, seo_title, meta_description, raw_json)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20::jsonb)
        ON CONFLICT (slug) DO UPDATE SET
            name=EXCLUDED.name, full_name=EXCLUDED.full_name, established_year=EXCLUDED.established_year,
            naac_grade=EXCLUDED.naac_grade, ugc_approved=EXCLUDED.ugc_approved, mode_of_learning=EXCLUDED.mode_of_learning,
            starting_fee=EXCLUDED.starting_fee, num_programs=EXCLUDED.num_programs, about_content=EXCLUDED.about_content,
            why_choose_content=EXCLUDED.why_choose_content, admission_steps=EXCLUDED.admission_steps,
            admission_fee_note=EXCLUDED.admission_fee_note, emi_content=EXCLUDED.emi_content, exam_content=EXCLUDED.exam_content,
            faculty_intro=EXCLUDED.faculty_intro, placement_content=EXCLUDED.placement_content, seo_title=EXCLUDED.seo_title,
            meta_description=EXCLUDED.meta_description, raw_json=EXCLUDED.raw_json, updated_at=now()
        RETURNING id
        """,
        slug,
        name,
        payload.get("full_name"),
        payload.get("established_year"),
        payload.get("naac_grade"),
        payload.get("ugc_approved"),
        payload.get("mode_of_learning"),
        parse_money(payload.get("starting_fee")),
        payload.get("num_programs"),
        payload.get("about_content"),
        payload.get("why_choose_content"),
        payload.get("admission_steps"),
        payload.get("admission_fee_note"),
        payload.get("emi_content"),
        payload.get("exam_content"),
        payload.get("faculty_intro"),
        payload.get("placement_content"),
        payload.get("seo_title"),
        payload.get("meta_description"),
        json.dumps(payload),
    )
    entity_id = row["id"]
    await replace_common_children(conn, "university", entity_id, payload)
    for table in ("faculty_members", "accreditations", "facts"):
        await conn.execute(f"DELETE FROM {table} WHERE university_id = $1", entity_id)
    for item in payload.get("faculty_members", []):
        await conn.execute("INSERT INTO faculty_members(university_id, member_name, member_program, member_designation, member_qualification) VALUES($1,$2,$3,$4,$5)", entity_id, item.get("member_name"), item.get("member_program"), item.get("member_designation"), item.get("member_qualification"))
    for item in payload.get("accreditations", []):
        await conn.execute("INSERT INTO accreditations(university_id, body_name, body_descriptor, body_detail) VALUES($1,$2,$3,$4)", entity_id, item.get("body_name"), item.get("body_descriptor"), item.get("body_detail"))
    for item in payload.get("facts", []):
        await conn.execute("INSERT INTO facts(university_id, fact_title, fact_description) VALUES($1,$2,$3)", entity_id, item.get("fact_title"), item.get("fact_description"))
    await rebuild_search_index(conn, "university", entity_id)
    return slug, entity_id


async def upsert_course(conn: asyncpg.Connection, payload: dict[str, Any]) -> tuple[str, int]:
    program = pick(payload, "program_name", "course_name") or "Course"
    slug = payload.get("slug") or slugify(program)
    university_slug = payload.get("university_slug")
    university_id = await conn.fetchval("SELECT id FROM universities WHERE slug = $1", university_slug)
    if not university_id:
        raise ValueError(f"university_slug not found: {university_slug}")
    row = await conn.fetchrow(
        """
        INSERT INTO courses(slug, university_id, program_name, duration, mode, naac_grade, ugc_status, total_fee,
            starting_fee, num_specializations, about_content, eligibility_content, eligibility_summary, admission_steps,
            admission_fee_note, syllabus_content, placement_content, certificate_description, validity, emi_amount,
            seo_title, meta_description, raw_json)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23::jsonb)
        ON CONFLICT (slug) DO UPDATE SET
            university_id=EXCLUDED.university_id, program_name=EXCLUDED.program_name, duration=EXCLUDED.duration,
            mode=EXCLUDED.mode, naac_grade=EXCLUDED.naac_grade, ugc_status=EXCLUDED.ugc_status,
            total_fee=EXCLUDED.total_fee, starting_fee=EXCLUDED.starting_fee, num_specializations=EXCLUDED.num_specializations,
            about_content=EXCLUDED.about_content, eligibility_content=EXCLUDED.eligibility_content,
            eligibility_summary=EXCLUDED.eligibility_summary, admission_steps=EXCLUDED.admission_steps,
            admission_fee_note=EXCLUDED.admission_fee_note, syllabus_content=EXCLUDED.syllabus_content,
            placement_content=EXCLUDED.placement_content, certificate_description=EXCLUDED.certificate_description,
            validity=EXCLUDED.validity, emi_amount=EXCLUDED.emi_amount, seo_title=EXCLUDED.seo_title,
            meta_description=EXCLUDED.meta_description, raw_json=EXCLUDED.raw_json, updated_at=now()
        RETURNING id
        """,
        slug,
        university_id,
        program,
        payload.get("duration"),
        payload.get("mode"),
        payload.get("naac_grade"),
        payload.get("ugc_status"),
        parse_money(payload.get("total_fee")),
        parse_money(payload.get("starting_fee")),
        payload.get("num_specializations"),
        payload.get("about_content"),
        payload.get("eligibility_content"),
        payload.get("eligibility_summary"),
        payload.get("admission_steps"),
        payload.get("admission_fee_note"),
        payload.get("syllabus_content"),
        payload.get("placement_content"),
        payload.get("certificate_description"),
        payload.get("validity"),
        payload.get("emi_amount"),
        payload.get("seo_title"),
        payload.get("meta_description"),
        json.dumps(payload),
    )
    entity_id = row["id"]
    await replace_common_children(conn, "course", entity_id, payload)
    await conn.execute("DELETE FROM fee_plans WHERE course_id = $1", entity_id)
    for item in payload.get("fee_plans", []):
        await conn.execute("INSERT INTO fee_plans(course_id, plan_name, plan_amount, plan_total) VALUES($1,$2,$3,$4)", entity_id, item.get("plan_name"), item.get("plan_amount"), item.get("plan_total"))
    await rebuild_search_index(conn, "course", entity_id)
    return slug, entity_id


async def upsert_specialization(conn: asyncpg.Connection, payload: dict[str, Any]) -> tuple[str, int]:
    name = pick(payload, "spec_name", "specialization_name") or "Specialization"
    slug = payload.get("slug") or slugify(name)
    university_id = await conn.fetchval("SELECT id FROM universities WHERE slug = $1", payload.get("university_slug"))
    course_id = await conn.fetchval("SELECT id FROM courses WHERE slug = $1", payload.get("course_slug"))
    if not university_id or not course_id:
        raise ValueError("university_slug and course_slug must reference existing rows")
    row = await conn.fetchrow(
        """
        INSERT INTO specializations(slug, course_id, university_id, spec_name, duration, mode, naac_grade, ugc_status,
            total_fee, about_content, eligibility_content, eligibility_summary, syllabus_content, exam_content,
            admission_steps, admission_fee_note, placement_content, certificate_description, emi_amount, seo_title,
            meta_description, raw_json)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22::jsonb)
        ON CONFLICT (slug) DO UPDATE SET
            course_id=EXCLUDED.course_id, university_id=EXCLUDED.university_id, spec_name=EXCLUDED.spec_name,
            duration=EXCLUDED.duration, mode=EXCLUDED.mode, naac_grade=EXCLUDED.naac_grade, ugc_status=EXCLUDED.ugc_status,
            total_fee=EXCLUDED.total_fee, about_content=EXCLUDED.about_content, eligibility_content=EXCLUDED.eligibility_content,
            eligibility_summary=EXCLUDED.eligibility_summary, syllabus_content=EXCLUDED.syllabus_content,
            exam_content=EXCLUDED.exam_content, admission_steps=EXCLUDED.admission_steps,
            admission_fee_note=EXCLUDED.admission_fee_note, placement_content=EXCLUDED.placement_content,
            certificate_description=EXCLUDED.certificate_description, emi_amount=EXCLUDED.emi_amount,
            seo_title=EXCLUDED.seo_title, meta_description=EXCLUDED.meta_description, raw_json=EXCLUDED.raw_json,
            updated_at=now()
        RETURNING id
        """,
        slug, course_id, university_id, name, payload.get("duration"), payload.get("mode"), payload.get("naac_grade"),
        payload.get("ugc_status"), parse_money(payload.get("total_fee")), payload.get("about_content"),
        payload.get("eligibility_content"), payload.get("eligibility_summary"), payload.get("syllabus_content"),
        payload.get("exam_content"), payload.get("admission_steps"), payload.get("admission_fee_note"),
        payload.get("placement_content"), payload.get("certificate_description"), payload.get("emi_amount"),
        payload.get("seo_title"), payload.get("meta_description"), json.dumps(payload)
    )
    entity_id = row["id"]
    await replace_common_children(conn, "specialization", entity_id, payload)
    await conn.execute("DELETE FROM other_specs WHERE specialization_id = $1", entity_id)
    for item in payload.get("other_specs", []):
        await conn.execute("INSERT INTO other_specs(specialization_id, other_spec_name, other_spec_fee) VALUES($1,$2,$3)", entity_id, item.get("other_spec_name"), item.get("other_spec_fee"))
    await rebuild_search_index(conn, "specialization", entity_id)
    return slug, entity_id


async def ingest(path: Path, explicit_type: str | None) -> tuple[str, int]:
    payload = json.loads(path.read_text())
    entity_type = explicit_type or detect_type(payload)
    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            if entity_type == "university":
                return await upsert_university(conn, payload)
            if entity_type == "course":
                return await upsert_course(conn, payload)
            if entity_type == "specialization":
                return await upsert_specialization(conn, payload)
            raise ValueError(f"Unknown type: {entity_type}")
    finally:
        await conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--type", choices=["university", "course", "specialization"])
    args = parser.parse_args()
    slug, entity_id = await ingest(args.json_path, args.type)
    print(f"upserted {slug} ({entity_id})")


if __name__ == "__main__":
    asyncio.run(main())
