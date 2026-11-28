"""Round 35 — Arabic hero title weight: font-weight 400 on
.hero-display-ar.

Re-test 30 (2026-11-28 22:27-22:46, cloud browser) PASSED the Arabic
hero title: four lines, joined, no overlap/clipping, stable 2 min
after refresh. But the demo-video recording on the VM's Chromium
(~/workspace/video-record/clips/batch_a_language.mp4, frames at ~9s
and ~11.5s) still shows the title with doubled/thickened strokes —
while the same page's Arabic nav and subtitle, both weight 400,
render clean connected Arabic on the same machine. So this is
environment-dependent, not a re-test 30 miss: the fix must make the
title correct on ANY machine, including font-poor ones.

Root cause: Round 34's .hero-display-ar class (globals.css) set the
family, spacing, line-height, shadow and animation — but its
font-weight was 700, the display-heading weight copied from
.display-hero. An <h1> is bold by default anyway, and the fallback
Arabic face on font-poor systems has no bold variant, so Chromium
synthesises bold by double-striking the glyphs: every stroke is
painted twice, slightly offset — exactly the doubled strokes in the
recording. The weight-400 Arabic text on the same page (nav,
subtitle) has no bold to synthesise, so it renders clean.

Fix (one token, CSS only): font-weight 700 -> 400 on
.hero-display-ar. Nothing else changes — same family, size,
spacing, line-height, no shadow, no animation, no mask. The en/zh
.display-hero keeps 700: Fraunces ships a real bold, and the Latin
display face is meant to be heavy.

Run from the project root:
    .venv/bin/pytest tests/test_r35_arabic_hero_weight.py -q -p no:cacheprovider
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
SRC = FE / "src"

GLOBALS = (SRC / "app" / "globals.css").read_text(encoding="utf-8")
PAGE = (SRC / "app" / "page.tsx").read_text(encoding="utf-8")


def _blocks(css: str, selector: str) -> list[str]:
    blocks = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert blocks, f"no CSS rule for {selector}"
    return blocks


def _rule(css: str, selector: str) -> str:
    return " ".join(_blocks(css, selector))


def _weight(rule: str) -> str:
    m = re.search(r"font-weight:\s*([0-9]+)", rule)
    assert m, "no font-weight in rule"
    return m.group(1)


def test_ar_hero_weight_is_400():
    """The ar hero must not ask for bold: on a font-poor system the
    fallback Arabic face has no bold variant and Chromium synthesises
    it by double-striking the glyphs (the doubled strokes in the
    video recording). 400 renders the face as-is, like the clean
    weight-400 Arabic nav/subtitle on the same page."""
    rule = _rule(GLOBALS, ".hero-display-ar")
    assert _weight(rule) == "400", rule
    assert "font-weight: 700" not in rule


def test_ar_hero_weight_is_declared_exactly_once():
    """Exactly one font-weight declaration on the ar class — a second
    (stale 700) hiding in a later block would win by cascade order
    and re-introduce the synthesis."""
    rule = _rule(GLOBALS, ".hero-display-ar")
    assert len(re.findall(r"font-weight:", rule)) == 1, rule


def test_ltr_display_hero_still_bold_700():
    """en/zh are untouched: .display-hero keeps 700 — Fraunces ships
    a real bold, and the Latin display face is meant to be heavy.
    The 400 applies to the Arabic class only, never to the LTR
    hero."""
    assert _weight(_rule(GLOBALS, ".display-hero")) == "700"
    assert "font-weight: 400" not in _rule(GLOBALS, ".display-hero")


def test_ar_hero_keeps_safe_typography():
    """The weight change is the ONLY change to the ar class: family,
    size, spacing, leading, shadow, animation and mask all stay as
    Round 34 left them."""
    rule = _rule(GLOBALS, ".hero-display-ar")
    assert "font-family: system-ui, sans-serif" in rule
    assert "--font-display" not in rule
    assert "letter-spacing: 0" in rule
    m = re.search(r"line-height:\s*([0-9.]+)", rule)
    assert m and float(m.group(1)) >= 1.3, m
    assert "font-size: clamp(3.2rem, 9.5vw, 6.4rem)" in rule
    assert "text-shadow: none" in rule
    assert "animation: none" in rule
    assert "overflow: visible" in rule
    assert "font-style: normal" in rule


def test_ar_h1_still_uses_hero_display_ar():
    """The ar h1 still renders with ONLY .hero-display-ar (no
    line-mask, no display-hero, no inner span) — the weight fix
    lives in that class, so the branch must still use it."""
    assert '<h1 className="hero-display-ar mt-3">{t(' in PAGE
    assert "hero-display-ar" in PAGE
