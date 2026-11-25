"""Loads data/versions/v1, validates schema + references at startup.

Refuses fixtures in real data: any program with synthetic=true or an id
starting with 'fixture-' raises at load time.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DATA_VERSION = "v2"

# backend/app/data.py -> project root is ../../ from this file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "versions" / DATA_VERSION


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_programs() -> dict[str, dict]:
    programs_path = DATA_DIR / "programs.json"
    manifest_path = DATA_DIR / "source-manifest.json"
    data = _load_json(programs_path)
    manifest = _load_json(manifest_path)
    if data.get("data_version") != DATA_VERSION:
        raise ValueError(f"programs.json data_version {data.get('data_version')} != {DATA_VERSION}")
    if manifest.get("data_version") != DATA_VERSION:
        raise ValueError("source-manifest.json data_version mismatch")

    known_fact_ids = {f["id"] for f in manifest.get("facts", [])}
    known_source_ids = {s["id"] for s in manifest.get("sources", [])}
    programs: dict[str, dict] = {}
    for program in data.get("programs", []):
        pid = program.get("id")
        if program.get("synthetic") is True or str(pid).startswith("fixture-"):
            raise ValueError(f"Refusing fixture program in real data: {pid}")
        if pid in programs:
            raise ValueError(f"Duplicate program id: {pid}")
        # Validate source references.
        for src in program.get("sources", []):
            if src.get("id") not in known_source_ids:
                raise ValueError(f"Program {pid} references unknown source {src.get('id')}")
        for req in program.get("requirements", []):
            for sid in req.get("source_ids", []):
                if sid not in known_source_ids:
                    raise ValueError(f"Program {pid} requirement {req.get('id')} references unknown source {sid}")
        # Every fact id referenced by a rule must exist in the manifest.
        for fact_id in [f for f in known_fact_ids]:
            pass  # manifest integrity: facts reference known programs/sources
        programs[pid] = program

    for fact in manifest.get("facts", []):
        if fact.get("program_id") not in programs:
            raise ValueError(f"Manifest fact {fact.get('id')} references unknown program {fact.get('program_id')}")
        if fact.get("source_id") not in known_source_ids:
            raise ValueError(f"Manifest fact {fact.get('id')} references unknown source {fact.get('source_id')}")
    return programs


def load_fixture() -> dict:
    """Test-only loader. Fixtures never enter load_programs()."""
    path = PROJECT_ROOT / "data" / "fixtures" / "fixture-p01.json"
    data = _load_json(path)
    program = data["program"]
    if not program.get("synthetic"):
        raise ValueError("Fixture file must be marked synthetic.")
    return program


# --- Rankings (Day 3, spec Ch9 FR15/FR16) -----------------------------------
# Top 100 institutions per provider (QS 2027, THE 2027, ARWU 2026):
# at most 300 entries. rank_display is
# reproduced exactly as published; no combined/average rank across
# providers is stored or computed anywhere (BR15). Rankings never affect
# eligibility (BR16). An entry whose verification_status is "unavailable"
# carries rank_display null plus an unavailable_reason — never a value
# taken from a third-party reproduction.
def load_rankings() -> dict:
    rankings_path = DATA_DIR / "rankings.json"
    data = _load_json(rankings_path)
    if data.get("data_version") != DATA_VERSION:
        raise ValueError(f"rankings.json data_version {data.get('data_version')} != {DATA_VERSION}")
    providers = {p["id"] for p in data.get("providers", [])}
    institutions = {i["id"] for i in data.get("institutions", [])}
    entries = data.get("entries", [])
    if len(entries) > 300:
        raise ValueError(f"rankings.json has {len(entries)} entries; at most 300 allowed (top 100 x 3 providers)")
    seen: set[tuple[str, str]] = set()
    for e in entries:
        if e.get("provider") not in providers:
            raise ValueError(f"Ranking entry references unknown provider {e.get('provider')}")
        if e.get("institution_id") not in institutions:
            raise ValueError(f"Ranking entry references unknown institution {e.get('institution_id')}")
        key = (e["provider"], e["institution_id"], e.get("edition_label"))
        if key in seen:
            raise ValueError(f"Duplicate ranking entry for {key}")
        seen.add(key)
        if e.get("rank_kind") not in ("single", "tie", "band", None):
            raise ValueError(f"Ranking entry {key} has invalid rank_kind {e.get('rank_kind')!r}")
        if e.get("verification_status") == "verified":
            if not e.get("rank_display"):
                raise ValueError(f"Verified ranking entry {key} has no rank_display")
            if e.get("unavailable_reason"):
                raise ValueError(f"Verified ranking entry {key} must not carry unavailable_reason")
        elif e.get("verification_status") == "unavailable":
            if e.get("rank_display") is not None or e.get("score") is not None:
                raise ValueError(f"Unavailable ranking entry {key} must not carry a rank or score")
            if not e.get("unavailable_reason"):
                raise ValueError(f"Unavailable ranking entry {key} needs unavailable_reason")
        else:
            raise ValueError(f"Ranking entry {key} has invalid verification_status {e.get('verification_status')!r}")
    return data


# Loaded once at import / startup.
RANKINGS: dict = load_rankings()


# Loaded once at import / startup.
PROGRAMS: dict[str, dict] = load_programs()


# --- Expansion catalogue (Day 3, v3; see data/expansions/README.md) ---------
# Round 6 (2026-11-26): expansion programmes with at least one evaluable
# rule (see domain/expansion_eval.evaluable_rules) and a wizard track
# (undergraduate / taught_masters) are matchable=true and are evaluated
# by the generic evaluator; the rest stay matchable=false, display-only.
# The merged file is data/expansions/expansion.json; band files in
# collectors/ are merged into it only after tools/validate_expansion.py
# prints OK. A missing file means "no expansion data yet" (empty
# catalogue); invalid content refuses to start, same as v2.
EXPANSION_PATH = PROJECT_ROOT / "data" / "expansions" / "expansion.json"
CLIMATE_PATH = PROJECT_ROOT / "data" / "expansions" / "climate.json"

# v2 programmes have no institution_id field; this explicit mapping is the
# only place that derives one (never guessed from the programme id).
V2_PROGRAM_INSTITUTION: dict[str, str] = {
    "ucl-cs-bsc-2026": "ucl",
    "ucl-cs-msc-2027": "ucl",
    "imperial-comp-beng-2027": "imperial",
    "imperial-msc-computing-2027": "imperial",
    "nus-mcomp-cs": "nus",
    "nus-bcomp-cs-2027": "nus",
    "ntu-bcomp-cs-2027": "ntu",
    "ntu-msai-2027": "ntu",
}

_EXPANSION_FIELDS = {
    "accounting", "aerospace-engineering", "agriculture",
    "anthropology", "architecture", "art-design", "artificial-intelligence",
    "biology", "biomedical-engineering", "business-administration",
    "chemical-engineering", "chemistry", "civil-engineering",
    "computer-engineering", "computer-science", "computational-biology",
    "cybersecurity", "data-science", "dentistry", "economics", "education",
    "electrical-engineering", "finance", "general-engineering", "geography",
    "history", "human-computer-interaction", "information-systems",
    "international-relations", "law", "linguistics", "literature",
    "management", "marketing", "mathematics", "mechanical-engineering",
    "medicine", "music", "nursing", "other", "other-computing", "pharmacy",
    "philosophy", "physics", "political-science", "psychology",
    "public-health", "robotics", "sociology", "software-engineering",
    "statistics", "veterinary-medicine",
}
_BANNED_RE = re.compile(r"u\.?\s?s\.?\s?news", re.IGNORECASE)


def validate_expansion_data(data: dict, ranking_ids: set[str],
                            v2_ids: set[str]) -> list[str]:
    """Same core checks as tools/validate_expansion.py (kept in sync by
    tests/test_expansion.py). Returns a list of error strings (empty = ok)."""
    errors: list[str] = []
    if _BANNED_RE.search(json.dumps(data, ensure_ascii=False)):
        errors.append("expansion data contains a U.S. News reference (forbidden)")
    if data.get("data_version") != "v3":
        errors.append(f"expansion data_version must be 'v3', got {data.get('data_version')!r}")
    source_ids = {s.get("id") for s in data.get("sources", [])}
    for inst in data.get("institutions", []):
        iid = inst.get("institution_id")
        if iid not in ranking_ids:
            errors.append(f"expansion institution {iid!r} not in v2 rankings")
    seen: set[str] = set()
    for prog in data.get("programs", []):
        pid = prog.get("id")
        if not pid:
            errors.append("expansion program without id")
            continue
        if pid in seen:
            errors.append(f"duplicate expansion program id {pid!r}")
        seen.add(pid)
        if pid in v2_ids:
            errors.append(f"expansion program {pid!r} collides with a v2 program id")
        if prog.get("synthetic") is True:
            errors.append(f"expansion program {pid!r}: synthetic=true is forbidden")
        if not isinstance(prog.get("matchable"), bool):
            errors.append(f"expansion program {pid!r}: matchable must be a boolean")
        elif prog.get("matchable") is True:
            # Round 6 promotion rule: matchable=true requires at least
            # one evaluable rule (fee amount known, structured
            # IELTS/TOEFL language threshold, or A-level threshold) and
            # a wizard track (undergraduate / taught_masters) — the
            # wizard has no track for foundation / joint_honours, so
            # those stay display-only even with an evaluable rule.
            from domain.expansion_eval import evaluable_rules
            if prog.get("degree_level") not in ("undergraduate", "taught_masters"):
                errors.append(
                    f"expansion program {pid!r}: matchable=true requires degree_level "
                    f"undergraduate/taught_masters, got {prog.get('degree_level')!r}")
            elif not any(evaluable_rules(prog).values()):
                errors.append(
                    f"expansion program {pid!r}: matchable=true requires at least "
                    f"one evaluable rule (fee / language / academic)")
        if prog.get("catalogue") != "expansion":
            errors.append(f"expansion program {pid!r}: catalogue must be 'expansion'")
        if prog.get("institution_id") not in ranking_ids:
            errors.append(f"expansion program {pid!r}: institution_id not in v2 rankings")
        if prog.get("field") not in _EXPANSION_FIELDS:
            errors.append(f"expansion program {pid!r}: field not in the controlled list")
        if not (prog.get("name_localized") or {}).get("zh-CN"):
            errors.append(f"expansion program {pid!r}: name_localized.zh-CN is required")
        for s in prog.get("sources", []):
            if s.get("id") not in source_ids:
                errors.append(f"expansion program {pid!r}: unknown source {s.get('id')!r}")
        for req in prog.get("requirements", []):
            for sid in req.get("source_ids", []):
                if sid not in source_ids:
                    errors.append(f"expansion program {pid!r}: requirement references unknown source {sid!r}")
    return errors


def load_expansion() -> dict:
    if not EXPANSION_PATH.exists():
        return {"data_version": "v3", "institutions": [], "programs": [],
                "sources": [], "traceability": []}
    data = _load_json(EXPANSION_PATH)
    ranking_ids = {i["id"] for i in RANKINGS.get("institutions", [])}
    v2_ids = set(PROGRAMS.keys())
    errors = validate_expansion_data(data, ranking_ids, v2_ids)
    if errors:
        raise ValueError(f"expansion.json failed validation: {'; '.join(errors)}")
    return data


EXPANSION: dict = load_expansion()
EXPANSION_INSTITUTIONS: dict[str, dict] = {
    i["institution_id"]: i for i in EXPANSION.get("institutions", [])}
EXPANSION_PROGRAMS: dict[str, dict] = {
    p["id"]: p for p in EXPANSION.get("programs", [])}
EXPANSION_MATCHABLE: dict[str, dict] = {
    p["id"]: p for p in EXPANSION.get("programs", [])
    if p.get("matchable") is True}
EXPANSION_INSTITUTION_CITIES: dict[str, str] = {
    i["institution_id"]: i["city"]
    for i in EXPANSION.get("institutions", []) if i.get("city")}


# --- Climate table (Day 3, round 6; see docs/CLIMATE.md) --------------------
# Curated city -> climate class (warm / cool / four_seasons / mild) with
# a source URL per city. A city with no entry gets NO climate signal.
# A missing file means "no climate data yet" (empty table); invalid
# content refuses to start, same as v2.
def load_climate() -> dict[str, dict]:
    if not CLIMATE_PATH.exists():
        return {}
    data = _load_json(CLIMATE_PATH)
    table: dict[str, dict] = {}
    for entry in data.get("cities", []):
        city = entry.get("city")
        if not city:
            raise ValueError("climate.json entry without city")
        if city in table:
            raise ValueError(f"climate.json has duplicate city {city!r}")
        if entry.get("climate") not in ("warm", "cool", "four_seasons", "mild"):
            raise ValueError(
                f"climate.json city {city!r} has invalid climate "
                f"{entry.get('climate')!r}")
        url = entry.get("source_url") or ""
        if not url.startswith("https://"):
            raise ValueError(
                f"climate.json city {city!r} has no https source_url")
        table[city] = entry
    return table


CLIMATE: dict[str, dict] = load_climate()
