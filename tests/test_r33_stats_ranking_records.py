"""Round 33 — homepage stats strip: 4th card is the live ranking-records count.

User choice (2026-11-28): "Languages" did not earn its own stat
card — it is site capability, not content scale. The 4th card now
shows the ranking-records count: QS 2027 + THE 2027 + ARWU 2026
top 100 each = 300 records.

* The number is a LIVE count: ``RANKING_ENTRIES.length`` from
  ``frontend/src/lib/rankings.ts`` (the same data the rankings page
  renders), never hard-coded. The node harness below compiles the
  real module and asserts the length is 300.
* Label is the new ``home.rankingRecords`` key in all 6 locales.
* ``common.languages`` (Round 30 F5) is removed everywhere — it was
  used only by the stats strip — so the key count stays 994.
* Card styling, serif numerals and the count-up animation are
  untouched; only the 4th card's value + label change.

Run from the project root:
    .venv/bin/pytest tests/test_r33_stats_ranking_records.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
PAGE = FE / "src" / "app" / "page.tsx"
RANKINGS = FE / "src" / "lib" / "rankings.ts"

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

EXPECTED_LABELS = {
    "en": "Ranking records",
    "zh-CN": "排名记录",
    "es": "Registros de ranking",
    "fr": "Records de classement",
    "pt-BR": "Registros de ranking",
    "ar": "سجلات التصنيف",
}

_NODE_HARNESS = r"""
const rankings = require(OUT + '/rankings.js');
console.log(JSON.stringify({ entries: rankings.RANKING_ENTRIES.length }));
"""


def _live_ranking_entry_count(tmp_path) -> int:
    """Compile the real rankings.ts and read RANKING_ENTRIES.length."""
    outdir = tmp_path / "r33_rankings"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/rankings.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r33_rankings_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    return json.loads(node.stdout)["entries"]


def test_ranking_entries_live_count_is_300(tmp_path):
    """The live count behind the 4th stat card: 300 ranking entries
    (top 100 x 3 providers), read from the real compiled module."""
    assert _live_ranking_entry_count(tmp_path) == 300


def test_stats_strip_fourth_card_is_ranking_records():
    """page.tsx renders exactly 4 stat cards in order — programmes,
    universities, success cases, ranking records — and the 4th is
    the live RANKING_ENTRIES.length, not a literal."""
    page = PAGE.read_text(encoding="utf-8")
    assert "RANKING_ENTRIES" in page
    assert "import { displayProgramInstitutionName, RANKING_ENTRIES, RANKING_INSTITUTIONS }" in page
    stats = re.search(
        r"\(\[([\s\S]*?)\] as const\)\.map\(\(\[value, label\]\)",
        page,
    )
    assert stats, "stats array literal not found in page.tsx"
    entries = [ln.strip() for ln in stats.group(1).strip().splitlines() if ln.strip()]
    assert len(entries) == 4, entries
    assert entries[0].startswith("[allPrograms().length, t('home.programsTitle')]"), entries
    assert entries[1].startswith("[RANKING_INSTITUTIONS.length, t('institutions.title')]"), entries
    assert entries[2].startswith("[SUCCESS_CASES.length, t('cases.title')]"), entries
    assert entries[3].startswith("[RANKING_ENTRIES.length, t('home.rankingRecords')]"), entries
    assert "300" not in stats.group(1), "ranking count must not be hard-coded"


def test_stats_strip_no_languages_card_left():
    """No trace of the old 4th card: neither the key nor the
    LOCALES-based value survives in the homepage."""
    page = PAGE.read_text(encoding="utf-8")
    assert "common.languages" not in page
    assert "LOCALES.length" not in page
    assert "LOCALES" not in page, "LOCALES import is now unused in page.tsx"


def test_ranking_records_label_in_all_locales():
    """home.rankingRecords exists in all 6 locales with the exact
    agreed wording, and common.languages is gone everywhere. The
    key count stays 994 (one removed, one added)."""
    for loc in LOCALES:
        msgs = json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        assert len(msgs) == 994, (loc, len(msgs))
        assert msgs.get("home.rankingRecords") == EXPECTED_LABELS[loc], loc
        assert "common.languages" not in msgs, loc


def test_stats_card_styling_unchanged():
    """The 4th card keeps the same markup as the other three —
    serif numeral + label — so only its value and label changed."""
    page = PAGE.read_text(encoding="utf-8")
    assert 'className="stat-num text-5xl font-bold text-navy"' in page
    assert 'className="card-hard card-lift rounded-2xl p-5"' in page
