"""Round 34 H1 (BLOCKING) — Arabic hero title, JSX-level fix.

Re-test 29 (2026-11-28 20:48-21:19): Round 32's [dir="rtl"] CSS fix
(#319) is IN the deployed stylesheet — verified live in this round
by curling the served homepage and its CSS chunk
(https://pathpilot-ai-vert.vercel.app/): the exact rules are present
in the served CSS, AFTER the base rules, with higher specificity
than ``.line-mask > span`` — yet the Arabic hero title STILL renders
garbled live: on first switch the four lines show unjoined letters
with overlapping/duplicated glyphs; after a refresh the first three
lines stay clipped and only the last word is visible for 2+ minutes.
H2b and H3 passed in the same run, so the tester was on the new
build — this is not a stale-deploy artifact, and the CSS itself is
not stale either (see the live check above). The failure is WHEN the
override can fire, not WHETHER it exists:

* ``frontend/src/app/layout.tsx:31`` + live SSR — the server always
  ships ``<html lang="en" dir="ltr">`` with the ENGLISH hero. The
  Arabic title never exists before hydration.
* ``frontend/src/lib/store.tsx`` — ``locale`` starts ``'en'``; a
  mount effect restores ``pp-locale`` and sets ``hydrated``; a
  SECOND effect, gated on ``[locale, hydrated]``, sets
  ``document.documentElement.dir``. Passive effects run AFTER paint,
  so the Arabic text is committed into the SAME already-animating
  ``<span>`` (React text swap — RouteTransition keys by pathname,
  the Header switch is a bare ``setLocale``, nothing remounts, and a
  CSS animation does not restart on a text change) and painted at
  least once under the FULL LTR hazard stack — negative tracking
  (-.03em / -.02em), line-height .98 at up to 6.4rem, Fraunces
  variable-font metrics, 32px glow, mid-reveal ``translateY(110%)``
  inside ``overflow: hidden`` — before ``dir="rtl"`` can ever apply
  and the Round 32 ``animation: none`` can ever cancel anything.
  That one LTR-painted frame is exactly the observed garble:
  unjoined letters (negative tracking breaking cursive joining),
  overlapping lines/words (.98 leading at 6.4rem), duplicated
  glyphs (mid-reveal + glow smear across four wrapped lines).
* The 2+-minute stuck state after refresh is NOT explained by any
  static mechanism: a mid-``line-reveal`` freeze would show the
  FIRST lines at the bottom of the mask (the reveal slides the span
  UP from ``translateY(110%)``), never "only the last word", and
  every static check in this file says the settled state must be
  clean. What the live DOM was doing at that moment — computed style
  of the span, ``documentElement.dir`` at screenshot time, whether
  an animation was running — is unobserved from here. See "LIVE-DOM
  EVIDENCE STILL OWED" below; the JSX fix below makes all of it moot
  for ``ar`` by removing the hazards from the render path entirely.

Fix (JSX level, no new [dir="rtl"] override, no copy / data / route
/ key change): ``page.tsx`` branches on ``locale`` — React state,
known at render time, so the correct classes are in the DOM from
the FIRST commit, with no race against any effect, animation, or
stylesheet:

* ``locale === 'ar'`` renders ``<h1 className="hero-display-ar
  mt-3">{t('home.heroTitle')}</h1>`` — the text node directly, no
  inner span, no ``line-mask``, no ``hero-display``, no
  ``display-hero``.
* Every other locale renders the byte-identical pre-existing line:
  ``<h1 className="hero-display line-mask mt-3"><span
  className="display-hero" style={{ animationDelay: '.08s'
  }}>{t('home.heroTitle')}</span></h1>`` — en/zh pixel-identical
  by construction.
* ``.hero-display-ar`` (appended at the END of ``globals.css``,
  append-only) is a standalone class: same display size as the LTR
  hero (``clamp(3.2rem, 9.5vw, 6.4rem)``), system-ui (Fraunces is
  Latin-only), ``letter-spacing: 0``, ``line-height: 1.3``,
  ``text-shadow: none``, ``animation: none``, ``overflow: visible``.
  It is a plain class rule — it does not depend on ``[dir="rtl"]``.
* The Round 32 ``[dir="rtl"]`` block is left untouched (append-only
  rule for this round); it is now inert for the hero because the ar
  h1 no longer matches any of its selectors.

KNOWN PIN UPDATE OWED (coordinator): ``test_r32_h1_arabic_hero.py``
``test_hero_title_is_a_single_unbroken_text_node`` asserts
``PAGE.count("home.heroTitle") == 1``. The JSX branch needs the
title in BOTH branches, so the count is now 2 — one per branch, one
text node each, no splitting. That pin's INTENT (one unbroken text
node, no splitter) is re-pinned here as count == 2; the r32 pin
itself must be updated at integration, not silently left failing.
Everything else in the r32 file still passes (the RTL CSS rules,
LTR base rules, copy and 994-key pins are all untouched).

LIVE-DOM EVIDENCE STILL OWED (parent / browser re-test after push —
no test in this file, or in this repo, can see real Arabic shaping):
1. Switch to العربية on the live homepage and screenshot the hero
   immediately AND after 5 s: the title must render joined and
   unclipped on the first switch, with no transient garble frame.
2. Refresh with ``pp-locale=ar`` saved and watch 2+ minutes: all
   lines visible, no clipping, no stuck state.
3. In the same live session, record the computed style of the ar
   ``h1`` (``font-family``, ``letter-spacing``, ``line-height``,
   ``animation-name``, ``text-shadow``, ``overflow``) and
   ``document.documentElement.dir`` — to close the open question of
   what the re-test 29 DOM was doing when it stayed garbled.
4. Switch back to en/zh and confirm the hero is pixel-identical to
   before (mask entrance, serif, glow intact).

Run from the project root:
    .venv/bin/pytest tests/test_r34_h1_arabic_hero_jsx.py -q -p no:cacheprovider
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
STORE = (SRC / "lib" / "store.tsx").read_text(encoding="utf-8")
LAYOUT = (SRC / "app" / "layout.tsx").read_text(encoding="utf-8")

LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

AR_TITLE = "اعثر على طريقك إلى الجامعة المناسبة"

# The exact pre-existing (en/zh) hero line — byte-identical after fix.
LTR_HERO_LINE = (
    '<h1 className="hero-display line-mask mt-3">'
    '<span className="display-hero" style={{ animationDelay: '
    "'.08s' }}>{t('home.heroTitle')}</span></h1>"
)
AR_HERO_LINE = (
    '<h1 className="hero-display-ar mt-3">{t('
    "'home.heroTitle')}</h1>"
)


def _blocks(css: str, selector: str) -> list[str]:
    blocks = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert blocks, f"no CSS rule for {selector}"
    return blocks


def _rule(css: str, selector: str) -> str:
    """Every block for a selector, joined (some selectors are
    declared twice — e.g. .hero-display sets the type scale first,
    the font family later)."""
    return " ".join(_blocks(css, selector))


def _ar_branch() -> str:
    """The true-branch of the locale ternary in page.tsx — the
    markup rendered when locale is 'ar'."""
    m = re.search(
        r"\{locale === 'ar' \? \(\s*(.*?)\s*\) : \(",
        PAGE,
        re.S,
    )
    assert m, "no `locale === 'ar'` ternary around the hero h1 in page.tsx"
    return m.group(1)


# ---------------------------------------------------------------------------
# (a) The branch: locale state at render time, not dir after paint
# ---------------------------------------------------------------------------

def test_hero_branches_on_locale_render_state():
    """The fix keys on `locale` (React state, known at render time),
    not on documentElement.dir (a post-paint DOM mutation). The
    correct classes are therefore in the DOM from the first commit —
    there is no frame in which Arabic can be painted under LTR rules."""
    assert "const { t, tf, locale, profile, setProfile } = useApp();" in PAGE
    assert "{locale === 'ar' ? (" in PAGE
    # page.tsx itself never reads the DOM dir — the branch cannot be
    # hostage to effect timing.
    assert "document.documentElement" not in PAGE
    assert "document." not in PAGE


def test_dir_timing_race_still_documented_in_store():
    """Pin the premise the JSX fix removes the dependency on: SSR
    ships dir=ltr and dir is only flipped by a post-paint passive
    effect gated on [locale, hydrated]. If the store ever sets dir
    synchronously (or SSR ships the locale), this pin names the
    place that changed — the JSX branch stays correct either way."""
    assert '<html lang="en" dir="ltr"' in LAYOUT
    assert "document.documentElement.dir" in STORE
    assert "RTL_LOCALES.includes(locale)" in STORE


# ---------------------------------------------------------------------------
# (b) The ar branch: no hazard class, no span, no animation
# ---------------------------------------------------------------------------

def test_ar_h1_line_is_present_and_hazard_free():
    """The ar h1 carries ONLY .hero-display-ar (plus the mt-3
    margin): no line-mask (no overflow:hidden mask, no reveal), no
    hero-display (no -.03em tracking), no display-hero (no Fraunces,
    no .98 leading, no glow)."""
    assert AR_HERO_LINE in PAGE
    branch = _ar_branch()
    assert branch.strip() == AR_HERO_LINE
    assert "line-mask" not in branch
    assert "display-hero" not in branch
    assert "hero-display " not in branch  # bare .hero-display class
    assert 'className="hero-display"' not in branch


def test_ar_h1_has_no_inner_span_and_no_animation():
    """The ar title is the h1's own text node — no inner span to
    animate, no inline animationDelay, nothing that can be caught
    mid-reveal. A second animation/transition on this path would
    reintroduce the exact defect."""
    branch = _ar_branch()
    assert "<span" not in branch
    assert "animationDelay" not in branch
    assert "animation" not in branch
    assert "transition" not in branch


def test_ar_title_is_one_unbroken_text_node_per_branch():
    """Each branch holds exactly one {t('home.heroTitle')} text node
    — no per-word / per-line splitting of the Arabic text exists to
    break letter joining. The count is 2 (one per branch), NOT 1:
    this supersedes the r32 count==1 pin, which the coordinator must
    update at integration (see the module docstring)."""
    assert PAGE.count("home.heroTitle") == 2, PAGE.count("home.heroTitle")
    assert AR_HERO_LINE in PAGE
    assert LTR_HERO_LINE in PAGE
    assert ".split(" not in PAGE


def test_no_split_text_helper_anywhere_in_frontend_src():
    """No component splits heading text into per-word/per-line
    masked spans (the mechanism the original brief asked to check
    first)."""
    for path in SRC.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert "splitText" not in text and "SplitText" not in text, path


# ---------------------------------------------------------------------------
# (c) The en/zh branch: byte-identical, pixel-identical
# ---------------------------------------------------------------------------

def test_en_branch_byte_identical():
    """The non-ar branch is the exact pre-existing hero line,
    character for character — en/zh render pixel-identical to today
    (same mask entrance, same serif, same glow)."""
    assert LTR_HERO_LINE in PAGE
    assert 'className="display-hero"' in PAGE


def test_ltr_hero_design_unchanged():
    """The base (LTR) hero keeps its tight tracking, .98 leading,
    Fraunces stack and glow: the fix is additive and branch-scoped,
    not a redesign of the LTR hero."""
    base = _blocks(GLOBALS, ".display-hero")[0]
    assert "letter-spacing: -.02em" in base
    assert "line-height: .98" in base
    assert "--font-display" in base
    assert "text-shadow: 0 0 32px" in base
    assert "font-style: normal" in base


def test_base_line_mask_animation_still_present():
    """The mask reveal itself is not deleted — only the ar hero opts
    out by never rendering the mask. Other headings and LTR keep the
    entrance."""
    assert "animation: line-reveal .7s var(--ease-reveal) both" in _rule(
        GLOBALS, ".line-mask > span"
    )


# ---------------------------------------------------------------------------
# (d) The new class: standalone, safe Arabic typography, appended
# ---------------------------------------------------------------------------

def test_hero_display_ar_class_is_safe_typography():
    """System font (Fraunces is Latin-only), no negative tracking,
    roomy leading for diacritics, no glow, no animation, no clipping
    mask — the whole Arabic-hostile cluster neutralised in one
    class, not scattered across overrides."""
    rule = _rule(GLOBALS, ".hero-display-ar")
    assert "font-family: system-ui, sans-serif" in rule
    assert "--font-display" not in rule
    assert "letter-spacing: 0" in rule
    m = re.search(r"line-height:\s*([0-9.]+)", rule)
    assert m, "no line-height on .hero-display-ar"
    assert float(m.group(1)) >= 1.3, m.group(1)
    assert "text-shadow: none" in rule
    assert "animation: none" in rule
    assert "overflow: visible" in rule
    assert "font-style: normal" in rule
    assert "font-weight: 700" in rule


def test_hero_display_ar_keeps_display_scale():
    """The ar hero keeps the LTR display size — same clamp as
    .display-hero — so the Arabic hero does not shrink into a body
    heading when the hazards are removed."""
    assert "font-size: clamp(3.2rem, 9.5vw, 6.4rem)" in _rule(
        GLOBALS, ".hero-display-ar"
    )
    assert "font-size: clamp(3.2rem, 9.5vw, 6.4rem)" in _rule(
        GLOBALS, ".display-hero"
    )


def test_hero_display_ar_is_a_plain_class_rule():
    """The class must not depend on [dir="rtl"] (or any dir
    attribute): it applies because React rendered it, not because
    an effect flipped a DOM attribute after paint."""
    m = re.search(r"(^|\n)\.hero-display-ar\s*\{[^}]*\}", GLOBALS)
    assert m, ".hero-display-ar is not a plain top-level class rule"
    assert "dir=" not in m.group(0)


def test_new_class_appended_after_round_32_block():
    """Append-only: the new class lives at the END of globals.css,
    after the Round 32 [dir=\"rtl\"] hero block — nothing earlier in
    the file was edited, moved, or deleted for this round."""
    rtl_pos = GLOBALS.find('[dir="rtl"] h1.hero-display.line-mask > span')
    assert rtl_pos > 0, "Round 32 RTL hero block missing"
    ar_pos = GLOBALS.find(".hero-display-ar {")
    assert ar_pos > 0, ".hero-display-ar rule missing"
    comment_pos = GLOBALS.find("Round 34 H1")
    assert comment_pos > 0, "Round 34 H1 comment missing"
    # Comment, then rule, both after the Round 32 block: appended
    # at the END of the file, nothing earlier moved or deleted.
    assert rtl_pos < comment_pos < ar_pos


def test_no_new_dir_rtl_hero_override():
    """This round adds NO new [dir=\"rtl\"] hero override — the fix is
    the JSX branch, not another CSS patch on the same failed
    mechanism. The three Round 32 hero rules stay exactly as they
    were (append-only: untouched, now inert for the hero because the
    ar h1 matches none of their selectors)."""
    assert re.search(
        r'\[dir="rtl"\]\s+\.hero-display,\s*\[dir="rtl"\]\s+\.display-hero'
        r"\s*\{\s*letter-spacing:\s*0;",
        GLOBALS,
    )
    assert re.search(
        r'\[dir="rtl"\]\s+h1\.hero-display\.line-mask\s*>\s*span'
        r"\s*\{\s*animation:\s*none;",
        GLOBALS,
    )
    # Strip comments first: the Round 34 comment itself mentions
    # [dir="rtl"] and .hero-display-ar, and a naive scan would match
    # across it into the rule.
    no_comments = re.sub(r"/\*.*?\*/", "", GLOBALS, flags=re.S)
    rtl_blocks = re.findall(r'\[dir="rtl"\][^{]*\{[^}]*\}', no_comments)
    assert rtl_blocks, "no [dir=\"rtl\"] rules found at all"
    assert not any("hero-display-ar" in b for b in rtl_blocks)


def test_no_oblique_or_italic_font_style_in_globals():
    """Synthetic slant breaks Arabic joining (Round 30 F4). No
    `font-style: oblique` / `font-style: italic` declaration may
    appear in globals.css — including in the new class."""
    bad = re.compile(r"font-style\s*:\s*(oblique|italic)")
    assert bad.search(GLOBALS) is None


# ---------------------------------------------------------------------------
# (e) No copy, data or locale-key change
# ---------------------------------------------------------------------------

def test_hero_copy_unchanged_in_all_locales():
    """No copy change: the ar title is the exact string from
    re-test 28/29, and en/zh are untouched."""
    with open(MESSAGES / "ar.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == AR_TITLE
    with open(MESSAGES / "en.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == (
            "Find your route to the right university"
        )
    with open(MESSAGES / "zh-CN.json", encoding="utf-8") as f:
        assert json.load(f)["home.heroTitle"] == "找到通往理想大学的路线"


def test_no_new_locale_keys():
    """JSX + CSS fix: still 994 keys in every locale."""
    counts = {}
    for locale in LOCALES:
        with open(MESSAGES / f"{locale}.json", encoding="utf-8") as f:
            counts[locale] = len(json.load(f))
    assert counts == {locale: 994 for locale in LOCALES}, counts


# ---------------------------------------------------------------------------
# (f) The Round 33 stats strip is untouched by this round
# ---------------------------------------------------------------------------

def test_round_33_stats_strip_untouched():
    """This worker's only page.tsx edit is the hero h1. The Round 33
    stats strip (4th card = live ranking-records count) must be
    exactly as Round 33 left it."""
    assert "[RANKING_ENTRIES.length, t('home.rankingRecords')]" in PAGE
    assert "home.rankingRecords" in PAGE
    assert "LOCALES.length" not in PAGE
    assert "common.languages" not in PAGE
