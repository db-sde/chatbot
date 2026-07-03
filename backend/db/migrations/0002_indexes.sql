CREATE INDEX IF NOT EXISTS idx_courses_university ON courses(university_id);
CREATE INDEX IF NOT EXISTS idx_courses_fee ON courses(total_fee);
CREATE INDEX IF NOT EXISTS idx_courses_mode ON courses(mode);
CREATE INDEX IF NOT EXISTS idx_specializations_course ON specializations(course_id);
CREATE INDEX IF NOT EXISTS idx_specializations_university ON specializations(university_id);
CREATE INDEX IF NOT EXISTS idx_faqs_entity ON faqs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_reviews_entity ON reviews(entity_type, entity_id);
