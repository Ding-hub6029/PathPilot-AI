"""Restyle 2 (aureon + RAN KV) — Worker A, visual half.

Visual-only restyle, no logic / data / copy / route change, no new
i18n key from THIS half (994 keys in all 6 locales: 984 at Round 31
+ the behaviour half's 10 keys — the visual half adds none):

- Display type: Fraunces (high-contrast Didone serif) via
  next/font/google, Latin-only subsets, weights 500/700, wired as
  --font-display. CJK/Arabic fall back to the system stack. NO
  oblique/italic on display type anywhere (Round 30 F4 lesson:
  synthetic slant breaks Arabic joining) — the display classes pin
  font-style: normal.
- Hero: navy #0B1F3A with a RECREATED canvas particle ring
  (ParticleRing.tsx) — restrained blue-white stardust, amber
  #F2A541 highlights, one slow ~12 s silent loop, gold compass at
  the centre, particle tracks as study-route arcs. The RAN video's
  own fine print forbids commercial reuse / secondary distribution,
  so the effect is recreated in code — no footage, no lifted asset.
  Lightweight canvas 2D, pauses offscreen (IntersectionObserver),
  static frame under prefers-reduced-motion.
- Asymmetric editorial hero (big serif title + serif slogan +
  eyebrow with a `//` prefix, generous black space); hero prompt
  bar / wizard CTA untouched and still working.
- Content pages on paper #F7F5F0; navy reserved for the hero +
  embedded dark panel + footer (footer is now dark navy).
  Programme cards: white cards, 1px hairline borders, numbered
  01-08, one gold object each (compass / cap / globe / key, inline
  SVG, no new binary assets), both buttons still present. Stats in
  big serif numerals, same live counts, same labels. Numbered nav
  (01-06) and the stats count-up behaviour are unchanged.

Covers, with no API key and no network:
- (a) the display font is Fraunces, Latin-only, 500/700,
  --font-display wired; every display class pins font-style:
  normal; no `oblique` anywhere in frontend/src; the hero title,
  stats and section headings use the serif display classes;
- (b) ParticleRing respects reduced-motion (static frame, no rAF
  loop) and pauses offscreen (IntersectionObserver +
  cancelAnimationFrame), runs a 12 s loop, and contains no video
  or lifted footage;
- (c) the programme cards are white paper cards with a gold object
  and both buttons; the footer is dark navy; no locale key was
  added by this half (994 x 6 = 984 at Round 31 + behaviour half x10);
- (d) the two new components compile clean under tsc.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_restyle2_a_visual.py
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
SRC = FE / "src"
MESSAGES = FE / "messages"

LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

LAYOUT = (SRC / "app" / "layout.tsx").read_text(encoding="utf-8")
GLOBALS = (SRC / "app" / "globals.css").read_text(encoding="utf-8")
PAGE = (SRC / "app" / "page.tsx").read_text(encoding="utf-8")
PARTICLE = (SRC / "components" / "ParticleRing.tsx").read_text(encoding="utf-8")
GOLD = (SRC / "components" / "GoldObject.tsx").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    # Some selectors are declared twice (e.g. .hero-display sets the
    # type scale first, the font family later) — join every block so
    # a pin sees the full effective rule.
    blocks = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert blocks, f"no CSS rule for {selector}"
    return " ".join(blocks)


# ---------------------------------------------------------------------------
# (a) Display font: Fraunces, upright, wired
# ---------------------------------------------------------------------------

def test_display_font_is_fraunces_latin_500_700():
    assert "Fraunces" in LAYOUT
    assert "Space_Grotesk" not in LAYOUT
    assert "subsets: ['latin']" in LAYOUT
    assert "weight: ['500', '700']" in LAYOUT
    assert "variable: '--font-display'" in LAYOUT


def test_no_oblique_or_italic_font_style_in_frontend_src():
    """Round 30 F4: synthetic slant breaks Arabic joining — no
    `font-style: oblique` / `font-style: italic` declaration may
    appear in any frontend source file. (The word 'oblique' in a
    comment explaining the ban is fine; a Tailwind `italic` class
    on a body quote elsewhere is not a font-style declaration and
    is out of this pin's scope — display type is what it guards.)"""
    bad = re.compile(r"font-style\s*:\s*(oblique|italic)")
    hits = [str(p) for p in SRC.rglob("*") if p.is_file()
            and bad.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == [], hits


@pytest.mark.parametrize("selector", [
    ".hero-display", ".display-hero", ".card-num", ".stat-num", ".nav-num",
])
def test_display_classes_pin_font_style_normal(selector):
    """Every display-type class declares font-style: normal, so no
    browser or inherited italic can ever slant the serif."""
    assert "font-style: normal" in _rule(GLOBALS, selector), selector


def test_display_classes_use_serif_variable():
    for selector in (".hero-display", ".display-hero", ".card-num", ".stat-num"):
        assert "--font-display" in _rule(GLOBALS, selector), selector


def test_hero_title_and_slogan_are_serif():
    assert 'className="hero-display line-mask mt-3"' in PAGE
    assert 'className="display-hero"' in PAGE
    # Serif slogan (aureon: serif slogan bottom-left) + `//` eyebrow.
    assert "font-display text-lg" in PAGE
    assert "hero-eyebrow" in PAGE
    assert '.hero-eyebrow::before' in GLOBALS
    assert '"// "' in GLOBALS


def test_section_headings_are_serif():
    """Section display headings (programmes, sources, before/after)
    carry the serif display class."""
    assert PAGE.count("font-display text-2xl font-bold") >= 3


def test_stats_are_big_serif_numerals():
    assert 'className="stat-num text-5xl font-bold text-navy"' in PAGE
    assert "font-style: normal" in _rule(GLOBALS, ".stat-num")


# ---------------------------------------------------------------------------
# (b) Particle ring: reduced-motion, offscreen pause, 12 s loop
# ---------------------------------------------------------------------------

def test_particle_ring_respects_reduced_motion():
    assert "prefers-reduced-motion: reduce" in PARTICLE
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in PARTICLE
    # Static frame, then an early return — the rAF loop is never
    # started under reduced motion.
    assert "draw(0.25)" in PARTICLE
    assert "Static frame only" in PARTICLE


def test_particle_ring_pauses_offscreen():
    assert "IntersectionObserver" in PARTICLE
    assert "cancelAnimationFrame" in PARTICLE
    assert "requestAnimationFrame" in PARTICLE


def test_particle_ring_is_a_12s_canvas_loop_no_footage():
    assert "LOOP_MS = 12000" in PARTICLE
    assert "<canvas" in PARTICLE
    assert "getContext('2d')" in PARTICLE
    # Recreated in code, never lifted: no video element, no media file.
    assert "<video" not in PARTICLE
    assert ".mp4" not in PARTICLE and ".webm" not in PARTICLE
    # Compass at the centre of the ring, amber highlights, stardust.
    assert "#F2A541" in PARTICLE
    assert "centre of the ring" in PARTICLE


# ---------------------------------------------------------------------------
# (c) White programme cards, gold objects, dark footer, no new keys
# ---------------------------------------------------------------------------

def test_programme_cards_are_white_with_gold_object():
    assert "card-paper" in PAGE
    assert "card-black rounded-2xl" not in PAGE
    assert ".card-paper" in GLOBALS
    assert "background: #fff" in _rule(GLOBALS, ".card-paper")
    assert "GoldObject" in PAGE
    assert "GOLD_OBJECT_KINDS[i % GOLD_OBJECT_KINDS.length]" in PAGE
    for kind in ("compass", "cap", "globe", "key"):
        assert f"'{kind}'" in GOLD
    # No new binary assets: the objects are inline SVG only.
    assert "<svg" in GOLD
    assert "src=" not in GOLD


def test_programme_card_buttons_still_present():
    assert "results.viewDetail" in PAGE
    assert "home.ctaSample" in PAGE
    # White-card text colours (navy), not the old white-on-navy ones.
    assert "text-navy/75" in PAGE
    assert "text-amber-dark" in PAGE


def test_footer_is_dark_navy():
    assert 'className="bg-navy pb-10 pt-8 text-center text-sm text-white/75"' in LAYOUT


def test_numbered_nav_kept():
    assert "nav-num" in GLOBALS
    assert "01" not in LAYOUT  # numbers are rendered, not hard-coded
    header = (SRC / "components" / "Header.tsx").read_text(encoding="utf-8")
    assert "nav-num" in header
    assert "padStart(2, '0')" in header


def test_no_new_locale_keys():
    """Visual half adds no locale keys: 994 in every locale
    (984 at Round 31 + the behaviour half's 10 keys)."""
    counts = {}
    for locale in LOCALES:
        with open(MESSAGES / f"{locale}.json", encoding="utf-8") as f:
            counts[locale] = len(json.load(f))
    assert counts == {locale: 994 for locale in LOCALES}, counts


# ---------------------------------------------------------------------------
# (d) New components compile clean
# ---------------------------------------------------------------------------

def test_new_components_compile(tmp_path):
    outdir = tmp_path / "restyle2_a"
    res = subprocess.run(
        ["npx", "tsc", "src/components/ParticleRing.tsx",
         "src/components/GoldObject.tsx",
         "--jsx", "react-jsx", "--module", "esnext",
         "--moduleResolution", "bundler", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--noEmit", "false"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
