"""Round 32 H1 (BLOCKING) — Arabic hero title renders garbled.

Re-test 28 (2026-11-28 18:44-18:55, gateway down whole run): the
Arabic homepage hero title "اعثر على طريقك إلى الجامعة المناسبة"
renders garbled — words overlap multiple times ("اعثر" appearing
three times), basically unreadable, reproduced across language
switches and confirmed zoomed in. English and Chinese titles are
fine. This is a Restyle 2 regression: re-test 27 (Round 31, Space
Grotesk, no oblique) had a clean Arabic title.

Root cause (verified in code, not a guess about one property): the
hero title combines every Arabic-hostile property at once, on a
single element:

* ``frontend/src/app/page.tsx:86`` — the h1 holds ONE text node
  (``{t('home.heroTitle')}`` inside a single ``<span>``). There is
  NO JS per-word / per-line splitting anywhere in the codebase
  (no split helper, no word map), so the "splitting" in the task
  brief is the CSS line-mask, not code that can be "unsplit".
* ``frontend/src/app/globals.css:53`` — the h1 (``.hero-display``)
  sets ``letter-spacing: -.03em``.
* ``frontend/src/app/globals.css:291`` — the span
  (``.display-hero``) sets ``letter-spacing: -.02em``,
  ``line-height: .98`` at up to ``6.4rem``, and a 32px-blur
  ``text-shadow``. Negative tracking pulls each Arabic glyph back
  over the previous glyph's exit stroke and breaks cursive
  joining (same class of break as the Round 30 F4 oblique, which
  is why F4's ``font-style: normal`` pin alone did not save it);
  ``.98`` leading stacks the title's ~3 wrapped lines (6.4rem in
  the 7-column hero) with almost no leading, so tall Arabic
  ascenders / diacritics collide with the line above and words
  from adjacent lines overlap; the 32px glow smears the glyphs
  further.
* ``frontend/src/app/globals.css:59-60`` + ``:39`` — the
  ``.line-mask`` reveal (``translateY(110%)`` inside
  ``overflow: hidden``) replays on every locale switch, so the
  title is repeatedly caught mid-reveal.
* ``frontend/src/app/layout.tsx:17-22`` — Fraunces is Latin-only
  (``subsets: ['latin']``), so Arabic falls back to the system
  font; the variable font's metrics still drive the line box.
  Round 30 F4 (#310) already proved this stack is fragile for
  Arabic; Restyle 2 (#316) swapped Space Grotesk for Fraunces
  and the defect came back worse.

Fix (CSS only, RTL-scoped, no copy / data / route / key change):
``globals.css`` gains a ``[dir="rtl"]`` override block right after
the ``.display-hero`` rule — ``letter-spacing: 0`` on both the h1
and the span, ``font-family: system-ui, sans-serif`` (Fraunces out
of the stack, so no variable-font metrics leak into the Arabic
line box), ``line-height: 1.3`` for diacritic room,
``text-shadow: none``, and ``animation: none`` on the hero's
line-mask span only. ``[dir="rtl"]`` is the convention this file
already uses, and ``store.tsx`` sets ``documentElement.dir =
'rtl'`` for ``ar``. The LTR design (en/zh) is pixel-identical:
base rules, mask animation and glow are untouched.

Run from the project root:
    .venv/bin/pytest tests/test_r32_h1_arabic_hero.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
SRC = FE / "src"
MESSAGES = FE / "messages"

GLOBALS = (SRC / "app" / "globals.css").read_text(encoding="utf-8")
PAGE = (SRC / "app" / "page.tsx").read_text(encoding="utf-8")
LAYOUT = (SRC / "app" / "layout.tsx").read_text(encoding="utf-8")
STORE = (SRC / "lib" / "store.tsx").read_text(encoding="utf-8")

LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

AR_TITLE = "اعثر على طريقك إلى الجامعة المناسبة"


def _blocks(css: str, selector: str) -> list[str]:
    blocks = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert blocks, f"no CSS rule for {selector}"
    return blocks


def _rule(css: str, selector: str) -> str:
    """Every block for a selector, joined (some selectors are
    declared twice — e.g. .hero-display sets the type scale first,
    the font family later)."""
    return " ".join(_blocks(css, selector))


# ---------------------------------------------------------------------------
# (a) The hero title is one unbroken text node — nothing splits it
# ---------------------------------------------------------------------------

def test_hero_title_is_a_single_unbroken_text_node():
    """Each locale branch holds exactly one span/text node holding
    exactly one {t('home.heroTitle')} — no per-word / per-line
    splitting of the Arabic text exists to break letter joining. If
    anyone re-adds a splitter, this pin fails first.
    Round 34 (H1, JSX-level fix): the title is now branched — ar
    renders a plain h1 with no line-mask/display-hero hazards, en/zh
    keep the old line. So the key occurs twice (once per branch),
    each occurrence an unbroken text node."""
    assert 'className="hero-display line-mask mt-3"' in PAGE
    assert (
        '<span className="display-hero" style={{ animationDelay: '
        "'.08s' }}>{t('home.heroTitle')}</span>"
    ) in PAGE
    assert (
        '<h1 className="hero-display-ar mt-3">{t(\'home.heroTitle\')}</h1>'
        in PAGE
    )
    assert PAGE.count("home.heroTitle") == 2
    assert ".split(" not in PAGE


def test_no_split_text_helper_anywhere_in_frontend_src():
    """No component splits heading text into per-word/per-line
    masked spans (the mechanism the brief asked to check first)."""
    for path in SRC.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert "splitText" not in text and "SplitText" not in text, path


# ---------------------------------------------------------------------------
# (b) RTL override: neutralise the Arabic-hostile cluster on the hero
# ---------------------------------------------------------------------------

def test_rtl_hero_letter_spacing_is_zero():
    """Negative tracking (-.03em h1 / -.02em span) breaks Arabic
    joining. In RTL both are reset to 0 by one combined rule."""
    assert re.search(
        r'\[dir="rtl"\]\s+\.hero-display,\s*\[dir="rtl"\]\s+\.display-hero'
        r"\s*\{\s*letter-spacing:\s*0;",
        GLOBALS,
    ), "RTL letter-spacing: 0 rule missing for hero title"


def test_rtl_hero_line_height_is_roomy():
    """line-height .98 stacks the ~3 wrapped Arabic lines onto each
    other. In RTL the span gets 1.3 for diacritic room."""
    rtl = _rule(GLOBALS, '[dir="rtl"] .display-hero')
    m = re.search(r"line-height:\s*([0-9.]+)", rtl)
    assert m, "no RTL line-height on .display-hero"
    assert float(m.group(1)) >= 1.25, m.group(1)


def test_rtl_hero_drops_fraunces_and_glow():
    """Fraunces is Latin-only; its variable-font metrics must not
    drive the Arabic line box, and the 32px glow must not smear the
    glyphs. In RTL the span falls back to system-ui with no shadow."""
    rtl = _rule(GLOBALS, '[dir="rtl"] .display-hero')
    assert "font-family: system-ui, sans-serif" in rtl
    assert "--font-display" not in rtl
    assert "text-shadow: none" in rtl


def test_rtl_hero_line_mask_entrance_disabled():
    """The translateY(110%) mask reveal replays on every locale
    switch. In RTL it is off for the hero title only — the title
    renders settled as a single text node."""
    assert re.search(
        r'\[dir="rtl"\]\s+h1\.hero-display\.line-mask\s*>\s*span'
        r"\s*\{\s*animation:\s*none;",
        GLOBALS,
    ), "RTL animation: none rule missing for hero line-mask span"


def test_rtl_scoping_hook_exists_in_store():
    """The [dir=\"rtl\"] CSS only fires because store.tsx sets
    documentElement.dir = 'rtl' for ar. Pin the hook, not just the
    CSS."""
    assert "RTL_LOCALES" in STORE
    assert "document.documentElement.dir" in STORE
    assert "'rtl'" in STORE or '"rtl"' in STORE


# ---------------------------------------------------------------------------
# (c) The Round 30 F4 lesson still holds: no slant anywhere
# ---------------------------------------------------------------------------

def test_no_oblique_or_italic_font_style_in_globals():
    """Synthetic slant breaks Arabic joining (Round 30 F4). No
    `font-style: oblique` / `font-style: italic` declaration may
    appear in globals.css."""
    bad = re.compile(r"font-style\s*:\s*(oblique|italic)")
    assert bad.search(GLOBALS) is None
    assert "font-style: normal" in _blocks(GLOBALS, ".display-hero")[0]
    # .hero-display is declared twice (type scale first, font family
    # later) — the font-style pin lives in the later block.
    assert "font-style: normal" in _rule(GLOBALS, ".hero-display")


# ---------------------------------------------------------------------------
# (d) LTR design untouched — the fix is additive and RTL-scoped
# ---------------------------------------------------------------------------

def test_ltr_hero_design_unchanged():
    """The base (LTR) hero keeps its tight tracking, .98 leading,
    Fraunces stack and glow: en/zh render exactly as before."""
    base = _blocks(GLOBALS, ".display-hero")[0]
    assert "letter-spacing: -.02em" in base
    assert "line-height: .98" in base
    assert "--font-display" in base
    assert "text-shadow: 0 0 32px" in base
    assert "font-style: normal" in base


def test_base_line_mask_animation_still_present():
    """The mask reveal itself is not deleted — only the RTL hero
    span opts out. Other headings and LTR keep the entrance."""
    assert "animation: line-reveal .7s var(--ease-reveal) both" in _rule(
        GLOBALS, ".line-mask > span"
    )


# ---------------------------------------------------------------------------
# (e) No copy, data or locale-key change
# ---------------------------------------------------------------------------

def test_hero_copy_unchanged_in_all_locales():
    """No copy change: the ar title is the exact string from
    re-test 28, and en/zh are untouched."""
    with open(MESSAGES / "ar.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == AR_TITLE
    with open(MESSAGES / "en.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == (
            "Find your route to the right university"
        )
    with open(MESSAGES / "zh-CN.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == "找到通往理想大学的路线"


def test_no_new_locale_keys():
    """CSS-only fix: still 994 keys in every locale."""
    counts = {}
    for locale in LOCALES:
        with open(MESSAGES / f"{locale}.json", encoding="utf-8") as f:
            counts[locale] = len(json.load(f))
    assert counts == {locale: 994 for locale in LOCALES}, counts
