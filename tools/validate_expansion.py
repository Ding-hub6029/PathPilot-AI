"""Validate an expansion file (band file or merged expansion.json).

Run from the project root with the project venv (the promotion check
imports the evaluator, so plain system python is not enough):

    .venv/bin/python tools/validate_expansion.py data/expansions/expansion.json
    .venv/bin/python tools/validate_expansion.py data/expansions/collectors/rank-01-10.json

Checks (see data/expansions/README.md for the rules):
- file shape + data_version == "v3"
- institution ids exist in data/versions/v2/rankings.json
- programme ids unique, not colliding with v2 programme ids
- every referenced source id exists in the file's sources list
- no U.S. News strings anywhere (case-insensitive)
- no synthetic=true; matchable=true requires a wizard track
  (undergraduate / taught_masters) and at least one evaluable rule
  (see domain/expansion_eval.evaluable_rules) — the round-6 promotion
  rule, mirrored from backend/app/data.py
- required fields present; name_localized.zh-CN present
- application_status open/closed carries a source + as-of date
- stat percentages in 0-100, ratios > 0, founded year sane
- traceability rows exist for every sourced stat and every programme
  fee/requirement/deadline fact (checked by scope id + field name)
Exits 0 on success, 1 with a list of errors otherwise.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "data" / "versions" / "v2"

sys.path.insert(0, str(ROOT / "backend"))

from domain.expansion_eval import evaluable_rules  # noqa: E402

BANNED = re.compile(r"u\.?\s?s\.?\s?news", re.IGNORECASE)
ID_RE = re.compile(r"^[a-z0-9-]+$")
FIELDS = {
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
STAT_FIELDS = ("total_students", "student_faculty_ratio", "international_pct",
               "graduate_pct", "male_pct", "female_pct")


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _check_banned(obj, errors: list[str], where: str) -> None:
    text = json.dumps(obj, ensure_ascii=False)
    if BANNED.search(text):
        errors.append(f"{where}: contains a U.S. News reference (forbidden)")


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = _load(path)
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return [f"{path}: cannot load JSON: {exc}"]
    _check_banned(data, errors, str(path))
    if data.get("data_version") != "v3":
        errors.append(f"{path}: data_version must be 'v3', got {data.get('data_version')!r}")

    rankings = _load(V2_DIR / "rankings.json")
    ranking_ids = {i["id"] for i in rankings.get("institutions", [])}
    v2 = _load(V2_DIR / "programs.json")
    v2_ids = {p["id"] for p in v2.get("programs", [])}

    sources = data.get("sources", [])
    source_ids = set()
    for s in sources:
        if not s.get("id"):
            errors.append(f"{path}: source without id: {s}")
            continue
        if s["id"] in source_ids:
            errors.append(f"{path}: duplicate source id {s['id']!r}")
        source_ids.add(s["id"])
        if not s.get("url"):
            errors.append(f"{path}: source {s['id']!r} has no url")
        if not s.get("retrieved_at"):
            errors.append(f"{path}: source {s['id']!r} has no retrieved_at")

    trace = data.get("traceability", [])
    trace_keys = {(t.get("scope"), t.get("scope_id"), t.get("field")) for t in trace}

    for inst in data.get("institutions", []):
        iid = inst.get("institution_id")
        where = f"{path}: institution {iid!r}"
        if not iid or not ID_RE.match(str(iid)):
            errors.append(f"{where}: bad institution_id")
            continue
        if iid not in ranking_ids:
            errors.append(f"{where}: not in v2 rankings institutions")
        if not inst.get("official_name"):
            errors.append(f"{where}: missing official_name")
        if not inst.get("country_code") or not re.match(r"^[A-Z]{2}$", str(inst.get("country_code") or "")):
            errors.append(f"{where}: bad country_code")
        if not inst.get("last_verified_at"):
            errors.append(f"{where}: missing last_verified_at")
        stats = inst.get("stats")
        if not isinstance(stats, dict):
            errors.append(f"{where}: missing stats object")
            continue
        for field in STAT_FIELDS:
            stat = stats.get(field)
            if stat is None:
                continue  # unknown is allowed
            if not isinstance(stat, dict) or stat.get("value") is None:
                errors.append(f"{where}: stat {field} must be a sourced number or null")
                continue
            value = stat["value"]
            if not isinstance(value, (int, float)):
                errors.append(f"{where}: stat {field} value must be a number")
                continue
            if field.endswith("_pct") and not 0 <= value <= 100:
                errors.append(f"{where}: stat {field}={value} out of 0-100")
            if field == "student_faculty_ratio" and value <= 0:
                errors.append(f"{where}: stat {field}={value} must be > 0")
            if field == "total_students" and value <= 0:
                errors.append(f"{where}: stat {field}={value} must be > 0")
            if not stat.get("source_url") or not stat.get("retrieved_at"):
                errors.append(f"{where}: stat {field} needs source_url + retrieved_at")
            if ("institution", iid, f"stats.{field}") not in trace_keys:
                errors.append(f"{where}: stat {field} has no traceability row")
        fy = inst.get("founded_year")
        if fy is not None:
            if not isinstance(fy, dict) or not isinstance(fy.get("value"), int) or not 1000 <= fy["value"] <= 2026:
                errors.append(f"{where}: founded_year must be a sourced year 1000-2026")
            elif ("institution", iid, "founded_year") not in trace_keys:
                errors.append(f"{where}: founded_year has no traceability row")
        for tag in inst.get("membership_tags", []):
            if not tag.get("tag") or not tag.get("source_url") or not tag.get("retrieved_at"):
                errors.append(f"{where}: membership tag needs tag + source_url + retrieved_at")

    seen_ids: set[str] = set()
    for prog in data.get("programs", []):
        pid = prog.get("id")
        where = f"{path}: program {pid!r}"
        if not pid or not ID_RE.match(str(pid)):
            errors.append(f"{where}: bad id")
            continue
        if pid in seen_ids:
            errors.append(f"{where}: duplicate program id in this file")
        seen_ids.add(pid)
        if pid in v2_ids:
            errors.append(f"{where}: collides with a v2 program id — record additional programmes only")
        if prog.get("synthetic") is True:
            errors.append(f"{where}: synthetic=true is forbidden in real data")
        if not isinstance(prog.get("matchable"), bool):
            errors.append(f"{where}: matchable must be a boolean")
        elif prog.get("matchable") is True:
            # Round 6 promotion rule (mirrors backend/app/data.py):
            # matchable=true requires a wizard track (undergraduate /
            # taught_masters) and at least one evaluable rule (fee amount
            # known, structured IELTS/TOEFL threshold, or A-level
            # threshold). Foundation / joint_honours stay display-only
            # even with an evaluable rule — the wizard has no track for
            # them. Use tools/promote_expansion.py to (re)compute flags.
            if prog.get("degree_level") not in ("undergraduate", "taught_masters"):
                errors.append(
                    f"{where}: matchable=true requires degree_level "
                    f"undergraduate/taught_masters, got {prog.get('degree_level')!r}")
            elif not any(evaluable_rules(prog).values()):
                errors.append(
                    f"{where}: matchable=true requires at least one "
                    f"evaluable rule (fee / language / academic)")
        if prog.get("catalogue") != "expansion":
            errors.append(f"{where}: catalogue must be 'expansion'")
        if prog.get("institution_id") not in ranking_ids:
            errors.append(f"{where}: institution_id {prog.get('institution_id')!r} not in v2 rankings")
        if prog.get("field") not in FIELDS:
            errors.append(f"{where}: field {prog.get('field')!r} not in the controlled list")
        if prog.get("subject") != prog.get("field"):
            errors.append(f"{where}: subject must equal field")
        if not (prog.get("name_localized") or {}).get("zh-CN"):
            errors.append(f"{where}: name_localized.zh-CN is required")
        if not prog.get("official_name") or not prog.get("institution"):
            errors.append(f"{where}: missing official_name or institution")
        if prog.get("degree_level") not in ("undergraduate", "taught_masters", "foundation", "joint_honours"):
            errors.append(f"{where}: bad degree_level")
        fees = prog.get("fees") or {}
        if not fees.get("currency") or not fees.get("period"):
            errors.append(f"{where}: fees need currency + period")
        if fees.get("period") not in ("per_year", "total", "per_credit"):
            errors.append(f"{where}: bad fees.period")
        if fees.get("amount") is None and "unknown" not in str(fees.get("notes", "")).lower():
            errors.append(f"{where}: fees.amount null must be explained as unknown in fees.notes")
        status = prog.get("application_status")
        if status not in ("open", "closed", "unknown"):
            errors.append(f"{where}: bad application_status")
        if status in ("open", "closed") and (not prog.get("application_status_source") or not prog.get("application_status_as_of")):
            errors.append(f"{where}: application_status {status} needs source + as-of date")
        prog_sources = prog.get("sources") or []
        if not prog_sources:
            errors.append(f"{where}: at least one source is required")
        for s in prog_sources:
            if s.get("id") not in source_ids:
                errors.append(f"{where}: references unknown source {s.get('id')!r}")
        for req in prog.get("requirements", []):
            for sid in req.get("source_ids", []):
                if sid not in source_ids:
                    errors.append(f"{where}: requirement {req.get('id')!r} references unknown source {sid!r}")
        if ("program", pid, "fees") not in trace_keys:
            errors.append(f"{where}: fees have no traceability row")
        if prog.get("application_deadline") and ("program", pid, "application_deadline") not in trace_keys:
            errors.append(f"{where}: application_deadline has no traceability row")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <expansion-file.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    errors = validate(path)
    if errors:
        print(f"FAIL {path} ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
