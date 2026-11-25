"""Generate data/versions/v2/traceability.csv (spec Ch16).

Derives the CSV from the v1 source manifest (evidence fact ids are checked
against it — a missing fact id fails the run, except the documented
forward-reference f-ucl-gcse, which the v2 manifest must add) and TASKS.md
(D2-04 / D2-06 rows are read and recorded as evidence). The
requirement -> implementation -> test mapping itself is the traceability
content maintained here; release_sha comes from git HEAD when available,
else "unknown" (this workspace has no local git repo, so it is "unknown"
until the coordinator runs this under git).

Columns: requirement_id, implementation, test_id, evidence, release_sha.

Run from the project root:
    .venv/bin/python tools/generate_traceability.py
The coordinator re-runs this once the v2 manifest lands.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "data" / "versions" / "v1"
OUT = ROOT / "data" / "versions" / "v2" / "traceability.csv"

# requirement_id -> (implementation, test_id, evidence fact ids / files)
# Evidence fact ids must exist in the v1 manifest unless marked fwd-ref.
ROWS: list[tuple[str, str, str, list[str]]] = [
    ("FR01", "backend/app/schemas.py;backend/app/main.py:POST /profile/validate",
     "tests/test_day2.py::test_validate_full_shape_valid;tests/test_day2.py::test_validate_field_errors",
     ["data/schemas/student-profile.json"]),
    ("FR02", "backend/app/main.py:GET /programs",
     "tests/test_day2.py::test_programs_filter_country;tests/test_day2.py::test_programs_pagination_cursor",
     ["data/versions/v1/programs.json"]),
    ("FR05", "backend/domain/eligibility.py",
     "tests/test_day2.py::test_t01_ordinary_cases;tests/test_day2.py::test_t02_non_alevel_ib_background_unknown",
     ["f-ucl-ielts", "f-ucl-alevel", "f-ucl-ib", "f-nus-ielts", "f-nus-academic"]),
    ("FR06", "backend/ai/explain.py;backend/ai/provider.py;backend/app/main.py:POST /explain",
     "tests/test_day2.py::test_explain_recomputes_from_profile;tests/test_day2.py::test_t08_provider_timeout_keeps_rules",
     ["f-ucl-ielts", "f-nus-ielts"]),
    ("FR07", "backend/app/main.py:POST /simulate",
     "tests/test_eligibility.py::test_simulation_matches_direct_reevaluation",
     ["f-ucl-ielts"]),
    ("BR01", "backend/domain/eligibility.py:evaluate_ucl:academic;backend/app/adapter.py:flat_to_student",
     "tests/test_day2.py::test_t02_non_alevel_ib_background_unknown;tests/test_day2.py::test_ib_hl_total_boundaries",
     ["f-ucl-alevel", "f-ucl-ib"]),
    ("BR02", "backend/domain/eligibility.py:_ucl_toefl_rule;backend/domain/eligibility.py:evaluate_ucl:language",
     "tests/test_day2.py::test_t05_toefl_date_boundary;tests/test_day2.py::test_t05_ielts_threshold_boundaries",
     ["f-ucl-ielts", "f-nus-toefl"]),
    ("BR03", "backend/domain/eligibility.py:UNKNOWN branches;backend/app/main.py:_profile_warnings",
     "tests/test_day2.py::test_t04_complex_or_cross_currency_unknown_date;tests/test_day2.py::test_validate_warnings_for_missing_fields",
     ["f-ucl-tara", "f-nus-gre"]),
    ("BR04", "backend/domain/eligibility.py (rule order is fixed; no override logic in Day 2 scope)",
     "",
     ["data/versions/v1/source-manifest.json"]),
    ("BR05", "backend/domain/eligibility.py:_fee_ucl;backend/domain/eligibility.py:evaluate_nus:fee (Decimal)",
     "tests/test_day2.py::test_decimal_budget_comparison;tests/test_day2.py::test_t04_complex_or_cross_currency_unknown_date",
     ["f-ucl-fee-overseas", "f-ucl-fee-uk", "f-nus-fee"]),
    ("BR06", "backend/domain/eligibility.py:overall_status",
     "tests/test_day2.py::test_t01_ordinary_cases",
     ["f-ucl-ielts", "f-nus-ielts"]),
    ("BR07", "data/versions/v1/programs.json (NUS deadline recorded as null/UNKNOWN; no date invented)",
     "",
     ["data/versions/v1/programs.json"]),
    ("BR08", "backend/app/main.py:GET /programs (stable file order; filters before paging)",
     "tests/test_day2.py::test_programs_pagination_cursor",
     ["data/versions/v1/programs.json"]),
    ("BR09", "not implemented in Day 2 scope (no improvement-plan/action endpoint)",
     "",
     ["TASKS.md D2-07/Day 3"]),
    ("T01", "backend/domain/eligibility.py;backend/app/main.py:POST /match",
     "tests/test_day2.py::test_t01_ordinary_cases",
     ["f-ucl-ielts", "f-nus-ielts"]),
    ("T02", "backend/domain/eligibility.py:evaluate_ucl:academic (other);evaluate_nus:academic (other)",
     "tests/test_day2.py::test_t02_non_alevel_ib_background_unknown",
     ["f-ucl-alevel", "f-ucl-ib", "f-nus-academic"]),
    ("T03", "backend/domain/eligibility.py (pure function, no I/O)",
     "tests/test_day2.py::test_t03_repeat_determinism_10x",
     ["data/versions/v1/programs.json"]),
    ("T04", "backend/domain/eligibility.py:evaluate_nus:academic (OR routes);_fee_ucl (cross-currency UNKNOWN);_ucl_toefl_rule (no date UNKNOWN)",
     "tests/test_day2.py::test_t04_complex_or_cross_currency_unknown_date",
     ["f-nus-academic", "f-ucl-fee-overseas", "f-ucl-ielts"]),
    ("T05", "backend/domain/eligibility.py (threshold comparisons)",
     "tests/test_day2.py::test_t05_ielts_threshold_boundaries;tests/test_day2.py::test_t05_toefl_date_boundary;tests/test_day2.py::test_t05_ib_hl_total_boundaries;tests/test_day2.py::test_t05_gcse_boundaries;tests/test_day2.py::test_t05_fee_boundaries",
     ["f-ucl-ielts", "f-nus-toefl", "f-ucl-ib", "f-ucl-fee-overseas", "f-ucl-fee-uk"]),
    ("T08", "backend/ai/explain.py:explain_with_status (template fallback, ai_status=unavailable)",
     "tests/test_day2.py::test_t08_provider_timeout_keeps_rules",
     ["f-ucl-ielts"]),
    ("T09", "backend/app/data.py:load_programs (raises on corrupt/missing/fixture data; never serves a half dataset)",
     "tests/test_day2.py::test_t09_corrupt_manifest_refuses_load;tests/test_day2.py::test_t09_missing_manifest_refuses_load;tests/test_day2.py::test_t09_fixture_in_real_data_refused",
     ["data/versions/v1/source-manifest.json"]),
    ("NFR02", "backend/ai/explain.py:explain_with_status;backend/app/data.py:load_programs",
     "tests/test_day2.py::test_t08_provider_timeout_keeps_rules;tests/test_day2.py::test_t09_corrupt_manifest_refuses_load",
     ["data/versions/v1/source-manifest.json"]),
    ("NFR03", "backend/domain/eligibility.py (pure function)",
     "tests/test_day2.py::test_t03_repeat_determinism_10x",
     ["data/versions/v1/programs.json"]),
    ("NFR04", "backend/app/main.py:rate limiting + security headers middleware;tools/generate_openapi.py",
     "tests/test_day2.py::test_rate_limit_explain_429;tests/test_day2.py::test_security_headers_present;tests/test_day2.py::test_openapi_matches_generated_copy",
     ["docs/openapi.json"]),
    # Fix 2026-11-25 (language / status chips / curriculum branching).
    # Evidence is file paths, not v1 fact ids: the new equivalence facts
    # (f-ucl-china-gaokao, f-imperial-usa-ap, f-imperial-china-none) live
    # in the v2 manifest, which this tool does not validate fact ids
    # against — the manifest file itself is the evidence.
    ("FIX-01", "backend/domain/eligibility.py:effective_curriculum;backend/app/adapter.py:flat_to_student (curriculum branches cn_gaokao/uk_alevel/ib/usa/sg_alevel/other; Gaokao/USA UNKNOWN where no official equivalence exists)",
     "tests/test_curriculum.py (13 tests: Gaokao UNKNOWN for UCL/Imperial, USA AP below-standard NOT_MET / standard-met UNKNOWN, SG A-level MET, adapter flat mapping, /profile/validate field errors)",
     ["data/versions/v2/source-manifest.json"]),
    ("FIX-02", "frontend/src/lib/ruleText.ts;frontend/src/lib/format.ts (localized rule rendering from observedRaw/thresholdRaw/reasonKey; fee sentence; programme duration/intake/fee period)",
     "/tmp/pp-test-src/render-test.ts (standalone tsc + node, fake t() backed by the real locale files; zh-CN + en, all checks passed)",
     ["frontend/messages/en.json", "frontend/messages/zh-CN.json"]),
    ("FIX-03", "frontend/src/app/results/page.tsx (labelled chips, legend, next-steps panel);frontend/src/app/programs/[id]/page.tsx (minimums list + check button, back to home);frontend/src/components/WelcomeModal.tsx (first-visit modal)",
     "npm run build (locale check 6 x 306 keys + all routes); live :3000 production build, all pages 200",
     ["frontend/messages/en.json"]),
    ("FIX-04", "frontend/src/lib/api.ts:evaluateLocal (curriculum branches; supplementary nus-toefl + ntu-msai-toefl rules)",
     "tests/test_curriculum.py;/tmp/pp-test-src/render-test.ts",
     ["data/versions/v2/source-manifest.json"]),
]

# Forward-reference fact ids: used by the Day 2 engine, to be added by the
# v2 manifest (documented in DECISIONS.md #45). Not an error here.
FORWARD_REFS = {"f-ucl-gcse"}


def _release_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _tasks_evidence() -> dict[str, str]:
    """Read the D2-04 / D2-06 rows out of TASKS.md."""
    text = (ROOT / "TASKS.md").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| D2-04") or line.startswith("| D2-06"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4:
                found[parts[0]] = f"TASKS.md {parts[0]}: {parts[-1]}"
    return found


def main() -> Path:
    manifest = json.loads((V1 / "source-manifest.json").read_text(encoding="utf-8"))
    known_facts = {f["id"] for f in manifest.get("facts", [])}
    tasks = _tasks_evidence()
    if "D2-04" not in tasks or "D2-06" not in tasks:
        raise SystemExit("TASKS.md must contain D2-04 and D2-06 rows.")
    sha = _release_sha()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["requirement_id", "implementation", "test_id", "evidence", "release_sha"])
        for req, impl, test_id, evidence in ROWS:
            ev = list(evidence)
            for item in evidence:
                if item.startswith("f-") and item not in known_facts and item not in FORWARD_REFS:
                    raise SystemExit(f"Traceability evidence fact {item} not in v1 manifest ({req}).")
            if req in ("FR06",):
                ev.append(tasks["D2-04"])
            if req in ("FR02", "NFR04"):
                ev.append(tasks["D2-06"])
            w.writerow([req, impl, test_id, ";".join(ev), sha])
    print(f"Wrote {OUT} ({len(ROWS)} rows, release_sha={sha})")
    return OUT


if __name__ == "__main__":
    main()
