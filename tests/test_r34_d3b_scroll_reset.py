"""Round 34 D3b — guarded clipped-arrival scroll reset in RouteTransition.

Defect (re-test 29, 2026-11-28 20:48-21:19): the /results and /cases
H1 headings ("Your results", "Success cases") are clipped by the
sticky nav after in-site navigation. Mechanism (D3 analysis,
DECISIONS #327 — preserved, not re-derived here): Next 14.2.35's
``InnerScrollAndFocusHandler.handlePotentialScroll`` early-exits
without resetting scroll when the new page segment's top is already
in the viewport; ``pushState`` does not reset scroll, and nothing
else in the app scrolls (no ``window.scrollTo`` anywhere in
``frontend/src`` before this fix; only ``main.focus({preventScroll:
true})``). The H1 sits ``py-8`` (32px) below the page top, so a
carried-over ``scrollY`` in (32px, headerHeight] puts the H1's top
under the sticky header (z-50) — desktop band ≈ (32, 53]px, wider
on mobile where the header wraps taller. The offset is
self-perpetuating: once in the band, every further in-site
navigation early-exits again. NOT the line-mask (the reveal settles
at translateY(0) and never moves the H1 box; the clip persists past
the animation) and NOT missing scroll-margin (the H1 has no id,
nothing links to it, no scrolling happens at all in the failing
path — ``scroll-mt-*`` would be a placebo).

Fix (layout level, one place, all pages): a guarded arrival check
in ``frontend/src/components/RouteTransition.tsx`` — on every
pathname change, in ``requestAnimationFrame`` (after paint, after
Next's scroll handler has settled), measure the REAL sticky header
bottom and the REAL first heading top
(``header.getBoundingClientRect().bottom``,
``main h1.getBoundingClientRect().top``) and call
``window.scrollTo(0, 0)`` ONLY when ``isClippedArrival`` is true:
``0 <= h1Top < headerBottom``. That guard cannot disturb a
back/forward restored deep scroll (H1 above the viewport,
``h1Top < 0``) or a scrollY = 0 arrival (H1 a full py-8 below the
header bottom). No hard-coded pixel heights; no change to the
sticky header, the pages' padding, or the line-mask animation.
This is the ONLY ``window.scrollTo`` in the app.

Tests in this file are source/behaviour pins over the real
component code: the guard function is EXTRACTED VERBATIM from
RouteTransition.tsx and executed in node over the full boundary
vector (no copy of the logic lives in this file), and the effect
structure is pinned by source assertions. Browser scroll behaviour
itself cannot be observed from here.

LIVE-DOM EVIDENCE STILL OWED (parent / browser re-test after push):
1. On desktop, scroll the previous page ~33-53px, then click a nav
   link to /results or /cases: the H1 must be fully visible (no
   clip), and the page must be at scrollY = 0.
2. Same on a narrow/mobile viewport with the header wrapped taller
   (scroll ~40-90px first): H1 fully visible.
3. Back/forward: from /results scrolled deep, go to /cases, then
   press Back — the restored deep scroll position on /results must
   be intact (NOT reset to top).
4. Normal arrival at scrollY = 0: no visible jump, no reset.
5. Confirm no other page regressed (rankings / programs / report /
   wizard / institutions share the same geometry and the same fix).

Run from the project root:
    .venv/bin/pytest tests/test_r34_d3b_scroll_reset.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
SRC = FE / "src"
RT = SRC / "components" / "RouteTransition.tsx"
LAYOUT = SRC / "app" / "layout.tsx"
HEADER = SRC / "components" / "Header.tsx"
RESULTS = SRC / "app" / "results" / "page.tsx"
CASES = SRC / "app" / "cases" / "page.tsx"
GLOBALS = (SRC / "app" / "globals.css").read_text(encoding="utf-8")

# (h1Top, headerBottom) -> expected isClippedArrival result.
# Desktop header ~53px: clipped band is h1Top in [0, 53).
# scrollY = 0 puts the H1 at 53 + 32 (py-8) = 85.
VECTORS = [
    ((52, 53), True),    # desktop clipped band, scrollY ~33
    ((33, 53), True),    # desktop clipped band, scrollY ~52
    ((0, 53), True),     # H1 top exactly at viewport top: under header
    ((53, 53), False),   # exactly at header bottom: fully visible
    ((85, 53), False),   # scrollY = 0 arrival: never reset
    ((-1, 53), False),   # one px above viewport: restored deep scroll
    ((-400, 53), False),  # deep back/forward restore: never reset
    ((90, 100), True),   # mobile wrapped header (~100px): clipped
    ((110, 100), False),  # mobile, H1 below the taller header
    ((0, 100), True),    # mobile, H1 at viewport top
]


def _guard_source() -> str:
    """The exported guard, extracted VERBATIM from the component —
    no copy of its logic lives in this test file."""
    m = re.search(
        r"export function isClippedArrival\(h1Top: number, headerBottom: number\): boolean \{(.*?)\n\}",
        RT.read_text(encoding="utf-8"),
        re.S,
    )
    assert m, "isClippedArrival not found in RouteTransition.tsx"
    return m.group(0)


def _guard_js() -> str:
    """The verbatim guard with its TypeScript type annotations
    stripped, so plain node can execute it — the logic (one return
    expression) is byte-identical to the component source."""
    src = _guard_source()
    src = re.sub(
        r"export function isClippedArrival\(h1Top: number, headerBottom: number\): boolean",
        "function isClippedArrival(h1Top, headerBottom)",
        src,
    )
    assert ": number" not in src and ": boolean" not in src
    return src


def _run_guard_in_node(tmp_path) -> dict[str, bool]:
    """Execute the real extracted guard in node over VECTORS."""
    harness = tmp_path / "r34_d3b_guard_harness.js"
    cases = json.dumps([[list(v), exp] for v, exp in VECTORS])
    harness.write_text(
        _guard_js()
        + "\nconst cases = "
        + cases
        + ";\nconsole.log(JSON.stringify(cases.map(([v, e]) => "
          "isClippedArrival(v[0], v[1]) === e)));\n",
        encoding="utf-8",
    )
    env = {"PATH": os.environ["PATH"]}
    node = subprocess.run(
        ["node", str(harness)], capture_output=True, text=True,
        timeout=60, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    return json.loads(node.stdout)


def test_guard_behaviour_over_boundary_vectors(tmp_path):
    """The REAL guard from RouteTransition.tsx returns the expected
    value for every boundary vector: true exactly inside the clipped
    band (desktop and wrapped-mobile header heights), false for a
    scrollY = 0 arrival, false for any restored deep scroll, false
    at the exact header-bottom boundary."""
    results = _run_guard_in_node(tmp_path)
    assert len(results) == len(VECTORS), results
    assert all(results), [
        (v, exp) for (v, exp), ok in zip(VECTORS, results) if not ok
    ]


def test_guard_is_a_single_half_open_interval():
    """The guard is exactly ``0 <= h1Top < headerBottom`` — a
    half-open interval. No extra clause (no scrollY read, no
    pathname check, no timer) may widen or narrow it."""
    src = _guard_source()
    assert "h1Top >= 0 && h1Top < headerBottom" in src
    assert "scrollY" not in src
    assert "pathname" not in src


# ---------------------------------------------------------------------------
# The effect: guarded, live-measured, pathname-keyed, sole scrollTo
# ---------------------------------------------------------------------------

def test_scroll_reset_is_guarded_not_unconditional():
    """The ONLY window.scrollTo in the component sits inside the
    ``if (isClippedArrival(...))`` — there is no unconditional
    scroll-to-top on navigation anywhere in the effect."""
    text = RT.read_text(encoding="utf-8")
    assert text.count("window.scrollTo") == 1, text.count("window.scrollTo")
    assert "window.scrollTo(0, 0);" in text
    m = re.search(
        r"if \(isClippedArrival\(h1\.getBoundingClientRect\(\)\.top, "
        r"header\.getBoundingClientRect\(\)\.bottom\)\) \{\s*\n\s*window\.scrollTo\(0, 0\);",
        text,
    )
    assert m, "scrollTo is not inside the isClippedArrival guard"


def test_effect_measures_real_header_and_real_h1():
    """Both edges are measured live at runtime — the sticky
    header's bottom (covers the wrapped mobile header) and the
    first h1 inside <main> — never a hard-coded pixel height."""
    text = RT.read_text(encoding="utf-8")
    assert "document.querySelector('header')" in text
    assert "document.querySelector('main h1')" in text
    assert "header.getBoundingClientRect().bottom" in text
    assert "h1.getBoundingClientRect().top" in text


def test_effect_runs_after_paint_on_pathname_change():
    """The check runs in requestAnimationFrame on every pathname
    change — i.e. after paint and after Next's scroll handler has
    settled — and its frame is cancelled on cleanup."""
    text = RT.read_text(encoding="utf-8")
    assert "window.requestAnimationFrame" in text
    assert "window.cancelAnimationFrame(raf)" in text
    m = re.search(
        r"return \(\) => window\.cancelAnimationFrame\(raf\);\s*\n\s*\}, \[pathname\]\);",
        text,
    )
    assert m, "guarded effect is not keyed on [pathname] with rAF cleanup"


def test_effect_is_noop_without_header_or_h1():
    """Pages without a header or without an h1 are left alone —
    the effect returns early instead of scrolling."""
    text = RT.read_text(encoding="utf-8")
    assert "if (!header || !h1) return;" in text


def test_no_other_scrollto_in_frontend_src():
    """This is the ONLY window.scrollTo in the whole frontend —
    no other component, page or helper scrolls the window, so no
    second reset can fight this one or break scroll restoration."""
    hits = []
    for path in SRC.rglob("*.tsx"):
        if "window.scrollTo" in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(SRC)))
    assert hits == ["components/RouteTransition.tsx"], hits


def test_no_hard_coded_pixel_heights_in_fix():
    """No hard-coded 53px header height or 32px py-8 offset in the
    fix CODE (guard function + guarded effect): the geometry comes
    from live getBoundingClientRect calls. The prose comments may
    describe the band in numbers; the code must not contain them."""
    text = RT.read_text(encoding="utf-8")
    effect = re.search(
        r"(/\*\*\n   \* Round 34 D3 — guarded clipped-arrival scroll reset\..*?\n  \}, \[pathname\]\);)",
        text,
        re.S,
    )
    assert effect, "guarded effect block not found"
    code = _guard_source() + "\n" + effect.group(1)
    code_lines = [ln for ln in code.splitlines() if not ln.strip().startswith("*")]
    code_only = "\n".join(code_lines)
    assert "53" not in code_only
    assert "32" not in code_only


def test_focus_effect_still_prevent_scroll():
    """The pre-existing focus-to-<main> effect is untouched and
    still uses preventScroll — the fix does not smuggle in a
    focus-driven scroll."""
    text = RT.read_text(encoding="utf-8")
    assert "(main as HTMLElement).focus({ preventScroll: true });" in text


# ---------------------------------------------------------------------------
# Nothing else changed: header, pages, animation, transition untouched
# ---------------------------------------------------------------------------

def test_sticky_header_unchanged():
    """The header stays sticky top-0 z-50 — the fix measures it,
    it does not restyle it."""
    assert 'className="sticky top-0 z-50 border-b border-white/10 bg-navy text-white shadow-md"' in HEADER.read_text(
        encoding="utf-8"
    )


def test_h1s_unchanged_no_scroll_margin_placebo():
    """The /results and /cases H1s keep their exact pre-existing
    markup (py-8 container, line-mask h1, no id, no scroll-mt):
    the D3 analysis proved scroll-margin would be a placebo here
    and no in-page workaround was applied."""
    for page in (RESULTS, CASES):
        text = page.read_text(encoding="utf-8")
        assert 'className="mx-auto max-w-6xl px-4 py-8"' in text
    assert '<h1 className="line-mask text-2xl font-bold">' in RESULTS.read_text(encoding="utf-8")
    assert '<h1 className="line-mask text-2xl font-bold">' in CASES.read_text(encoding="utf-8")
    assert "scroll-mt" not in RESULTS.read_text(encoding="utf-8").split("<h1")[1].split("</h1>")[0]
    assert "scroll-mt" not in CASES.read_text(encoding="utf-8").split("<h1")[1].split("</h1>")[0]


def test_line_mask_animation_untouched():
    """The line-mask reveal is not edited for this defect — it was
    ruled out as the mechanism and settles at translateY(0)."""
    assert "animation: line-reveal .7s var(--ease-reveal) both" in GLOBALS


def test_quiet_prefixes_and_wrapper_unchanged():
    """RouteTransition's quiet-page list and wrapper classes are
    untouched — /results and /cases still render the quiet fade
    wrapper, which is the segment Next's scroll handler measures."""
    text = RT.read_text(encoding="utf-8")
    assert "const QUIET_PREFIXES = ['/rankings', '/institutions', '/programs', '/report', '/results', '/cases'];" in text
    assert "className={plain ? undefined : quiet ? 'route-enter-quiet' : 'route-enter'}" in text


def test_layout_scroll_restoration_comment_still_true():
    """layout.tsx still documents scroll restoration intact — the
    guard is what keeps that true for back/forward arrivals."""
    assert "scroll restoration intact" in LAYOUT.read_text(encoding="utf-8")
