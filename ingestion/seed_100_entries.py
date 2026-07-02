from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

# Add backend directory to sys.path so we can import settings and ingestion helpers
root_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_path / "backend"))
sys.path.insert(0, str(root_path))

import asyncpg
from settings import settings
from ingestion.microapp_to_db import upsert_university, upsert_course, upsert_specialization


# 10 Universities definition
UNIVERSITIES_DATA = [
    {"slug": "nmims", "name": "NMIMS", "full_name": "Narsee Monjee Institute of Management Studies", "year": "1981", "grade": "A+"},
    {"slug": "amity", "name": "Amity University", "full_name": "Amity University Online", "year": "2005", "grade": "A+"},
    {"slug": "manipal", "name": "Manipal University", "full_name": "Manipal Academy of Higher Education Online", "year": "1953", "grade": "A++"},
    {"slug": "lpu", "name": "LPU Online", "full_name": "Lovely Professional University Online", "year": "2005", "grade": "A++"},
    {"slug": "ignou", "name": "IGNOU", "full_name": "Indira Gandhi National Open University", "year": "1985", "grade": "A++"},
    {"slug": "chandigarh", "name": "Chandigarh University", "full_name": "Chandigarh University Online", "year": "2012", "grade": "A+"},
    {"slug": "dy-patil", "name": "DY Patil", "full_name": "Dr. D.Y. Patil Vidyapeeth Online", "year": "2003", "grade": "A++"},
    {"slug": "symbiosis", "name": "SCDL", "full_name": "Symbiosis Centre for Distance Learning", "year": "2001", "grade": "A"},
    {"slug": "jain", "name": "Jain University", "full_name": "Jain University Online", "year": "1990", "grade": "A+"},
    {"slug": "online-manipal", "name": "Sikkim Manipal", "full_name": "Sikkim Manipal University Online", "year": "1995", "grade": "A"},
]

# 3 Courses to be added per university (3 * 10 = 30 total courses)
COURSES_TEMPLATES = [
    {"slug_suffix": "online-mba", "name": "Online MBA", "duration": "2 Years", "fee": 200000, "start_fee": 50000},
    {"slug_suffix": "online-bba", "name": "Online BBA", "duration": "3 Years", "fee": 150000, "start_fee": 25000},
    {"slug_suffix": "online-mca", "name": "Online MCA", "duration": "2 Years", "fee": 180000, "start_fee": 45000},
]

# 2 Specializations to be added per course (2 * 30 = 60 total specializations)
SPECIALIZATIONS_MAP = {
    "online-mba": [
        {"slug_suffix": "finance", "name": "Financial Management", "fee": 220000},
        {"slug_suffix": "marketing", "name": "Marketing Management", "fee": 210000},
    ],
    "online-bba": [
        {"slug_suffix": "hr", "name": "Human Resource Management", "fee": 160000},
        {"slug_suffix": "retail", "name": "Retail Management", "fee": 155000},
    ],
    "online-mca": [
        {"slug_suffix": "data-science", "name": "Data Science", "fee": 195000},
        {"slug_suffix": "cloud", "name": "Cloud Computing", "fee": 190000},
    ],
}


async def seed():
    # Detect if we need localhost fallback (e.g. running from host but .env specifies db hostname)
    db_url = settings.database_url
    try:
        host = db_url.split("@")[1].split(":")[0]
        socket.gethostbyname(host)
    except (socket.gaierror, IndexError):
        print(f"Hostname '{host}' not resolvable, falling back to localhost...")
        db_url = db_url.replace("@db:", "@localhost:")

    print("Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        async with conn.transaction():
            print("Beginning seeding transaction...")
            
            univ_count = 0
            course_count = 0
            spec_count = 0

            for u in UNIVERSITIES_DATA:
                univ_payload = {
                    "slug": u["slug"],
                    "name": u["name"],
                    "full_name": u["full_name"],
                    "established_year": u["year"],
                    "naac_grade": u["grade"],
                    "ugc_approved": "Yes",
                    "mode_of_learning": "Online",
                    "starting_fee": f"₹50,000",
                    "num_programs": "10",
                    "about_content": f"About {u['name']} details.",
                    "why_choose_content": f"Why choose {u['name']} details.",
                    "admission_steps": "Fill application, upload docs, pay fee.",
                    "admission_fee_note": "Registration charges extra.",
                    "emi_content": "No cost EMI options available.",
                    "exam_content": "Proctored online examinations.",
                    "faculty_intro": "Experienced faculty panel.",
                    "placement_content": "100% placement assistance support.",
                    "seo_title": f"{u['name']} Online Admissions",
                    "meta_description": f"Admission guides for {u['name']}.",
                    "faqs": [
                        {"question": f"Is {u['name']} accredited?", "answer": f"Yes, NAAC grade is {u['grade']}."},
                        {"question": f"Does {u['name']} offer EMI?", "answer": "Yes, through partner banks."}
                    ]
                }
                _, univ_id = await upsert_university(conn, univ_payload)
                univ_count += 1

                for c in COURSES_TEMPLATES:
                    course_slug = f"{u['slug']}-{c['slug_suffix']}"
                    course_payload = {
                        "slug": course_slug,
                        "university_slug": u["slug"],
                        "program_name": f"{c['name']} ({u['name']})",
                        "duration": c["duration"],
                        "mode": "Online",
                        "naac_grade": u["grade"],
                        "ugc_status": "Approved",
                        "total_fee": f"₹{c['fee']:,}",
                        "starting_fee": f"₹{c['start_fee']:,}",
                        "num_specializations": "5",
                        "about_content": f"About {c['name']} at {u['name']}.",
                        "eligibility_content": "Graduation degree with 50% marks.",
                        "eligibility_summary": "Bachelor's degree in any stream.",
                        "admission_steps": "Apply on portal.",
                        "admission_fee_note": "Fee details subject to change.",
                        "syllabus_content": "Syllabus detailed content here.",
                        "placement_content": "Corporate tieups for placements.",
                        "certificate_description": "Accredited certificate on completion.",
                        "validity": "Lifetime validity",
                        "emi_amount": "EMI starts Rs 5,000/mo.",
                        "seo_title": f"Online {c['name']} - {u['name']}",
                        "meta_description": f"Enroll in online {c['name']} from {u['name']}.",
                        "faqs": [
                            {"question": "What is the duration?", "answer": f"It is a {c['duration']} program."}
                        ]
                    }
                    _, course_id = await upsert_course(conn, course_payload)
                    course_count += 1

                    specs = SPECIALIZATIONS_MAP[c["slug_suffix"]]
                    for s in specs:
                        spec_slug = f"{course_slug}-{s['slug_suffix']}"
                        spec_payload = {
                            "slug": spec_slug,
                            "university_slug": u["slug"],
                            "course_slug": course_slug,
                            "spec_name": f"{s['name']} specialization",
                            "duration": c["duration"],
                            "mode": "Online",
                            "naac_grade": u["grade"],
                            "ugc_status": "Approved",
                            "total_fee": f"₹{s['fee']:,}",
                            "about_content": f"Specialization details for {s['name']}.",
                            "eligibility_content": "Same as graduation criteria.",
                            "eligibility_summary": "Bachelor's degree required.",
                            "syllabus_content": "Accredited syllabus details.",
                            "exam_content": "Online proctored exams.",
                            "admission_steps": "Apply via course portal.",
                            "admission_fee_note": "Specialization fee included.",
                            "placement_content": "Placement opportunities in domain fields.",
                            "certificate_description": "Accredited degree specialization certificate.",
                            "emi_amount": "EMI starting at Rs 6,000/month."
                        }
                        await upsert_specialization(conn, spec_payload)
                        spec_count += 1

            print("Transaction complete!")
            print(f"Seeded: {univ_count} universities, {course_count} courses, {spec_count} specializations.")
            print(f"Total core entries created: {univ_count + course_count + spec_count}.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
