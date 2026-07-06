# Consolidated Migration Audit Report

This report outlines the migration consolidation process completed for the DegreeBaba chatbot platform. It documents the target schema, index list, extensions created, removed migrations, and risk mitigations.

---

## 1. Extensions Created
All three required PostgreSQL extensions are initialized idempotently:
1. `vector` — Supports high-dimensional search structures (reserved/unused).
2. `pgcrypto` — Standard cryptographic functions (used by UUID gen_random_uuid).
3. `pg_trgm` — Trigram parsing for ILIKE text-matching indexing.

---

## 2. Tables Created & Schema Consolidation

| Table Name | Consolidated Columns | Status |
| :--- | :--- | :--- |
| **`universities`** | `id`, `slug`, `name`, `full_name`, `established_year`, `naac_grade`, `ugc_approved`, `mode_of_learning`, `starting_fee`, `num_programs`, `about_content`, `why_choose_content`, `admission_steps`, `admission_fee_note`, `emi_content`, `exam_content`, `faculty_intro`, `placement_content`, `seo_title`, `meta_description`, `raw_json`, `created_at`, `updated_at` | Active (Seed populated) |
| **`courses`** | `id`, `slug`, `university_id` (FK), `program_name`, `duration`, `mode`, `naac_grade`, `ugc_status`, `total_fee`, `starting_fee`, `num_specializations`, `about_content`, `eligibility_content`, `eligibility_summary`, `admission_steps`, `admission_fee_note`, `syllabus_content`, `placement_content`, `certificate_description`, `validity`, `emi_amount`, `seo_title`, `meta_description`, `raw_json`, `created_at`, `updated_at` | Active (Seed populated) |
| **`specializations`** | `id`, `slug`, `course_id` (FK), `university_id` (FK), `spec_name`, `duration`, `mode`, `naac_grade`, `ugc_status`, `total_fee`, `about_content`, `eligibility_content`, `eligibility_summary`, `syllabus_content`, `exam_content`, `admission_steps`, `admission_fee_note`, `placement_content`, `certificate_description`, `emi_amount`, `seo_title`, `meta_description`, `raw_json`, `created_at`, `updated_at` | Active (Seed populated) |
| **`faqs`** | `id`, `entity_type`, `entity_id`, `question`, `answer` | Dead Schema Table |
| **`reviews`** | `id`, `entity_type`, `entity_id`, `review_text`, `reviewer_name`, `reviewer_label` | Dead Schema Table |
| **`job_profiles`** | `id`, `entity_type`, `entity_id`, `job_title`, `avg_salary` | Dead Schema Table |
| **`highlights`** | `id`, `entity_type`, `entity_id`, `highlight_title`, `highlight_description` | Dead Schema Table |
| **`fee_plans`** | `id`, `course_id` (FK), `plan_name`, `plan_amount`, `plan_total` | Dead Schema Table |
| **`faculty_members`** | `id`, `university_id` (FK), `member_name`, `member_program`, `member_designation`, `member_qualification` | Dead Schema Table |
| **`accreditations`** | `id`, `university_id` (FK), `body_name`, `body_descriptor`, `body_detail` | Dead Schema Table |
| **`facts`** | `id`, `university_id` (FK), `fact_title`, `fact_description` | Dead Schema Table |
| **`other_specs`** | `id`, `specialization_id` (FK), `other_spec_name`, `other_spec_fee` | Dead Schema Table |
| **`entity_search`** | `id`, `entity_type`, `entity_id`, `search_text` | Active (Trigram matched) |
| **`sessions`** | `id`, `site_id`, `page_university_slug`, `summary`, `started_at`, `last_active_at`, `message_count`, `ip_address`, `user_agent`, `lead_intent_detected`, `lead_intent_type`, `lead_intent_confidence`, `lead_intent_reasoning`, `lead_ask_triggered_by` | Active |
| **`session_context`** | `session_id` (PK, FK), `current_university_slug`, `current_course_slug`, `current_specialization_slug`, `last_updated` | Active |
| **`messages`** | `id`, `session_id` (FK), `role`, `content`, `tool_calls`, `created_at`, `response_time_ms`, `ttft_ms`, `model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `estimated_cost_usd`, `tool_execution_time_ms`, `started_at`, `completed_at` | Active (Observability) |
| **`leads`** | `id`, `session_id` (FK), `name`, `phone`, `email`, `course_interest`, `trigger_reason`, `created_at` | Active |
| **`lead_score_events`** | `id`, `session_id` (FK), `event_type`, `points`, `created_at` | Active |
| **`lead_asks`** | `session_id` (PK, FK), `asked_at` | Active |
| **`unanswered_questions`** | `id`, `question`, `session_id` (FK), `university_slug`, `course_slug`, `reason`, `created_at` | Active |
| **`content_chunks`** | `id`, `source_url`, `chunk_text`, `embedding` (768), `updated_at` | Dead Schema Table |
| **`flagged_messages`** | `id`, `session_id` (FK), `message`, `layer`, `risk_score`, `reason`, `created_at` | Active |
| **`widget_settings`** | `site_id` (PK), `show_estimated_wait_time`, `sound_notifications`, `desktop_notifications`, `mobile_message_preview`, `agent_typing_indicator`, `visitor_typing_indicator`, `browser_tab_notifications`, `hide_when_offline`, `hide_on_desktop`, `hide_on_mobile`, `offline_if_no_agents`, `emoji_picker_enabled`, `file_upload_enabled`, `chat_rating_enabled`, `email_transcript_enabled`, `updated_at`, `updated_by`, `primary_color`, `widget_title`, `bot_name`, `welcome_message`, `logo_url`, `show_on_mobile`, `show_on_desktop`, `lead_capture_enabled`, `capture_name`, `capture_email`, `capture_phone`, `lead_trigger`, `lead_form_title`, `lead_form_description` | Active |
| **`security_events`** | `id`, `created_at`, `ip_address`, `user_agent`, `session_id`, `event_type`, `severity`, `payload`, `source`, `action_taken`, `blocked`, `metadata_json`, `country` | Active |
| **`blocked_ips`** | `id`, `ip_address` (Unique), `reason`, `blocked_by`, `created_at`, `expires_at`, `is_active`, `block_type` | Active |

---

## 3. Indexes Created
1. `idx_entity_search_type` on `entity_search(entity_type)`
2. `idx_entity_search_entity` (Unique) on `entity_search(entity_type, entity_id)`
3. `idx_flagged_messages_layer` on `flagged_messages(layer)`
4. `idx_flagged_messages_session` on `flagged_messages(session_id)`
5. `idx_flagged_messages_created_at` on `flagged_messages(created_at DESC)`
6. `idx_unanswered_session` on `unanswered_questions(session_id)`
7. `idx_unanswered_created_at` on `unanswered_questions(created_at DESC)`
8. `idx_sessions_ip` on `sessions(ip_address)`
9. `idx_messages_observability` on `messages(session_id, created_at DESC)`
10. `idx_sessions_lead_intent` on `sessions(lead_intent_detected) WHERE lead_intent_detected = TRUE`
11. `idx_courses_university` on `courses(university_id)`
12. `idx_courses_fee` on `courses(total_fee)`
13. `idx_courses_mode` on `courses(mode)`
14. `idx_specializations_course` on `specializations(course_id)`
15. `idx_specializations_university` on `specializations(university_id)`
16. `idx_faqs_entity` on `faqs(entity_type, entity_id)`
17. `idx_reviews_entity` on `reviews(entity_type, entity_id)`
18. `idx_sessions_site_id` on `sessions(site_id)`
19. `idx_messages_created_at` on `messages(created_at)`
20. `idx_sessions_university` on `sessions(page_university_slug)`
21. `idx_sessions_last_active` on `sessions(last_active_at DESC)`
22. `idx_messages_role_model` on `messages(role, model_name)`
23. `idx_leads_session` on `leads(session_id)`
24. `idx_lead_score_events_session` on `lead_score_events(session_id)`
25. `idx_entity_search_text_trgm` (GIN) on `entity_search(search_text gin_trgm_ops)`
26. `idx_security_events_created_at` on `security_events(created_at DESC)`
27. `idx_security_events_ip_address` on `security_events(ip_address)`
28. `idx_security_events_event_type` on `security_events(event_type)`
29. `idx_security_events_severity` on `security_events(severity)`
30. `idx_security_events_blocked` on `security_events(blocked)`
31. `idx_blocked_ips_ip_address` on `blocked_ips(ip_address)`
32. `idx_blocked_ips_is_active` on `blocked_ips(is_active)`
33. `idx_blocked_ips_expires_at` on `blocked_ips(expires_at)`

---

## 4. Removed Legacy Migration Files
The following 13 SQL migrations were successfully deleted from `backend/db/migrations/`:
* `0002_indexes.sql`
* `0002_security.sql`
* `0003_flagged_messages.sql`
* `0003_session_metadata.sql`
* `0004_observability.sql`
* `0004_perf_indexes.sql`
* `0005_lead_intent.sql`
* `0006_perf_indexes_v2.sql`
* `0007_widget_settings.sql`
* `0008_remove_embedding.sql`
* `0009_simplify_widget_settings.sql`
* `0010_security_events.sql`
* `0011_add_security_event_country.sql`

---

## 5. Potential Risks & Mitigation

1. **Risk:** Schema changes might not be run on existing local/staging databases if `schema_migrations` already has a record for `0001_init.sql` but not the newer migrations.
   * **Mitigation:** The consolidation is designed for clean setups (and staging databases can simply run `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` to re-initialize). Furthermore, the entire schema DDL utilizes `IF NOT EXISTS` constructs to safely allow manual executions against existing database instances.
2. **Risk:** Missing schema constraints or renamed columns.
   * **Mitigation:** Comprehensive audit verified that all tables, foreign keys, cascades, columns (e.g. `estimated_cost_usd` NUMERIC(12,8) and `lead_intent_detected` columns), indices, and extensions exist exactly as configured in the previous sequence of migrations.
