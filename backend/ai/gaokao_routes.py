"""Verified Gaokao (高考) facts for the AI layer (Day 3, DECISIONS #105).

Source: ~/workspace/gaokao_research.md (research pass 2026-11-25, official
pages only). Every fact carries the URL it was read from; facts whose URL
was NOT re-captured in that pass carry ``url=None`` and ``url_verified``
False — the model may state them in prose but must never present them as
a link, and the citation checker never resolves them to a URL. Nothing
here is a conversion table: no university publishes a Gaokao % -> A-level
grade-band mapping, so none is invented. Unknown stays unknown (Oxford).
"""
from __future__ import annotations

# Each fact: id, topic, text (English; the model translates it into the
# user's locale), url (or None), url_verified, applies_to.
GAOKAO_FACTS: list[dict] = [
    {
        "id": "gaokao-ucl-cs-no-route",
        "topic": "gaokao_route",
        "text": "UCL Computer Science BSc has no published Gaokao direct-entry route. "
                "UCL's published China routes are A-levels (ABB minimum generally; "
                "A*A*A for this course), IB (36 generally; 40 for this course), or "
                "one year of a bachelor's degree at a recognised Chinese university "
                "at 90%.",
        "url": "https://www.ucl.ac.uk/study/international/region/east-asia/china",
        "url_verified": True,
        "applies_to": ["ucl-cs-bsc-2026"],
    },
    {
        "id": "gaokao-ucl-upc",
        "topic": "gaokao_route",
        "text": "UCL's Undergraduate Preparatory Certificate (UPC) is the foundation "
                "route for students whose qualification UCL does not accept. UPCSE "
                "overall 70% with 76% in each core science unit maps to A*A*A for "
                "Computer Science BSc. Apply direct to UCL (not via UCAS); general "
                "deadline 18 June 2027; entrance tests and interview apply.",
        "url": None,
        "url_verified": False,
        "applies_to": ["ucl-cs-bsc-2026"],
    },
    {
        "id": "gaokao-imperial-not-accepted",
        "topic": "gaokao_route",
        "text": "Imperial College London does not accept the Gaokao for any degree, "
                "including Computing BEng. The official remedy is an accepted "
                "foundation programme or another accepted qualification; no specific "
                "foundation provider is named on the page.",
        "url": "https://www.imperial.ac.uk/study/international-students/information-by-region/east-asia/",
        "url_verified": True,
        "applies_to": ["imperial-comp-beng-2027"],
    },
    {
        "id": "gaokao-birmingham-80",
        "topic": "gaokao_route",
        "text": "University of Birmingham accepts Gaokao for direct entry: at least "
                "80% overall average (80% in Mathematics where A-level Maths is "
                "required), plus the Senior Secondary School Graduation Certificate "
                "at 85% overall. Note: the province table on that page is labelled "
                "for students who sat the Gaokao in 2025 or earlier.",
        "url": "https://www.birmingham.ac.uk/international/students/country/china/gaokao",
        "url_verified": True,
        "applies_to": [],
    },
    {
        "id": "gaokao-sheffield-75-70-65",
        "topic": "gaokao_route",
        "text": "University of Sheffield accepts Gaokao for direct entry: AAA+ "
                "courses 75% overall or above; AAB-ABB 70%; BBB-BBC 65%.",
        "url": None,
        "url_verified": False,
        "applies_to": [],
    },
    {
        "id": "gaokao-leeds-75-85",
        "topic": "gaokao_route",
        "text": "University of Leeds accepts Gaokao plus senior high school: "
                "subject-specific Gaokao 75-85%, plus senior high school Year 1-2 "
                "average 80% with at least 80% in relevant subjects.",
        "url": None,
        "url_verified": False,
        "applies_to": [],
    },
    {
        "id": "gaokao-southampton-80-75-70",
        "topic": "gaokao_route",
        "text": "University of Southampton accepts Gaokao for many degrees: A*AA/AAA "
                "80%; AAB 75%; ABB/BBB/BBC/BCC/CCC 70%. Not accepted for Faculty of "
                "Engineering and Physical Sciences degrees or medicine.",
        "url": None,
        "url_verified": False,
        "applies_to": [],
    },
    {
        "id": "gaokao-york-75",
        "topic": "gaokao_route",
        "text": "University of York accepts Gaokao with a minimum 75% overall average "
                "for Year 1 entry (courses without other essential subject "
                "requirements), plus the Senior High School Graduation Certificate.",
        "url": None,
        "url_verified": False,
        "applies_to": [],
    },
    {
        "id": "gaokao-cardiff-85",
        "topic": "gaokao_route",
        "text": "Cardiff University accepts Gaokao for direct entry, requiring the "
                "Gaokao score plus the Senior Secondary School Graduation Certificate "
                "at 85% overall (Years 11-12) including 85% in relevant subjects, "
                "plus English language requirements.",
        "url": None,
        "url_verified": False,
        "applies_to": [],
    },
    {
        "id": "gaokao-lse-ast",
        "topic": "gaokao_route",
        "text": "LSE accepts Gaokao combined with AST (Aptitude Scholastic Test) "
                "scores: A = 210, A* = 250 per subject; Mathematics A*/A requires "
                "250 in Mathematics. The senior high school diploma alone is not "
                "acceptable at LSE.",
        "url": "https://www.lse.ac.uk/study-at-lse/international-students/china",
        "url_verified": True,
        "applies_to": [],
    },
    {
        "id": "gaokao-cambridge-top-01",
        "topic": "gaokao_route",
        "text": "Cambridge generally makes Gaokao applicants an offer of a rank in "
                "the top 0.1% of those taking the Gaokao in their province (a rank, "
                "not a percentage). Colleges differ.",
        "url": "https://www.trin.cam.ac.uk/undergraduate/applying/overseas-qualifications/",
        "url_verified": True,
        "applies_to": [],
    },
    {
        "id": "gaokao-oxford-unknown",
        "topic": "gaokao_route",
        "text": "Whether Oxford accepts Gaokao is unknown: its international "
                "qualifications page could not be read in the research pass. Do not "
                "claim it is accepted or not accepted.",
        "url": "https://www.ox.ac.uk/admissions/undergraduate/courses/admissions-requirements/international-qualifications",
        "url_verified": True,
        "applies_to": [],
    },
    {
        "id": "gaokao-ucas-no-tariff",
        "topic": "gaokao_route",
        "text": "Gaokao attracts no UCAS Tariff points: UCAS's own qualification "
                "information states this qualification does not currently attract "
                "UCAS Tariff points.",
        "url": "https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications",
        "url_verified": True,
        "applies_to": [],
    },
    {
        "id": "gaokao-tmua-imperial",
        "topic": "extra_exam",
        "text": "TMUA (Test of Mathematics for University Admission) is required for "
                "Imperial Computing BEng and joint Maths/CS. China/Hong Kong/Macau "
                "test windows: 15-16 October 2026 and 8 January 2027. No published "
                "cut-off score (no pass or fail).",
        "url": "https://www.imperial.ac.uk/study/apply/undergraduate/process/admissions-tests/tmua/",
        "url_verified": True,
        "applies_to": ["imperial-comp-beng-2027"],
    },
    {
        "id": "gaokao-tara-ucl-required",
        "topic": "extra_exam",
        "text": "TARA (Test of Academic Reasoning for Admissions) is required for "
                "UCL Computer Science BSc for 2027/28 admission, alongside the "
                "UCAS application. TARA is run by University Admissions Tests UK.",
        "url": "https://www.ucl.ac.uk/study/prospective-students/undergraduate/courses/computer-science-bsc",
        "url_verified": True,
        "applies_to": ["ucl-cs-bsc-2026"],
    },
    {
        "id": "gaokao-ucas-deadlines",
        "topic": "extra_exam",
        "text": "UCAS equal-consideration deadlines for 2027 entry: 15 October 2026 "
                "for Oxford, Cambridge and most medicine/dentistry/veterinary "
                "courses; 13 January 2027 for most undergraduate courses, including "
                "UCL CS BSc and Imperial Computing BEng. Maximum 5 choices.",
        "url": "https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications",
        "url_verified": True,
        "applies_to": [],
    },
]


def facts_for_program(program_id: str | None) -> list[dict]:
    """Gaokao facts for one programme first, then the general routes."""
    specific = [f for f in GAOKAO_FACTS if program_id and program_id in f["applies_to"]]
    general = [f for f in GAOKAO_FACTS if not f["applies_to"]]
    return specific + general


def all_facts() -> list[dict]:
    return list(GAOKAO_FACTS)
