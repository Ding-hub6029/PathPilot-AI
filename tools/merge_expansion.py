"""Merge validated collector band files into data/expansions/expansion.json.

Official-sources-only merge: any fact citing a blocked (aggregator /
Wikipedia / ranking-provider) domain is never merged as verified. The
merge is incremental — already-merged band files are skipped — so run it
again as each new band lands:

    .venv/bin/python tools/merge_expansion.py
    .venv/bin/python tools/merge_expansion.py data/expansions/collectors/rank-26-50.json

Rules (see data/expansions/README.md):
- Institution profile: kept, but any stat / founded_year / intro /
  address / membership tag / photo citing a blocked domain is nulled or
  dropped (the stat stays unknown, never laundered).
- Programme: kept only if, after stripping, nothing it cites is blocked.
  A requirement citing a blocked source loses that source id (mixed
  sources) or is dropped entirely (blocked-only sources). A programme
  whose fee traceability row cites a blocked domain is held whole; a
  deadline citing a blocked domain is nulled (unknown) and the programme
  is kept, with the strip recorded.
- Held programmes / institutions are listed in the printed report and in
  data/expansions/hold-list.md for a re-verification pass. Nothing held
  is silently dropped: the band file keeps the original record.
- Source ids are deduplicated across bands (same id + same URL merges;
  same id + different URL gets a band suffix and references are remapped).
- The merged file is validated with tools/validate_expansion.py before it
  is written; on validation failure nothing is written.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from validate_expansion import validate as validate_file  # noqa: E402

EXPANSION_PATH = ROOT / "data" / "expansions" / "expansion.json"
COLLECTORS_DIR = ROOT / "data" / "expansions" / "collectors"
HOLD_LIST_PATH = ROOT / "data" / "expansions" / "hold-list.md"

# Domains that are never an official source for a programme/institution
# fact: aggregators, Wikipedia, ranking providers, forums, lead-gen sites.
BLOCKED_SUBSTRINGS = (
    "wikipedia.org", "collegedunia", "studyu.org", "yocket.com",
    "unifinder", "gradtab.app", "wentchina.com", "laigui.ch",
    "armaneducation.com", "studygateway.io", "topuniversities.com",
    "timeshighereducation.com", "shanghairanking.com", "mastersportal",
    "findamasters", "leverageedu", "collegedekho", "shiksha.com",
    "getmyuni", "thegradcafe", "admitkard", "idp.com", "hotcourses",
    "whatuni", "thecompleteuniversityguide", "edurank", "4icu",
    "unirank", "webometrics", "collegefactual", "niche.com",
    "usnews.com", "qs.com", "quacquarelli", "joinleland.com",
)


def is_blocked(url: str | None) -> bool:
    if not url:
        return False
    dom = urlparse(url).netloc.lower()
    return any(b in dom for b in BLOCKED_SUBSTRINGS)


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _strip_blocked_sources(record: dict, blocked_ids: set[str]) -> list[str]:
    """Remove blocked source ids from a programme's requirement source_ids.
    Drops requirements left with no sources. Returns a list of actions."""
    actions: list[str] = []
    kept_reqs = []
    for req in record.get("requirements", []):
        srcs = [s for s in req.get("source_ids", []) if s not in blocked_ids]
        if not srcs and req.get("source_ids"):
            actions.append(f"dropped requirement {req.get('id')} (blocked-only sources)")
            continue
        if len(srcs) != len(req.get("source_ids", [])):
            actions.append(f"stripped blocked source(s) from requirement {req.get('id')}")
            req = dict(req, source_ids=srcs)
        kept_reqs.append(req)
    record["requirements"] = kept_reqs
    return actions


def merge_band(band: dict, band_name: str, merged: dict) -> dict:
    """Merge one band file into the merged dict. Returns a report dict."""
    report = {"band": band_name, "kept_programs": [], "held_programs": [],
              "kept_institutions": [], "held_institutions": [],
              "stripped": [], "dropped_sources": []}
    srcmap = {s["id"]: s for s in band.get("sources", [])}
    blocked_ids = {sid for sid, s in srcmap.items() if is_blocked(s.get("url"))}
    trace = band.get("traceability", [])

    def trace_sources(scope: str, scope_id: str, field: str) -> list[str]:
        return [t.get("source_url", "") for t in trace
                if t.get("scope") == scope and t.get("scope_id") == scope_id
                and t.get("field") == field]

    # --- institutions: keep, nulling blocked stats -------------------------
    for inst in band.get("institutions", []):
        iid = inst.get("institution_id")
        if iid in {i["institution_id"] for i in merged["institutions"]}:
            continue
        inst = json.loads(json.dumps(inst))  # deep copy
        held = False
        for field in ("total_students", "student_faculty_ratio",
                      "international_pct", "graduate_pct", "male_pct",
                      "female_pct"):
            stat = (inst.get("stats") or {}).get(field)
            if isinstance(stat, dict) and is_blocked(stat.get("source_url")):
                inst["stats"][field] = None
                report["stripped"].append(
                    f"{iid}: stat {field} nulled (blocked source {stat.get('source_url')})")
        fy = inst.get("founded_year")
        if isinstance(fy, dict) and is_blocked(fy.get("source_url")):
            inst["founded_year"] = None
            report["stripped"].append(f"{iid}: founded_year nulled (blocked source)")
        for key in ("intro", "address"):
            val = inst.get(key)
            if isinstance(val, dict) and is_blocked(val.get("source_url")):
                inst[key] = None
                report["stripped"].append(f"{iid}: {key} nulled (blocked source)")
        tags = [t for t in inst.get("membership_tags", [])
                if not is_blocked(t.get("source_url"))]
        if len(tags) != len(inst.get("membership_tags", [])):
            report["stripped"].append(f"{iid}: membership tag(s) dropped (blocked source)")
            inst["membership_tags"] = tags
        photo = inst.get("campus_photo")
        if isinstance(photo, dict) and is_blocked(photo.get("source_url")):
            inst["campus_photo"] = None
            report["stripped"].append(f"{iid}: campus_photo dropped (blocked source)")
        merged["institutions"].append(inst)
        report["kept_institutions"].append(iid)

    # --- programmes: keep only if nothing cited is blocked -----------------
    kept_ids = {p["id"] for p in merged["programs"]}
    for prog in band.get("programs", []):
        pid = prog.get("id")
        if pid in kept_ids:
            continue
        prog = json.loads(json.dumps(prog))  # deep copy
        fee_blocked = any(is_blocked(u) for u in
                          trace_sources("program", pid, "fees"))
        if fee_blocked:
            report["held_programs"].append(
                f"{pid}: fee cites a blocked source")
            continue
        # A deadline citing a blocked source is nulled (unknown), not a
        # reason to hold the whole programme — the fee is the headline
        # fact; a deadline is not. The strip is recorded below.
        dl_blocked = any(is_blocked(u) for u in
                         trace_sources("program", pid, "application_deadline"))
        if dl_blocked and prog.get("application_deadline"):
            prog["application_deadline"] = None
            report["stripped"].append(
                f"{pid}: application_deadline nulled (blocked source)")
        actions = _strip_blocked_sources(prog, blocked_ids)
        # After stripping, any blocked source still referenced anywhere?
        remaining = {s["id"] for s in prog.get("sources", [])
                     if s["id"] in blocked_ids}
        still_ref = set()
        for req in prog.get("requirements", []):
            still_ref |= {s for s in req.get("source_ids", []) if s in blocked_ids}
        if still_ref:
            report["held_programs"].append(
                f"{pid}: still references blocked source(s) {sorted(still_ref)}")
            continue
        # Drop blocked sources that are now unreferenced.
        prog["sources"] = [s for s in prog.get("sources", [])
                           if s["id"] not in blocked_ids]
        if remaining:
            report["dropped_sources"].append(
                f"{pid}: dropped unreferenced blocked source(s) {sorted(remaining)}")
        for a in actions:
            report["stripped"].append(f"{pid}: {a}")
        merged["programs"].append(prog)
        report["kept_programs"].append(pid)

    # --- sources: keep only referenced, deduped across bands ---------------
    used_ids: set[str] = set()
    for prog in merged["programs"]:
        used_ids |= {s["id"] for s in prog.get("sources", [])}
        for req in prog.get("requirements", []):
            used_ids |= set(req.get("source_ids", []))
    existing = {s["id"]: s for s in merged["sources"]}
    for sid in sorted(used_ids):
        if sid in existing:
            continue
        src = srcmap.get(sid)
        if src is None:
            continue  # belongs to an already-merged band
        if is_blocked(src.get("url")):
            continue
        merged["sources"].append(src)
        existing[sid] = src

    # --- traceability: keep rows for kept scopes, re-key fact ids ----------
    kept_prog_ids = {p["id"] for p in merged["programs"]}
    kept_inst_ids = {i["institution_id"] for i in merged["institutions"]}
    existing_fact_ids = {t["fact_id"] for t in merged["traceability"]}
    for t in trace:
        scope, scope_id = t.get("scope"), t.get("scope_id")
        if scope == "program" and scope_id not in kept_prog_ids:
            continue
        if scope == "institution" and scope_id not in kept_inst_ids:
            continue
        if is_blocked(t.get("source_url")):
            continue
        # A nulled stat must not keep its traceability row.
        if scope == "institution" and t.get("field", "").startswith("stats."):
            inst = next((i for i in merged["institutions"]
                         if i["institution_id"] == scope_id), None)
            stat = (inst.get("stats") or {}).get(t["field"][len("stats."):]) \
                if inst else None
            if stat is None:
                continue
        if scope == "institution" and t.get("field") == "founded_year":
            inst = next((i for i in merged["institutions"]
                         if i["institution_id"] == scope_id), None)
            if not inst or not inst.get("founded_year"):
                continue
        fact_id = f"{band_name}-{t.get('fact_id')}"
        if fact_id in existing_fact_ids:
            continue
        merged["traceability"].append(dict(t, fact_id=fact_id))
        existing_fact_ids.add(fact_id)
    return report


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or sorted(COLLECTORS_DIR.glob("rank-*.json"))
    if not paths:
        print("No band files found in data/expansions/collectors/.")
        return 1
    if EXPANSION_PATH.exists():
        merged = _load(EXPANSION_PATH)
    else:
        merged = {"data_version": "v3", "institutions": [], "programs": [],
                  "sources": [], "traceability": []}
    merged_notes = merged.get("notes", "")
    already = set(re.findall(r"rank-\d+-\d+", merged_notes))
    reports = []
    for path in paths:
        band_name = path.stem  # e.g. rank-11-25
        if band_name in already:
            print(f"SKIP {path} (already merged)")
            continue
        band = _load(path)
        report = merge_band(band, band_name, merged)
        reports.append(report)
        merged_notes = (merged_notes + f" Merged band {band_name}."
                        if merged_notes else f"Merged band {band_name}.")
        merged["notes"] = merged_notes
        print(f"--- {band_name}: kept {len(report['kept_programs'])} programs, "
              f"held {len(report['held_programs'])}, "
              f"kept {len(report['kept_institutions'])} institutions")
        for h in report["held_programs"]:
            print(f"    HOLD program: {h}")
        for s in report["stripped"]:
            print(f"    STRIP: {s}")
        for d in report["dropped_sources"]:
            print(f"    DROP source: {d}")
    # Validate before writing anything (validate_expansion.validate takes a
    # path, so check via a temp file).
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tmp:
        json.dump(merged, tmp, ensure_ascii=False, indent=1)
        tmp_path = Path(tmp.name)
    errors = validate_file(tmp_path)
    tmp_path.unlink()
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} errors) — nothing written:")
        for e in errors:
            print(f"  - {e}")
        return 1
    EXPANSION_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    # traceability.csv + source-manifest.json (mirrors of the merged file).
    with open(ROOT / "data" / "expansions" / "traceability.csv", "w",
              newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["fact_id", "scope", "scope_id",
                                          "field", "value", "source_url",
                                          "retrieved_at"])
        w.writeheader()
        for t in merged["traceability"]:
            w.writerow(t)
    (ROOT / "data" / "expansions" / "source-manifest.json").write_text(
        json.dumps({"data_version": "v3", "sources": merged["sources"]},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Hold list (append-only record for the re-verification pass).
    held_lines = ["# Expansion hold list — records held at merge time for "
                  "re-verification against official pages.\n"]
    for r in reports:
        held_lines.append(f"\n## {r['band']}\n")
        for h in r["held_programs"]:
            held_lines.append(f"- program: {h}\n")
        for s in r["stripped"]:
            held_lines.append(f"- stripped: {s}\n")
    if any(r["held_programs"] or r["stripped"] for r in reports):
        with open(HOLD_LIST_PATH, "a", encoding="utf-8") as f:
            f.writelines(held_lines)
    print(f"WROTE {EXPANSION_PATH} "
          f"({len(merged['institutions'])} institutions, "
          f"{len(merged['programs'])} programs, "
          f"{len(merged['sources'])} sources, "
          f"{len(merged['traceability'])} traceability rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
