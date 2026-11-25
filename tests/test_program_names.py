"""Programme display names (Issue 2, 2026-11-25 user testing).

name_localized is a presentation-layer field: the official English title
(official_name) is never overwritten, and a locale without an entry falls
back to it. The zh-CN values use the standard Chinese degree-name
convention; institution Chinese names match the user-supplied THE/ARWU
tables. The frontend mirror (src/lib/programs.ts) must carry the same
values as data/versions/v2/programs.json.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "versions" / "v2" / "programs.json"
MIRROR = ROOT / "frontend" / "src" / "lib" / "programs.ts"

EXPECTED_OFFICIAL = {
    "ucl-cs-bsc-2026": "Computer Science BSc",
    "nus-mcomp-cs": "Master of Computing (Computer Science specialisation)",
    "imperial-comp-beng-2027": "Computing BEng",
    "imperial-msc-computing-2027": "Computing MSc",
    "ucl-cs-msc-2027": "Computer Science MSc",
    "nus-bcomp-cs-2027": "Bachelor of Computing (Computer Science)",
    "ntu-bcomp-cs-2027": "Bachelor of Computing (Hons) in Computer Science",
    "ntu-msai-2027": "Master of Science in Artificial Intelligence (MSAI)",
}

EXPECTED_ZH = {
    "ucl-cs-bsc-2026": "计算机科学理学学士",
    "nus-mcomp-cs": "计算机硕士（计算机科学方向）",
    "imperial-comp-beng-2027": "计算机工程学士",
    "imperial-msc-computing-2027": "计算机理学硕士",
    "ucl-cs-msc-2027": "计算机科学理学硕士",
    "nus-bcomp-cs-2027": "计算机学士（计算机科学）",
    "ntu-bcomp-cs-2027": "计算机学士（荣誉，计算机科学）",
    "ntu-msai-2027": "人工智能理学硕士",
}

LOCALES = ["zh-CN", "es", "fr", "pt-BR", "ar"]


def _load():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["programs"]}


def test_official_names_unchanged():
    progs = _load()
    assert set(progs) == set(EXPECTED_OFFICIAL)
    for pid, name in EXPECTED_OFFICIAL.items():
        assert progs[pid]["official_name"] == name, pid


def test_name_localized_present_for_all_locales():
    progs = _load()
    for pid, prog in progs.items():
        loc = prog.get("name_localized")
        assert isinstance(loc, dict), pid
        for locale in LOCALES:
            val = loc.get(locale)
            assert isinstance(val, str) and val.strip(), f"{pid} {locale}"
            assert val != prog["official_name"], f"{pid} {locale} must differ from English"
        assert loc["zh-CN"] == EXPECTED_ZH[pid], pid


def test_mirror_carries_same_localized_names():
    mirror = MIRROR.read_text(encoding="utf-8")
    for pid, zh in EXPECTED_ZH.items():
        assert zh in mirror, f"{pid}: {zh} missing from frontend mirror"
    assert mirror.count("nameLocalized") >= 8


def test_render_sites_use_display_helpers():
    """Programme titles must render through displayProgramName/Title, never
    raw officialName, on every page that shows a programme title."""
    pages = [
        ROOT / "frontend" / "src" / "app" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "wizard" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "results" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "report" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "institutions" / "[id]" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "programs" / "[id]" / "page.tsx",
    ]
    for page in pages:
        src = page.read_text(encoding="utf-8")
        assert "displayProgramName" in src or "displayProgramTitle" in src, page
        # No raw {p.officialName} / {program.officialName} left in JSX.
        assert not re.search(r"\{p\.officialName\}|\{program\.officialName\}", src), page
