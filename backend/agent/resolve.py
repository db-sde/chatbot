from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz, process

from db import queries
from db.pool import get_pool
from leads.scoring import is_contact_intent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Greeting / chitchat detection
# ---------------------------------------------------------------------------

_GREETINGS = {
    "hi", "hello", "hey", "hiya", "helo", "hii", "hiiii",
    "thanks", "thank", "thank you", "thankyou", "thx", "ty",
    "ok", "okay", "k", "kk", "sure",
    "bye", "goodbye", "cya", "see you",
    "good morning", "good evening", "good afternoon", "good night",
    "gm", "gn", "sup", "yo", "what's up", "whats up",
    "nice", "great", "awesome", "cool", "perfect",
    "yes", "no", "nope", "yep", "yup",
}

_GREETING_PATTERN = re.compile(
    r"^(?:hi+|hey+|hello+|helo+|hiya|"
    r"thanks?|thank\s+you|thankyou|thx|ty|"
    r"ok+|okay|sure|"
    r"bye|goodbye|cya|"
    r"good\s+(?:morning|evening|afternoon|night)|"
    r"gm|gn|sup|yo|"
    r"yes|no|nope|yep|yup|"
    r"nice|great|awesome|cool|perfect"
    r")[.!?]*$",
    re.IGNORECASE,
)


def is_greeting(message: str) -> bool:
    """Return True if the message is purely a greeting/chitchat with no factual content."""
    stripped = message.strip()
    if stripped.lower() in _GREETINGS:
        return True
    return bool(_GREETING_PATTERN.match(stripped))


# ---------------------------------------------------------------------------
# In-memory entity cache + canonical university alias index
# ---------------------------------------------------------------------------
# Each university row:
#   {entity_id, search_text, canonical_slug, name?, full_name?}
# Course / specialization rows keep university_id / course_id for scoping.

ENTITY_CACHE: dict[str, list[dict[str, Any]]] = {
    "university": [],
    "course": [],
    "specialization": [],
}

# alias (lowercase) → {entity_id, canonical_slug}
UNIVERSITY_ALIAS_INDEX: dict[str, dict[str, Any]] = {}

# Sorted (alias, meta) longest-first for catalog scan
_UNIVERSITY_ALIASES_SORTED: list[tuple[str, dict[str, Any]]] = []

# Tokens that should never be treated as university aliases. This is the
# baseline stopword set; COURSE_HINTS / SPECIALIZATION_HINTS / generic
# education vocabulary are merged into this further down, once those lists
# exist (see "Structural hint extraction" section below).
_ALIAS_BLOCKLIST = {
    "university", "college", "institute", "online", "distance", "the", "and",
    "of", "for", "in", "to", "a", "an", "mba", "bca", "mca", "bba", "pgdm",
    "course", "courses", "program", "programs", "degree", "edu", "education",
}


def _register_alias(alias: str, entity_id: int, canonical_slug: str) -> None:
    alias = alias.lower().strip()
    alias = re.sub(r"\s+", " ", alias)
    if not alias or len(alias) < 2:
        return
    if alias in _ALIAS_BLOCKLIST:
        return
    # Prefer longer / already-registered only if same entity; allow overwrite of weaker
    existing = UNIVERSITY_ALIAS_INDEX.get(alias)
    if existing and existing["entity_id"] != entity_id:
        # Keep first registered (stable); log once at debug
        return
    UNIVERSITY_ALIAS_INDEX[alias] = {
        "entity_id": entity_id,
        "canonical_slug": canonical_slug,
    }


def _tokenize_for_freq(text: str) -> list[str]:
    text = str(text).lower()
    text = re.sub(r"[^\w\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return [t for t in text.replace("-", " ").split() if t]


def _compute_alias_token_frequencies(
    rows: list[dict[str, Any]]
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """
    First pass over the catalog: for every candidate single-token and bigram
    alias, track which entity_ids it appears under.

    This exists because Indian university names share huge amounts of
    vocabulary ("management", "professional", "global", "education", ...).
    Registering those as single-token aliases means whichever university
    happens to be processed first silently "wins" that word forever, and
    every other university sharing it becomes unreachable by that token.
    Instead we only allow a single-token or bigram alias through when it is
    DISTINCTIVE — i.e. it belongs to exactly one university in the whole
    catalog. Full name / full_name / search_text phrases are registered
    unconditionally since a full phrase is specific enough to be safe.
    """
    token_freq: dict[str, set[int]] = {}
    bigram_freq: dict[str, set[int]] = {}

    for row in rows:
        entity_id = row["entity_id"]
        row_tokens: set[str] = set()
        row_bigrams: set[str] = set()
        for field in ("name", "full_name", "search_text"):
            raw = row.get(field)
            if not raw:
                continue
            tokens = _tokenize_for_freq(raw)
            for tok in tokens:
                if len(tok) >= 2 and tok not in _ALIAS_BLOCKLIST:
                    row_tokens.add(tok)
            for i in range(len(tokens) - 1):
                if tokens[i] in _ALIAS_BLOCKLIST:
                    continue
                row_bigrams.add(f"{tokens[i]} {tokens[i + 1]}")
        for tok in row_tokens:
            token_freq.setdefault(tok, set()).add(entity_id)
        for bg in row_bigrams:
            bigram_freq.setdefault(bg, set()).add(entity_id)

    return token_freq, bigram_freq


def _rebuild_university_alias_index() -> None:
    """Build alias → canonical_slug map from ENTITY_CACHE university rows.

    Single-token and bigram aliases are only registered when they are
    DISTINCTIVE (unique to exactly one university across the whole catalog).
    See _compute_alias_token_frequencies for why.
    """
    UNIVERSITY_ALIAS_INDEX.clear()
    rows = ENTITY_CACHE["university"]
    token_freq, bigram_freq = _compute_alias_token_frequencies(rows)

    for row in rows:
        entity_id = row["entity_id"]
        canonical = row.get("canonical_slug") or row.get("slug")
        if not canonical:
            continue

        # Canonical slug + hyphen variant + brand head are derived from the
        # slug itself (already unique), so these are always safe to register.
        _register_alias(canonical, entity_id, canonical)
        if "-" in canonical:
            _register_alias(canonical.replace("-", " "), entity_id, canonical)
            head = canonical.split("-")[0]
            if head and head not in _ALIAS_BLOCKLIST:
                _register_alias(head, entity_id, canonical)

        for field in ("name", "full_name", "search_text"):
            raw = row.get(field)
            if not raw:
                continue
            text = str(raw).lower()
            text = re.sub(r"[^\w\s\-]", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue

            # Full normalized phrase is specific enough to register unconditionally.
            _register_alias(text, entity_id, canonical)

            tokens = text.replace("-", " ").split()
            for tok in tokens:
                if tok in _ALIAS_BLOCKLIST or len(tok) < 2:
                    continue
                if len(token_freq.get(tok, set())) == 1:
                    _register_alias(tok, entity_id, canonical)

            for i in range(len(tokens) - 1):
                if tokens[i] in _ALIAS_BLOCKLIST:
                    continue
                bigram = f"{tokens[i]} {tokens[i + 1]}"
                if len(bigram_freq.get(bigram, set())) == 1:
                    _register_alias(bigram, entity_id, canonical)

    global _UNIVERSITY_ALIASES_SORTED
    _UNIVERSITY_ALIASES_SORTED = sorted(
        UNIVERSITY_ALIAS_INDEX.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    logger.info(
        "University alias index rebuilt: %d aliases for %d universities (distinctiveness-filtered)",
        len(UNIVERSITY_ALIAS_INDEX),
        len(ENTITY_CACHE["university"]),
    )


def resolve_university_alias(slug_or_alias: str | None) -> str | None:
    """Map any alias / brand / slug to the canonical university slug."""
    if not slug_or_alias:
        return None
    key = slug_or_alias.lower().strip()
    meta = UNIVERSITY_ALIAS_INDEX.get(key)
    if meta:
        return meta["canonical_slug"]
    # Try hyphen/space variants
    meta = UNIVERSITY_ALIAS_INDEX.get(key.replace("-", " "))
    if meta:
        return meta["canonical_slug"]
    meta = UNIVERSITY_ALIAS_INDEX.get(key.replace(" ", "-"))
    if meta:
        return meta["canonical_slug"]
    return None


async def load_entity_cache() -> None:
    """Fetch entity_search rows plus FK columns and university slugs into RAM.

    Called once at lifespan startup and on-demand via admin cache-refresh endpoint.
    """
    pool = await get_pool()

    # Universities — include canonical slug + names for alias index
    uni_rows = await pool.fetch(
        """
        SELECT es.entity_id, es.search_text, u.slug, u.name, u.full_name
        FROM entity_search es
        JOIN universities u ON u.id = es.entity_id
        WHERE es.entity_type = 'university'
        """
    )
    ENTITY_CACHE["university"] = [
        {
            "entity_id": r["entity_id"],
            "search_text": r["search_text"],
            "canonical_slug": r["slug"],
            "slug": r["slug"],
            "name": r["name"],
            "full_name": r["full_name"],
        }
        for r in uni_rows
    ]
    _rebuild_university_alias_index()

    # Courses — include canonical slug and name for zero-round-trip snapping.
    course_rows = await pool.fetch(
        """
        SELECT es.entity_id, es.search_text, c.slug, c.program_name, c.university_id
        FROM entity_search es
        JOIN courses c ON c.id = es.entity_id
        WHERE es.entity_type = 'course'
        """
    )
    ENTITY_CACHE["course"] = [
        {
            "entity_id": r["entity_id"],
            "search_text": r["search_text"],
            "slug": r["slug"],
            "name": r["program_name"],
            "university_id": r["university_id"],
        }
        for r in course_rows
    ]

    # Specializations — include canonical slug and name for zero-round-trip snapping.
    spec_rows = await pool.fetch(
        """
        SELECT es.entity_id, es.search_text, s.slug, s.spec_name, s.university_id, s.course_id
        FROM entity_search es
        JOIN specializations s ON s.id = es.entity_id
        WHERE es.entity_type = 'specialization'
        """
    )
    ENTITY_CACHE["specialization"] = [
        {
            "entity_id": r["entity_id"],
            "search_text": r["search_text"],
            "slug": r["slug"],
            "name": r["spec_name"],
            "university_id": r["university_id"],
            "course_id": r["course_id"],
        }
        for r in spec_rows
    ]

    total = sum(len(v) for v in ENTITY_CACHE.values())
    logger.info("Entity cache loaded: %d rows across %d types", total, len(ENTITY_CACHE))


def seed_university_cache_for_tests(rows: list[dict[str, Any]]) -> None:
    """Test helper: set university cache + rebuild alias index.

    Each row needs entity_id, search_text, and preferably canonical_slug/slug.
    """
    normalized = []
    for r in rows:
        slug = r.get("canonical_slug") or r.get("slug")
        if not slug:
            # Infer from first token of search_text for legacy tests
            tokens = (r.get("search_text") or "").lower().split()
            slug = tokens[0] if tokens else f"uni-{r['entity_id']}"
        normalized.append({
            "entity_id": r["entity_id"],
            "search_text": r.get("search_text", ""),
            "canonical_slug": slug,
            "slug": slug,
            "name": r.get("name"),
            "full_name": r.get("full_name"),
        })
    ENTITY_CACHE["university"] = normalized
    _rebuild_university_alias_index()


# ---------------------------------------------------------------------------
# Structural hint extraction (courses / specs / fees — not universities)
# ---------------------------------------------------------------------------

COURSE_HINTS = [
    "mba", "bca", "mca", "bba", "ma", "ba", "mcom", "bcom",
    "btech", "mtech", "pgdm", "pgpm",
    "masters", "bachelors",
]

SPECIALIZATION_HINTS = [
    "marketing", "finance", "hr", "human resource", "human resources",
    "data science", "cloud", "cloud computing", "retail", "operations",
    "it", "information technology", "fintech", "logistics", "analytics",
    "business analytics", "supply chain", "banking", "insurance",
    "healthcare", "media", "digital marketing",
]

# Course / specialization vocabulary should never become a university alias,
# and should never be counted as a "university-like" token when guessing how
# many institutions a message names — asking about "data science" or "MBA"
# is not the same as naming an institution.
_COURSE_SPEC_TOKENS: set[str] = set()
for _hint in COURSE_HINTS + SPECIALIZATION_HINTS:
    _COURSE_SPEC_TOKENS.update(_hint.split())

# Generic words that recur across dozens of Indian university names. Even
# with the distinctiveness filter in _rebuild_university_alias_index, keeping
# these out of alias generation entirely avoids noisy near-miss fuzzy matches.
_GENERIC_EDU_WORDS = {
    "global", "international", "national", "professional", "management",
    "studies", "science", "sciences", "technology", "technologies",
    "education", "programme", "programmes", "group", "campus", "centre",
    "center", "indian", "academy", "institution", "deemed", "autonomous",
    "private", "public", "state", "central", "school", "faculty", "world",
    "institute", "institutes", "university", "universities", "college",
    "colleges", "open", "correspondence", "regional", "society", "trust",
    "foundation", "research", "advanced", "higher", "learning", "knowledge",
}

# Common verbs/adjectives that show up in ordinary factual questions
# ("which college OFFERS data science", "is it AFFORDABLE") — these must not
# be mistaken for a leftover university name once real stopwords are removed.
_FACTUAL_VERB_NOISE = {
    "offer", "offers", "offering", "provide", "provides", "providing",
    "give", "gives", "giving", "have", "has", "having",
    "recognized", "recognised", "reputed", "approved", "accredited",
    "affordable", "cheap", "expensive", "available", "apply", "applying",
    "enroll", "enrolled", "enrolling", "join", "joining",
    "study", "studying", "learn", "learning", "teach", "teaches",
    "located", "location", "near", "nearby", "city", "state", "country",
    "india", "seat", "seats", "intake", "batch", "semester", "year",
    "years", "month", "months", "fulltime", "parttime", "weekend",
    "weekday", "exam", "exams", "syllabus", "curriculum", "faculty",
    "package", "salary", "job", "jobs", "career", "careers", "good",
    "better", "best", "top", "reviews", "review", "rated", "rating",
}

# Merge into the alias blocklist now that all three word-lists exist. This
# must happen BEFORE _UNIVERSITY_LIKE_BLOCKLIST is defined further down,
# since that set is built as `{...} | _ALIAS_BLOCKLIST` at import time.
_ALIAS_BLOCKLIST.update(_COURSE_SPEC_TOKENS | _GENERIC_EDU_WORDS | _FACTUAL_VERB_NOISE)

_FACTUAL_KEYWORDS = {
    "fee", "fees", "cost", "price", "emi", "eligib", "admission",
    "placement", "ranking", "course", "program", "specializ", "duration",
    "compare", "comparison", "vs", "versus", "tell me about", "info",
    "details", "what is", "how much", "brochure",
    "ugc", "naac", "approve", "accredit", "recogni",
    "this", "current", "here", "page", "about", "university", "college", "school",
    "more", "it",
}


def _message_needs_entity(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _FACTUAL_KEYWORDS)


def _local_extract(message: str) -> dict[str, Any]:
    """Extract structured hints: course type, specialization, fee limits, mode."""
    text = message.lower()
    result: dict[str, Any] = {}

    for course in COURSE_HINTS:
        if re.search(rf"\b{re.escape(course)}\b", text):
            result["course"] = course
            break

    for spec in SPECIALIZATION_HINTS:
        # "it" is usually a pronoun in follow-ups ("is it eligible?",
        # "what does it cost?"). Treat it as Information Technology only
        # when the user supplies explicit specialization/program context or
        # writes the standard uppercase abbreviation.
        if spec == "it" and not (
            re.search(r"\bIT\b", message)
            or re.search(r"\bit\s+(?:speciali[sz]ation|course|program)\b", text)
        ):
            continue
        if re.search(rf"\b{re.escape(spec)}\b", text):
            result["specialization_hint"] = spec
            break

    fee_match = re.search(
        r"(?:under|below|less than|max(?:imum)?)\s*(?:rs\.?|₹)?\s*([\d,]+)", text
    )
    if fee_match:
        result["max_fee"] = float(fee_match.group(1).replace(",", ""))

    if "cheapest" in text or "lowest" in text:
        result["sort_by"] = "fee"
        result["order"] = "asc"

    if "online" in text:
        result["mode"] = "online"
    elif "distance" in text:
        result["mode"] = "distance"

    return result


# ---------------------------------------------------------------------------
# Catalog-first university detection
# ---------------------------------------------------------------------------

def _normalize_message_for_scan(message: str) -> str:
    text = message.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_universities_in_message(message: str) -> list[dict[str, Any]]:
    """
    Scan the message for known catalog aliases (longest-first).

    Returns a de-duplicated list of:
      {entity_id, canonical_slug, matched_alias, method}
    in left-to-right message order.
    """
    if not _UNIVERSITY_ALIASES_SORTED and ENTITY_CACHE["university"]:
        _rebuild_university_alias_index()

    text = _normalize_message_for_scan(message)
    if not text:
        return []

    occupied: list[tuple[int, int]] = []
    matches: list[tuple[int, dict[str, Any]]] = []

    def _overlaps(start: int, end: int) -> bool:
        for a, b in occupied:
            if start < b and end > a:
                return True
        return False

    for alias, meta in _UNIVERSITY_ALIASES_SORTED:
        if " " in alias:
            pattern = re.escape(alias)
        else:
            pattern = rf"\b{re.escape(alias)}\b"
        for m in re.finditer(pattern, text):
            start, end = m.start(), m.end()
            if _overlaps(start, end):
                continue
            occupied.append((start, end))
            matches.append((
                start,
                {
                    "entity_id": meta["entity_id"],
                    "canonical_slug": meta["canonical_slug"],
                    "matched_alias": alias,
                    "method": "catalog",
                },
            ))
            logger.info(
                "CATALOG MATCH FOUND | alias=%r -> CANONICAL SLUG=%s id=%s",
                alias, meta["canonical_slug"], meta["entity_id"],
            )

    matches.sort(key=lambda x: x[0])
    # Deduplicate by entity_id preserving order
    seen: set[int] = set()
    result: list[dict[str, Any]] = []
    for _, item in matches:
        eid = item["entity_id"]
        if eid in seen:
            continue
        seen.add(eid)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Generic academic intent denylist (Change 1)
# ---------------------------------------------------------------------------
# These words describe *intent* or *topic*, not a university brand.
# They must never enter the fuzzy candidate pool, even if they happen to
# score highly against a university name fragment (e.g. "admission" → "mission").
GENERIC_NON_ENTITY_TERMS: frozenset[str] = frozenset({
    # Admission / application
    "admission", "admissions", "admission process", "application",
    "application process", "apply", "registration", "registration process",
    # Financials
    "fee", "fees", "cost", "price", "emi", "scholarship", "scholarships",
    "stipend", "waiver",
    # Eligibility / criteria
    "eligibility", "eligible", "criteria", "qualification", "qualifications",
    "requirement", "requirements",
    # Catalog / program vocabulary
    "course", "courses", "program", "programs", "degree", "online",
    "distance", "learning", "certification", "certifications",
    # Support / contact
    "help", "support", "counsellor", "counselor", "advisor", "adviser",
    "contact", "callback", "enquiry", "inquiry",
    # Misc factual queries
    "scope", "career", "placement", "ranking", "ranking", "review",
    "process", "procedure", "document", "documents",
})


def _has_token_overlap(cand: str, alias: str, min_prefix: int = 3) -> bool:
    """
    Change 2 — token-overlap guard.

    A fuzzy score can be misleadingly high when the candidate and alias
    share no meaningful tokens (e.g. "admission" vs "mission" scores 87.5
    on simple ratio because one is a substring of the other).  We require
    that at least one token from `cand` shares a common prefix of length
    >= min_prefix with at least one token from `alias`.  This is a much
    stricter criterion than substring containment while still allowing:

      * "nmis" → "nmims"   (prefix "nmi")
      * "amity" → "amity online"  (exact token match)
      * "srm" → "srm"   (full match, len 3, prefix len 3)

    and rejecting:

      * "admission" → "mission"   (no common prefix ≥ 3)
    """
    cand_tokens = cand.lower().split()
    alias_tokens = alias.lower().split()
    for ct in cand_tokens:
        for at in alias_tokens:
            # Determine longest common prefix
            lcp = 0
            for a, b in zip(ct, at):
                if a == b:
                    lcp += 1
                else:
                    break
            if lcp >= min_prefix:
                return True
    return False


def _fuzzy_find_universities_in_message(
    message: str,
    already: list[dict[str, Any]],
    threshold: int = 82,
) -> list[dict[str, Any]]:
    """
    Spelling-correction pass: fuzzy-match message tokens against catalog aliases
    when catalog-first scan found nothing (or to catch typos of unmatched tokens).

    Two guards prevent false positives (Change 1 + Change 2):
      1. GENERIC_NON_ENTITY_TERMS denylist — generic academic words are rejected
         before they ever enter the candidate pool.
      2. Token-overlap guard (_has_token_overlap) — a match is only accepted
         when candidate and alias share a meaningful prefix token, ruling out
         substring-only coincidences like "admission" → "mission".
    """
    if not UNIVERSITY_ALIAS_INDEX:
        return []

    already_ids = {m["entity_id"] for m in already}
    text = _normalize_message_for_scan(message)
    raw_tokens = [t for t in text.split() if len(t) >= 3 and t not in _ALIAS_BLOCKLIST]

    # Change 1: strip generic academic intent words before fuzzy matching
    tokens = [t for t in raw_tokens if t not in GENERIC_NON_ENTITY_TERMS]

    # Also try bigrams for multi-word brands
    candidates = list(tokens)
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i + 1]}"
        if bigram not in GENERIC_NON_ENTITY_TERMS:
            candidates.append(bigram)

    found: list[dict[str, Any]] = []
    for cand in candidates:
        best_alias = None
        best_score = 0.0
        best_meta = None
        for alias, meta in UNIVERSITY_ALIAS_INDEX.items():
            if meta["entity_id"] in already_ids:
                continue
            # Prefer similar-length aliases
            if abs(len(alias) - len(cand)) > max(3, len(cand) // 2):
                continue
            score = float(fuzz.ratio(cand, alias))
            if len(cand) <= 3 and score < 90:
                continue
            if score > best_score:
                best_score = score
                best_alias = alias
                best_meta = meta

        if best_meta and best_score >= threshold:
            # Change 2: require meaningful token overlap — rejects substring-only hits
            if not _has_token_overlap(cand, best_alias):
                logger.debug(
                    "FUZZY REJECTED | no token overlap | query=%r alias=%r score=%.1f",
                    cand, best_alias, best_score,
                )
                continue

            already_ids.add(best_meta["entity_id"])
            item = {
                "entity_id": best_meta["entity_id"],
                "canonical_slug": best_meta["canonical_slug"],
                "matched_alias": best_alias,
                "method": "fuzzy",
                "score": best_score,
            }
            found.append(item)
            logger.info(
                "CATALOG MATCH FOUND | fuzzy query=%r alias=%r score=%.1f -> CANONICAL SLUG=%s",
                cand, best_alias, best_score, best_meta["canonical_slug"],
            )
    return found


# Tokens that look like university brand names (short, not stop words, not course hints)
# Used to detect user-intended entity count even when catalog misses
_UNIVERSITY_LIKE_BLOCKLIST = {
    "tell", "me", "about", "what", "is", "the", "for", "of", "and", "in", "to",
    "a", "an", "i", "want", "know", "please", "can", "you", "get", "give",
    "details", "info", "much", "does", "cost", "fee", "fees", "how", "best",
    "university", "college", "institute", "program", "degree", "online",
    "compare", "comparison", "vs", "versus", "or", "with", "show", "list",
    "that", "this", "are", "have", "has", "do", "which", "any", "all",
    "will", "would", "could", "should", "may", "more", "yes", "no", "okey",
    "okay", "ok", "hi", "hello", "hey", "thats", "whats", "coures", "courses",
    # Additional common non-entity words
    "check", "emi", "price", "eligib", "eligibility", "eligible", "admission",
    "placement", "ranking", "brochure", "duration", "mode", "naac", "ugc",
    "its", "them", "they", "our", "your", "my", "new", "also", "now", "top",
    "right", "need", "some", "many", "these", "those", "been", "look", "see",
    "not", "but", "just", "very", "from", "where", "when", "why", "who",
    # Prompt-control vocabulary is not an institution name. Input security
    # handles these messages before the graph in production; keeping them out
    # of entity counting also preserves the graph's direct-call guard path.
    "ignore", "previous", "instructions", "instruction", "system", "prompt",
    # Back-reference words (not university names)
    "uni", "talking", "referring", "said", "asking", "mentioned", "above",
    "that", "same", "one", "other", "another", "both", "either",
} | _ALIAS_BLOCKLIST | GENERIC_NON_ENTITY_TERMS


def _count_intended_universities(message: str) -> int:
    """
    Estimate how many distinct university names the user intended to mention.

    Two independent signals are combined per comparison-connector-delimited
    segment; either is sufficient:

      1. Capitalization — a token that is capitalized and is NOT the first
         word of its segment is very likely a proper noun ("NMIMS", "Sharda",
         "FakeUniversity") in an otherwise lowercase chat message.
      2. Leftover vocabulary — after stripping stopwords, course names,
         specialization names, and common factual/query verbs, any token
         that still remains and is long enough (>=4 chars) to plausibly be a
         brand name. This catches all-lowercase mentions of universities that
         may not be in the catalog at all (which is the whole point — we
         still need to know the user *intended* one, e.g. Rule 2).

    This deliberately trades a little recall for much lower false-positive
    rates on generic catalog-wide questions like
    "which college offers data science online" (no capitalized words, and
    every leftover token is blocklisted noise → count stays 0).
    """
    raw_parts = re.split(r"\b(?:and|vs|versus|or|with)\b|,", message, flags=re.IGNORECASE)
    count = 0
    for part in raw_parts:
        words = part.strip().split()
        if not words:
            continue
        has_candidate = False
        for idx, word in enumerate(words):
            cleaned = re.sub(r"[^\w\-]", "", word)
            if not cleaned:
                continue
            lower = cleaned.lower()
            if lower in _UNIVERSITY_LIKE_BLOCKLIST:
                continue
            # High-confidence typo tolerance for generic academic vocabulary.
            # This prevents "scolarship" from becoming a fake university while
            # keeping actual brand candidates available to the alias matcher.
            if len(lower) >= 4 and process.extractOne(
                lower,
                _UNIVERSITY_LIKE_BLOCKLIST,
                scorer=fuzz.ratio,
                score_cutoff=88,
            ):
                continue
            is_cap_signal = idx > 0 and cleaned[0].isupper()
            is_leftover_signal = len(cleaned) >= 4
            if is_cap_signal or is_leftover_signal:
                has_candidate = True
                break
        if has_candidate:
            count += 1
    return count


def extract_intent(message: str) -> dict[str, Any]:
    """
    Parse structural hints (course / specialization / fee / mode).

    University entities come from catalog-first detection in resolve_entities().
    This function only sets university_query for logging/test compatibility.
    """
    local = _local_extract(message)
    result: dict[str, Any] = {
        k: v for k, v in local.items()
        if k not in ("course", "specialization_hint")
    }

    if "course" in local:
        result["course_query"] = local["course"]
    if "specialization_hint" in local:
        result["specialization_query"] = local["specialization_hint"]

    # NOTE: catalog scan is intentionally NOT done here to avoid double-calling.
    # resolve_entities() runs the full catalog scan and populates university_matches.

    return result


# ---------------------------------------------------------------------------
# Query classification helpers (comparison vs. multi-mention, catalog-wide)
# ---------------------------------------------------------------------------

_COMPARISON_PATTERN = re.compile(
    r"\b(?:compare|comparison|vs\.?|versus|difference\s+between|"
    r"which\s+is\s+better|better\s+than)\b",
    re.IGNORECASE,
)


def _is_comparison_query(message: str) -> bool:
    """True when the user is explicitly asking to compare named universities,
    as opposed to merely mentioning more than one in passing."""
    return bool(_COMPARISON_PATTERN.search(message))


_COMPARISON_FOLLOW_UP_PATTERN = re.compile(
    r"\b(?:which|who)\b.*\b(?:cheaper|better|best|stronger|placements?|alumni|working professionals?)\b"
    r"|\b(?:cheaper|better|best|stronger)\b.*\b(?:placements?|alumni|working professionals?)\b",
    re.IGNORECASE,
)


def _is_comparison_follow_up(message: str) -> bool:
    """Recognize pronoun-based comparison questions only with saved comparison state."""
    return bool(_COMPARISON_FOLLOW_UP_PATTERN.search(message))


_CATALOG_WIDE_PATTERN = re.compile(
    r"\b(?:which|what|list|show\s+me|top|best)\b[^.?!]{0,25}"
    r"\b(?:universit(?:y|ies)|colleges?|institutes?)\b"
    r"|\buniversit(?:y|ies)\b[^.?!]{0,25}\b(?:offer|offering|have|provide|provides|give|giving)\b"
    r"|\ball\s+universit(?:y|ies)\b"
    r"|\buniversit(?:y|ies)\s+(?:list|options)\b",
    re.IGNORECASE,
)

_CATALOG_SUPERLATIVE_PATTERN = re.compile(
    r"\b(?:best|top|cheapest|most\s+affordable|highest[-\s]?rated)\b"
    r"[^.?!]{0,50}\b(?:programs?|courses?|mba|bba|bca|mca|pgdm)\b"
    r"|\bwhich\b[^.?!]{0,45}\b(?:program|course|mba|bba|bca|mca|pgdm)\b"
    r"[^.?!]{0,25}\b(?:should\s+i|suits?\s+me|is\s+(?:the\s+)?best)\b"
    r"|\brecommend\s+(?:a|an|the)?\s*[^.?!]{0,30}"
    r"\b(?:program|course|mba|bba|bca|mca|pgdm)\b",
    re.IGNORECASE,
)

_CATALOG_DISCOVERY_PATTERN = re.compile(
    r"\b(?:online|distance)\s+(?:universit(?:y|ies)|colleges?|institutes?)\b"
    r"|\b(?:online|distance)\s+(?:mba|bba|bca|mca|pgdm|courses?|programs?)"
    r"\s+(?:courses?|programs?|options?)\b"
    r"|\b(?:compare|comparison\s+of|list|show\s+me)\b[^.?!]{0,35}"
    r"\b(?:mba|bba|bca|mca|pgdm)\s+(?:courses?|programs?|options?)\b",
    re.IGNORECASE,
)

_SUBJECTIVE_RECOMMENDATION_PATTERN = re.compile(
    r"\b(?:best|right|ideal|suitable)\b[^.?!]{0,55}\b(?:for\s+me|suits?\s+me)\b"
    r"|\b(?:which|what)\b[^.?!]{0,45}\b(?:should\s+i\s+choose|suits?\s+me)\b"
    r"|\bhelp\s+me\s+(?:choose|pick|find)\b"
    r"|\b(?:recommend|suggest)\b[^.?!]{0,45}\b"
    r"(?:mba|bba|bca|mca|pgdm|courses?|programs?|universit(?:y|ies))\b"
    r"|\bwhich\b[^.?!]{0,40}\b(?:mba|course|program|university)\b"
    r"[^.?!]{0,25}\b(?:is\s+(?:the\s+)?best|should\s+i\s+choose)\b",
    re.IGNORECASE,
)


def is_subjective_recommendation(message: str) -> bool:
    """Whether a catalog recommendation needs user-supplied filter criteria."""
    return bool(_SUBJECTIVE_RECOMMENDATION_PATTERN.search(message))


def _is_catalog_wide_query(message: str) -> bool:
    """
    True for questions about the catalog in general — "which university
    offers BTech?", "list of universities for MBA" — where no *specific*
    institution should be assumed from session or page context, even if one
    was discussed earlier in the conversation or is currently on-screen.
    """
    return bool(
        _CATALOG_WIDE_PATTERN.search(message)
        or _CATALOG_SUPERLATIVE_PATTERN.search(message)
        or _CATALOG_DISCOVERY_PATTERN.search(message)
    )


def _qualification_budget(message: str, intent: dict[str, Any]) -> float | None:
    if intent.get("max_fee") is not None:
        return float(intent["max_fee"])
    match = re.search(
        r"(?:₹|rs\.?\s*)?([0-9]+(?:\.[0-9]+)?)\s*(lakh|lac|lakhs|k|thousand)?",
        message.lower(),
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit in {"lakh", "lac", "lakhs"}:
        value *= 100_000
    elif unit in {"k", "thousand"}:
        value *= 1_000
    return value if value >= 10_000 else None


def _qualification_resolution(
    message: str,
    intent: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Advance the one-question-at-a-time recommendation profile."""
    profile_context = dict(context.get("profile_context") or {})
    qualification = dict(profile_context.get("qualification") or {})
    active = qualification.get("status") == "collecting"

    if not active:
        qualification = {
            "status": "collecting",
            "course_type": intent.get("course_query"),
            "mode": intent.get("mode"),
            "max_fee": intent.get("max_fee"),
            "specialization": intent.get("specialization_query"),
            "specialization_answered": bool(intent.get("specialization_query")),
        }
    else:
        awaiting = qualification.get("awaiting")
        if awaiting == "course_type":
            course_type = intent.get("course_query")
            if course_type:
                qualification["course_type"] = course_type
        elif awaiting == "budget":
            budget = _qualification_budget(message, intent)
            if budget is not None:
                qualification["max_fee"] = budget
        elif awaiting == "mode":
            mode = intent.get("mode")
            if not mode:
                normalized = message.lower()
                if "online" in normalized:
                    mode = "online"
                elif "distance" in normalized:
                    mode = "distance"
            if mode:
                qualification["mode"] = mode
        elif awaiting == "specialization":
            normalized = _normalize_message_for_scan(message)
            no_preference = any(
                phrase in normalized
                for phrase in ("no preference", "any specialization", "anything", "not sure")
            )
            specialization = intent.get("specialization_query")
            if specialization or no_preference:
                qualification["specialization"] = specialization
                qualification["specialization_answered"] = True

    if not qualification.get("course_type"):
        qualification["awaiting"] = "course_type"
    elif qualification.get("max_fee") is None:
        qualification["awaiting"] = "budget"
    elif not qualification.get("mode"):
        qualification["awaiting"] = "mode"
    elif not qualification.get("specialization_answered"):
        qualification["awaiting"] = "specialization"
    else:
        qualification["awaiting"] = None
        qualification["status"] = "ready"

    profile_context["qualification"] = qualification
    return {
        **_EMPTY_RESOLUTION,
        "raw": intent,
        "mode": qualification.get("mode"),
        "max_fee": qualification.get("max_fee"),
        "resolution_status": "subjective_recommendation",
        "intent_type": "subjective_recommendation",
        "profile_context_update": profile_context,
        "qualification": qualification,
    }


def _is_qualification_answer(
    message: str,
    intent: dict[str, Any],
    awaiting: str | None,
) -> bool:
    if awaiting == "course_type":
        return bool(intent.get("course_query"))
    if awaiting == "budget":
        return _qualification_budget(message, intent) is not None
    if awaiting == "mode":
        normalized = message.lower()
        return bool(intent.get("mode") or "online" in normalized or "distance" in normalized)
    if awaiting == "specialization":
        normalized = _normalize_message_for_scan(message)
        return bool(
            intent.get("specialization_query")
            or any(
                phrase in normalized
                for phrase in ("no preference", "any specialization", "anything", "not sure")
            )
        )
    return False


# ---------------------------------------------------------------------------
# Snapping (courses / specializations still use exact + fuzzy)
# ---------------------------------------------------------------------------

def _exact_match(normalized_name: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        tokens = row["search_text"].lower().split()
        if normalized_name in tokens:
            return row
    return None


def token_aware_similarity(query: str, target: str) -> float:
    q_tokens = query.lower().split()
    t_tokens = target.lower().split()
    if not q_tokens or not t_tokens:
        return 0.0

    total_score = 0.0
    for q_tok in q_tokens:
        best_tok_score = 0.0
        for t_tok in t_tokens:
            score = fuzz.ratio(q_tok, t_tok)
            if len(q_tok) <= 2 and score < 95:
                score = 0.0
            if score > best_tok_score:
                best_tok_score = score
        total_score += best_tok_score

    return total_score / len(q_tokens)


def _fuzzy_snap(
    normalized_name: str, rows: list[dict[str, Any]], threshold: int
) -> dict[str, Any] | None:
    best_score = 0.0
    best_row = None
    for row in rows:
        score = token_aware_similarity(normalized_name, row["search_text"].lower())
        if score > best_score:
            best_score = score
            best_row = row

    logger.debug(
        "FUZZY | name=%r best=%r score=%.1f threshold=%d -> %s",
        normalized_name,
        best_row["search_text"] if best_row else None,
        best_score, threshold,
        "HIT" if (best_row and best_score >= threshold) else "MISS",
    )
    return best_row if (best_row and best_score >= threshold) else None


async def _to_slug(entity_type: str, row: dict[str, Any]) -> str | None:
    # All warm-cache rows include a canonical slug. Keep the DB fallback for
    # cold/legacy cache rows so resolver behavior remains unchanged.
    if row.get("canonical_slug"):
        return row["canonical_slug"]
    if row.get("slug"):
        return row["slug"]
    pool = await get_pool()
    return await queries.slug_for_entity_id(pool, entity_type, row["entity_id"])


async def snap_university(name: str | None) -> tuple[str | None, int | None]:
    """Resolve a free-text name/alias to (canonical_slug, entity_id)."""
    if not name:
        return None, None

    normalized = name.lower().strip()

    # 1. Alias index (canonical system)
    meta = UNIVERSITY_ALIAS_INDEX.get(normalized)
    if not meta:
        meta = UNIVERSITY_ALIAS_INDEX.get(normalized.replace("-", " "))
    if meta:
        logger.info(
            "SNAP university | alias | %r -> CANONICAL SLUG=%s id=%d",
            normalized, meta["canonical_slug"], meta["entity_id"],
        )
        return meta["canonical_slug"], meta["entity_id"]

    rows = ENTITY_CACHE["university"]
    if not rows:
        logger.warning("University cache empty — falling back to DB")
        pool = await get_pool()
        rows = await queries.find_entity_search(pool, "university")

    row = _exact_match(normalized, rows)
    if row:
        slug = await _to_slug("university", row)
        logger.info("SNAP university | exact | %r -> CANONICAL SLUG=%s id=%d", normalized, slug, row["entity_id"])
        return slug, row["entity_id"]

    row = _fuzzy_snap(normalized, rows, threshold=82)
    if row:
        slug = await _to_slug("university", row)
        logger.info("SNAP university | fuzzy | %r -> CANONICAL SLUG=%s id=%d", normalized, slug, row["entity_id"])
        return slug, row["entity_id"]

    logger.info("SNAP university | MISS | %r", normalized)
    return None, None


async def snap_course(
    name: str | None,
    university_entity_id: int | None = None,
) -> tuple[str | None, int | None]:
    if not name:
        return None, None

    normalized = name.lower().strip()
    all_rows = ENTITY_CACHE["course"]
    if not all_rows:
        logger.warning("Course cache empty — falling back to DB")
        pool = await get_pool()
        all_rows = await queries.find_entity_search(pool, "course")

    scoped = (
        [r for r in all_rows if r.get("university_id") == university_entity_id]
        if university_entity_id is not None
        else list(all_rows)
    )

    for candidate_rows, label in [(scoped, "scoped"), (all_rows, "global")]:
        if not candidate_rows:
            continue
        row = _exact_match(normalized, candidate_rows)
        if not row:
            row = _fuzzy_snap(normalized, candidate_rows, threshold=80)
        if row:
            logger.info("SNAP course | %s | %r -> id=%d", label, normalized, row["entity_id"])
            return await _to_slug("course", row), row["entity_id"]
        if label == "scoped" and candidate_rows is all_rows:
            break

    logger.info("SNAP course | MISS | %r", normalized)
    return None, None


async def snap_specialization(
    name: str | None,
    university_entity_id: int | None = None,
    course_entity_id: int | None = None,
) -> str | None:
    if not name:
        return None

    normalized = name.lower().strip()
    all_rows = ENTITY_CACHE["specialization"]
    if not all_rows:
        logger.warning("Specialization cache empty — falling back to DB")
        pool = await get_pool()
        all_rows = await queries.find_entity_search(pool, "specialization")

    candidate_sets: list[tuple[list[dict[str, Any]], str]] = []
    if course_entity_id is not None:
        candidate_sets.append(
            ([r for r in all_rows if r.get("course_id") == course_entity_id], "course-scoped")
        )
    if university_entity_id is not None:
        candidate_sets.append(
            ([r for r in all_rows if r.get("university_id") == university_entity_id], "uni-scoped")
        )
    candidate_sets.append((all_rows, "global"))

    for scope_rows, label in candidate_sets:
        if not scope_rows:
            continue
        row = _exact_match(normalized, scope_rows)
        if not row:
            row = _fuzzy_snap(normalized, scope_rows, threshold=80)
        if row:
            logger.info(
                "SNAP spec | %s | %r course_id=%s uni_id=%s -> id=%d",
                label, normalized, course_entity_id, university_entity_id, row["entity_id"],
            )
            return await _to_slug("specialization", row)
        if scope_rows is all_rows:
            break

    logger.info("SNAP spec | MISS | %r", normalized)
    return None


# ---------------------------------------------------------------------------
# Public entry point: hierarchical entity resolution
# ---------------------------------------------------------------------------

_EMPTY_RESOLUTION = {
    "raw": {},
    "university_slug": None,
    "course_slug": None,
    "specialization_slug": None,
    "mode": None,
    "max_fee": None,
    "sort_by": None,
    "order": "asc",
    "comparison_targets": [],
    "resolution_status": "none",
    "requested_entity": None,
    "comparison_found": [],
    "comparison_missing": [],
    "intent_type": None,
    "mention_type": None,
}


async def resolve_entities(
    message: str,
    context: dict[str, Any],
    page_university_slug: str | None = None,
) -> dict[str, Any]:
    """
    Resolve named entities from the user's message:
      0. Contact intent → skip entity extraction entirely
      1. Greeting short-circuit
      2. Catalog-first university detection (+ fuzzy spelling)
      3. Course / specialization snap when structural evidence exists
      4. Session / page context only when no university was named in catalog
         AND the message isn't a catalog-wide question
    """
    # ── Step 0a: Contact intent short-circuit ──────────────────────────────
    if is_contact_intent(message):
        logger.info("CONTACT INTENT DETECTED | msg=%r", message[:80])
        return {
            **_EMPTY_RESOLUTION,
            "resolution_status": "contact",
            "intent_type": "contact",
            "raw": {"intent_type": "contact"},
        }

    # ── Step 0b: Greeting short-circuit ────────────────────────────────────
    if is_greeting(message):
        logger.info("RESOLVE | greeting detected, skipping entity resolution: %r", message[:60])
        return {**_EMPTY_RESOLUTION, "resolution_status": "none"}

    intent = extract_intent(message)
    logger.info("INTENT | msg=%r -> %r", message[:80], intent)

    qualification = (context.get("profile_context") or {}).get("qualification") or {}
    qualification_active = qualification.get("status") == "collecting"
    if qualification_active and _is_qualification_answer(
        message, intent, qualification.get("awaiting")
    ):
        logger.info("SUBJECTIVE RECOMMENDATION | active=True msg=%r", message[:80])
        return _qualification_resolution(message, intent, context)

    # ── Step 1: Catalog-first universities ─────────────────────────────────
    catalog_hits = find_universities_in_message(message)
    if not catalog_hits:
        catalog_hits = _fuzzy_find_universities_in_message(message, [])

    resolved_slugs: list[str] = []
    resolved_ids: list[int] = []
    matched_aliases: list[str] = []
    for hit in catalog_hits:
        slug = hit["canonical_slug"]
        if slug not in resolved_slugs:
            resolved_slugs.append(slug)
            resolved_ids.append(hit["entity_id"])
            matched_aliases.append(hit.get("matched_alias") or slug)
            logger.info(
                "CANONICAL SLUG | matched=%r -> %s (method=%s)",
                hit.get("matched_alias"), slug, hit.get("method"),
            )

    # Scope must be decided before course snapping. A catalog request carries
    # a course TYPE (MBA) rather than one arbitrary course entity slug.
    catalog_wide_requested = not resolved_slugs and _is_catalog_wide_query(message)

    if not resolved_slugs and is_subjective_recommendation(message):
        logger.info(
            "SUBJECTIVE RECOMMENDATION | active=False msg=%r", message[:80]
        )
        return _qualification_resolution(message, intent, context)

    # How many university-like names did the user intend to mention?
    # This is used to detect partial matches and entity_not_found when
    # catalog scan found fewer hits than the user intended.
    intended_count = _count_intended_universities(message)
    saved_comparison_context = context.get("comparison_context") or {}
    saved_comparison_targets = saved_comparison_context.get("university_slugs") or []
    is_saved_comparison_follow_up = (
        len(saved_comparison_targets) > 1 and _is_comparison_follow_up(message)
    )

    # explicit_university_requested: user mentioned at least one university-like
    # name, regardless of whether it was in the catalog.
    # Interrogatives such as "Which has better placements?" can look
    # university-like to the broad detector. Saved comparison context takes
    # precedence only for the narrow follow-up pattern above.
    explicit_university_requested = (
        (bool(resolved_slugs) or intended_count > 0)
        and not is_saved_comparison_follow_up
    )
    university_slug = resolved_slugs[0] if resolved_slugs else None
    university_entity_id = resolved_ids[0] if resolved_ids else None

    # ── Step 2: Course (scoped to university) ──────────────────────────────
    course_slug: str | None = None
    course_entity_id: int | None = None
    if "course_query" in intent and not catalog_wide_requested:
        course_slug, course_entity_id = await snap_course(
            intent["course_query"],
            university_entity_id=university_entity_id,
        )

    # ── Step 3: Specialization ─────────────────────────────────────────────
    specialization_slug: str | None = None
    if "specialization_query" in intent:
        specialization_slug = await snap_specialization(
            intent["specialization_query"],
            university_entity_id=university_entity_id,
            course_entity_id=course_entity_id,
        )

    # ── Step 4: Status determination + session/page fallbacks ─────────────
    resolution_status: str
    requested_entity: str | None = None
    comparison_targets: list[str] = []
    comparison_found: list[str] = []
    comparison_missing: list[str] = []
    mention_type: str | None = None

    if explicit_university_requested:
        found_count = len(resolved_slugs)

        if found_count == 0:
            # User explicitly named university/universities but NONE are in catalog.
            resolution_status = "entity_not_found"
            university_slug = None
            # Try to extract a readable name from the message for the error message
            text_normalized = _normalize_message_for_scan(message)
            tokens = [
                t for t in text_normalized.split()
                if len(t) >= 3 and t not in _UNIVERSITY_LIKE_BLOCKLIST
            ]
            requested_entity = " ".join(tokens[:3]) if tokens else message[:40]
            logger.info(
                "EXPLICIT ENTITY NOT FOUND | requested=%r | RESOLVED | uni=None",
                requested_entity,
            )

        elif intended_count > 1 and found_count < intended_count:
            # Multi-university query but only some resolved → partial match
            resolution_status = "partial_match"
            comparison_found = resolved_slugs
            mention_type = "comparison" if _is_comparison_query(message) else "multiple"
            # Build missing list: segments that had tokens but yielded no catalog hit
            text_normalized = _normalize_message_for_scan(message)
            parts = re.split(r"\b(?:and|vs|versus|or|with)\b|,", text_normalized, flags=re.IGNORECASE)
            for part in parts:
                tokens = [
                    t for t in part.split()
                    if len(t) >= 3 and t not in _UNIVERSITY_LIKE_BLOCKLIST
                ]
                if not tokens:
                    continue
                candidate = " ".join(tokens[:2])
                # Is this segment already covered by a resolved slug's matched alias?
                covered = any(
                    candidate in (a.lower() for a in matched_aliases)
                    or any(t in a.lower() for t in tokens for a in matched_aliases)
                    for _ in [None]  # single iteration
                )
                if not covered:
                    comparison_missing.append(candidate)
            requested_entity = ", ".join(matched_aliases)
            logger.info(
                "PARTIAL MATCH DETECTED | found=%r | missing=%r | RESOLVED | uni=%s",
                resolved_slugs, comparison_missing, university_slug,
            )

        elif found_count > 1:
            # Multi-university query, all resolved
            resolution_status = "resolved"
            comparison_targets = resolved_slugs
            comparison_found = resolved_slugs
            requested_entity = ", ".join(matched_aliases)
            mention_type = "comparison" if _is_comparison_query(message) else "multiple"

        else:
            # Single university found
            resolution_status = "resolved"
            requested_entity = resolved_slugs[0]
            mention_type = "single"

    else:
        # User did NOT mention any university-like name.
        catalog_wide = catalog_wide_requested
        page_canonical = resolve_university_alias(page_university_slug) or page_university_slug
        session_uni = context.get("current_university_slug")
        comparison_context = saved_comparison_context
        saved_targets = saved_comparison_targets

        if catalog_wide:
            # Explicit catalog-wide question ("which university offers BTech?",
            # "list of universities for MBA") must never be silently narrowed
            # to whatever university was discussed earlier in the session or
            # is currently shown on the page.
            resolution_status = "catalog_query"
            logger.info(
                "CATALOG-WIDE QUERY DETECTED | msg=%r | SESSION/PAGE CONTEXT SKIPPED",
                message[:80],
            )
        elif len(saved_targets) > 1 and _is_comparison_follow_up(message):
            comparison_targets = list(saved_targets)
            comparison_found = list(saved_targets)
            university_slug = saved_targets[0]
            course_slug = comparison_context.get("course_slug") or course_slug
            specialization_slug = comparison_context.get("specialization_slug") or specialization_slug
            resolution_status = "comparison_context"
            mention_type = "comparison_follow_up"
            logger.info("COMPARISON CONTEXT APPLIED | targets=%s", comparison_targets)
        elif session_uni:
            university_slug = resolve_university_alias(session_uni) or session_uni
            resolution_status = "session_context"
            logger.info(
                "NO EXPLICIT ENTITY DETECTED | SESSION CONTEXT APPLIED | uni=%s",
                university_slug,
            )
        elif page_canonical and _message_needs_entity(message):
            university_slug = page_canonical
            resolution_status = "page_context"
            logger.info(
                "NO EXPLICIT ENTITY DETECTED | PAGE CONTEXT APPLIED | uni=%s",
                university_slug,
            )
        else:
            resolution_status = "none"

        if not catalog_wide and not course_slug:
            course_slug = context.get("current_course_slug")
        if not catalog_wide and not specialization_slug:
            specialization_slug = context.get("current_specialization_slug")

    logger.info(
        "RESOLVED | uni=%s course=%s spec=%s status=%s mention_type=%s",
        university_slug, course_slug, specialization_slug, resolution_status, mention_type,
    )

    return {
        "raw": intent,
        "university_slug": university_slug,
        "course_slug": course_slug,
        "specialization_slug": specialization_slug,
        "mode": intent.get("mode"),
        "max_fee": intent.get("max_fee"),
        "sort_by": intent.get("sort_by"),
        "order": intent.get("order", "asc"),
        "comparison_targets": comparison_targets or list(resolved_slugs),
        "resolution_status": resolution_status,
        "requested_entity": requested_entity,
        "comparison_found": comparison_found,
        "comparison_missing": comparison_missing,
        "intent_type": None,
        "mention_type": mention_type,
    }
