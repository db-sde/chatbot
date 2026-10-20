"""Scoped, indexed section retrieval; no remote embedding/model calls."""
from __future__ import annotations

from catalog.adapter import TABLES


async def retrieve_sections(pool, university_slug, course_slug, specialization_slug, query_text, limit=4):
    entity_type = "specialization" if specialization_slug else "course" if course_slug else "university"
    slug = specialization_slug or course_slug or university_slug
    if not slug or not query_text.strip():
        return []
    table = TABLES[entity_type]
    if entity_type == "university":
        scope = "e.slug=$1 AND e.slug=$2"
        joins = ""
    elif entity_type == "course":
        scope = "e.slug=$1 AND u.slug=$2"
        joins = "JOIN universities u ON u.id=e.university_id"
    else:
        scope = "e.slug=$1 AND u.slug=$2 AND ($6::text IS NULL OR c.slug=$6) AND c.university_id=u.id"
        joins = "JOIN universities u ON u.id=e.university_id JOIN courses c ON c.id=e.course_id"
    # Table/join strings above are constants, user values are parameters.
    sql = f"""
        SELECT cs.source_url,cs.applied_version,cs.updated_at,s.title,s.content,
            ts_rank_cd(s.search_vector,q.query) AS relevance
        FROM {table} e {joins}
        JOIN catalog_sources cs ON cs.entity_type=$3 AND cs.entity_id=e.id
        JOIN catalog_sections s ON s.source=cs.source AND s.entity_type=cs.entity_type AND s.source_id=cs.source_id
        CROSS JOIN (SELECT websearch_to_tsquery('english',$4) AS query) q
        WHERE {scope} AND s.search_vector @@ q.query
        ORDER BY relevance DESC,s.section_id LIMIT $5
    """
    args = [slug, university_slug, entity_type, query_text[:400], max(1, min(limit, 4))]
    if entity_type == "specialization":
        args.append(course_slug)
    rows = await pool.fetch(sql, *args)
    return [{"source_url": r["source_url"], "source_version": r["applied_version"], "updated_at": r["updated_at"].isoformat(), "section": r["title"], "content": r["content"]} for r in rows]
