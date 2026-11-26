"""Round 13 W2 (frontend fail-fast + panel fixes): source-level pins.

There is no frontend JS test runner in this repo (no jest/vitest in
package.json), so these tests assert on the frontend source itself —
the same approach as test_frontend_mirrors.py. They pin:

* the SimulatePanel default never checks both budget options, and the
  toggle enforces mutual exclusion (both patches raise the same budget
  field, so both checked is a contradiction);
* simulateMulti / createPlan / reassessPlan use a 40s per-attempt
  timeout with the 90s overall budget (not the 25s fetchJsonPatient
  default);
* a failed explain:true simulate retries once with explain:false so
  the deterministic engine numbers still render, and a 429 shows the
  distinct rate-limit message (sim.rateLimited / plan.rateLimited)
  in all 6 locales instead of the generic error.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIMULATE_TS = ROOT / "frontend" / "src" / "lib" / "simulate.ts"
PLANS_TS = ROOT / "frontend" / "src" / "lib" / "plans.ts"
SIM_PANEL = ROOT / "frontend" / "src" / "components" / "SimulatePanel.tsx"
PLAN_PANEL = ROOT / "frontend" / "src" / "components" / "PlanPanel.tsx"
MESSAGES = ROOT / "frontend" / "messages"
LOCALES = ["en", "zh-CN", "ar", "es", "fr", "pt-BR"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_default_selection_drops_budget_plus_5000():
    src = _read(SIMULATE_TS)
    assert "export function defaultSimulateSelection" in src
    body = src.split("export function defaultSimulateSelection")[1].split("\n}\n")[0]
    assert "budget-plus-10000" in body and "budget-plus-5000" in body
    # The default keeps the +10000 step and filters out +5000.
    assert "id !== 'budget-plus-5000'" in body
    panel = _read(SIM_PANEL)
    assert "defaultSimulateSelection(candidates)" in panel
    # No select-all default remains anywhere in the panel.
    assert "candidates.map((c) => c.id)" not in panel


def test_toggle_enforces_budget_mutual_exclusion():
    src = _read(SIMULATE_TS)
    assert "export function toggleSimulateSelection" in src
    body = src.split("export function toggleSimulateSelection")[1].split("\n}\n")[0]
    # Checking +10000 drops +5000 and vice versa.
    assert "budget-plus-10000' ? 'budget-plus-5000' : 'budget-plus-10000'" in body
    panel = _read(SIM_PANEL)
    assert "toggleSimulateSelection(prev, id)" in panel
    # The reset button restores the same non-contradictory default.
    assert "setSelected(defaultSimulateSelection(candidates))" in panel


def test_simulate_and_plan_use_40s_attempt_timeout():
    sim = _read(SIMULATE_TS)
    assert re.search(r"attemptTimeoutMs:\s*40_000", sim), "simulateMulti must pass 40s attempts"
    assert re.search(r"budgetMs:\s*90_000", sim), "simulateMulti keeps the 90s overall budget"
    plans = _read(PLANS_TS)
    # createPlan and reassessPlan both set the same budgets.
    assert len(re.findall(r"attemptTimeoutMs:\s*40_000", plans)) >= 2
    assert len(re.findall(r"budgetMs:\s*90_000", plans)) >= 2
    panel = _read(PLAN_PANEL)
    assert "attemptTimeoutMs: 40_000" in panel
    assert "budgetMs: 90_000" in panel
    # api.ts itself is untouched by this worker (another worker owns it).
    assert "attemptTimeoutMs ?? 25_000" in _read(ROOT / "frontend" / "src" / "lib" / "api.ts")


def test_simulate_falls_back_to_explain_false_on_failure():
    panel = _read(SIM_PANEL)
    # First attempt asks the model; the fallback does not.
    assert "explain: true" in panel
    assert "explain: false" in panel
    # The fallback is short-budgeted so a dead backend does not stack
    # another full 90s wait onto the first one.
    assert "budgetMs: 30_000" in panel
    # Numbers render from the response even when the explanation is
    # missing — the explanation block must not gate the result.
    assert "result.explanation?.source" in panel
    assert "result.explanation?.text" in panel


def test_rate_limited_errors_show_distinct_message():
    plans = _read(PLANS_TS)
    assert "export function isRateLimitedError" in plans
    body = plans.split("export function isRateLimitedError")[1].split("\n}\n")[0]
    assert "429" in body and "RATE_LIMITED" in body
    for panel_path, key in ((SIM_PANEL, "sim.rateLimited"), (PLAN_PANEL, "plan.rateLimited")):
        panel = _read(panel_path)
        assert "isRateLimitedError" in panel
        assert f"t('{key}')" in panel
    # The distinct message exists, non-empty, in every locale; the
    # Chinese wording is the exact string from the task.
    for loc in LOCALES:
        msgs = json.loads((MESSAGES / f"{loc}.json").read_text(encoding="utf-8"))
        assert msgs["sim.rateLimited"].strip(), loc
        assert msgs["plan.rateLimited"].strip(), loc
    zh = json.loads((MESSAGES / "zh-CN.json").read_text(encoding="utf-8"))
    assert zh["sim.rateLimited"] == "AI 请求太频繁，请稍等一分钟再试"
    assert zh["plan.rateLimited"] == "AI 请求太频繁，请稍等一分钟再试"


def test_plan_renders_template_tasks_when_response_arrives():
    # The ready branch is keyed on the plan arriving, not on ai_status:
    # ai_status 'unavailable' renders the template label, never an error.
    panel = _read(PLAN_PANEL)
    assert "plan && phase === 'ready'" in panel
    assert "plan.ai_status === 'available' ? t('plan.aiSuggestionLabel') : t('plan.templateLabel')" in panel
    # Boundary wording untouched.
    en = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))
    assert en["sim.boundary"].startswith("AI-generated reading")
    zh = json.loads((MESSAGES / "zh-CN.json").read_text(encoding="utf-8"))
    assert zh["sim.boundary"] == "AI 生成的解读，仅供参考，请以大学官网为准。引擎数字是已核实的事实；建议只是建议，不是事实。"
