"""Schema tests for the school-reviews collection (Day 3).

Source: data/expansions/school_reviews.json — verbatim student quotes about
the experience of studying at a university, each with a public source URL.
See docs/SCHOOL_REVIEWS.md for method, coverage and gaps.

Run from the project root:
    .venv/bin/python -m pytest tests/test_school_reviews.py -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

DATA = Path(__file__).resolve().parent.parent / "data" / "expansions" / "school_reviews.json"
RANKINGS = (
    Path(__file__).resolve().parent.parent / "data" / "versions" / "v2" / "rankings.json"
)

LABEL = "网友分享，未经官方核实"

REQUIRED_FIELDS = {
    "id",
    "institution",
    "institution_id",
    "programme",
    "level",
    "quote",
    "quote_lang",
    "quote_zh",
    "author_display",
    "source",
    "source_url",
    "posted_date",
    "retrieved_at",
    "label",
}

ALLOWED_LEVELS = {"undergraduate", "taught_masters", None}

# institution_ids in rankings.json that could not be matched would be listed
# here by the test run; this pass matched all of them, so the list is empty.
# Keep the constant so a future collection pass has somewhere to declare
# unmatched ids explicitly instead of silently passing.
KNOWN_UNMATCHED_INSTITUTION_IDS: set[str] = set()

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture(scope="module")
def payload():
    return json.loads(DATA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reviews(payload):
    assert isinstance(payload.get("reviews"), list)
    assert payload["reviews"], "school_reviews.json must not be empty"
    return payload["reviews"]


@pytest.fixture(scope="module")
def ranking_ids():
    data = json.loads(RANKINGS.read_text(encoding="utf-8"))
    return {i["id"] for i in data.get("institutions", [])}


def test_file_has_meta_with_matching_total(payload, reviews):
    meta = payload.get("meta", {})
    assert meta.get("total_reviews") == len(reviews)
    assert meta.get("label") == LABEL


def test_required_fields_present(reviews):
    for r in reviews:
        missing = REQUIRED_FIELDS - set(r.keys())
        assert not missing, f"{r.get('id')}: missing fields {sorted(missing)}"


def test_ids_unique_and_prefixed(reviews):
    ids = [r["id"] for r in reviews]
    assert len(ids) == len(set(ids)), "duplicate review ids"
    assert all(i.startswith("sr-") for i in ids)


def test_label_fixed_value(reviews):
    for r in reviews:
        assert r["label"] == LABEL, f"{r['id']}: label must be {LABEL!r}"


def test_quotes_nonempty_and_no_rating_field(reviews):
    for r in reviews:
        assert isinstance(r["quote"], str) and len(r["quote"].strip()) >= 10, (
            f"{r['id']}: quote too short to be a real review excerpt"
        )
        assert isinstance(r["quote_zh"], str) and r["quote_zh"].strip(), (
            f"{r['id']}: quote_zh (collector translation) must be present"
        )
        assert r["quote_lang"] == "en"
        # PathPilot does not collect ratings: no rating field may appear.
        assert not any("rating" in k.lower() or "score" in k.lower() for k in r), (
            f"{r['id']}: rating/score fields are forbidden"
        )


def test_source_urls_are_valid_http_urls(reviews):
    for r in reviews:
        parsed = urlparse(r["source_url"])
        assert parsed.scheme in {"http", "https"}, f"{r['id']}: bad scheme"
        assert parsed.netloc, f"{r['id']}: source_url has no host"
        assert isinstance(r["source"], str) and r["source"].strip()


def test_dates_are_yyyy_mm_dd(reviews):
    for r in reviews:
        assert DATE_RE.match(r["retrieved_at"]), f"{r['id']}: bad retrieved_at"
        if r["posted_date"] is not None:
            assert DATE_RE.match(r["posted_date"]), f"{r['id']}: bad posted_date"


def test_levels_are_undergraduate_taught_masters_or_null(reviews):
    for r in reviews:
        assert r["level"] in ALLOWED_LEVELS, f"{r['id']}: bad level {r['level']!r}"


def test_institution_ids_match_rankings(reviews, ranking_ids):
    unmatched = sorted(
        {r["institution_id"] for r in reviews} - ranking_ids - KNOWN_UNMATCHED_INSTITUTION_IDS
    )
    assert not unmatched, (
        f"institution_ids with no match in rankings.json: {unmatched} "
        "(add to KNOWN_UNMATCHED_INSTITUTION_IDS only with a note in "
        "docs/SCHOOL_REVIEWS.md)"
    )


def test_institution_names_match_rankings(reviews, ranking_ids):
    # Every institution_id used must be a real rankings id (covered above);
    # the display name must also be non-empty and consistent per id.
    names_by_id: dict[str, set[str]] = {}
    for r in reviews:
        assert r["institution"].strip()
        names_by_id.setdefault(r["institution_id"], set()).add(r["institution"])
    for inst_id, names in names_by_id.items():
        assert len(names) == 1, f"{inst_id}: conflicting names {names}"


def test_no_contact_info_in_quotes(reviews):
    # No phone / email / WeChat handle may be recorded in any text field.
    contact_re = re.compile(
        r"(\+?\d[\d\s\-]{7,}\d|[\w.+-]+@[\w-]+\.[\w.]+|微信|WeChat\s*[:：]?\s*[A-Za-z0-9_]+)",
        re.IGNORECASE,
    )
    for r in reviews:
        for field in ("quote", "quote_zh", "author_display"):
            assert not contact_re.search(r[field] or ""), (
                f"{r['id']}: possible contact info in {field}"
            )


def test_meta_counts_match_reviews(payload, reviews):
    # The meta block is hand-written by the collector and was wrong once
    # (UK 10 vs 11, US 2 vs 1) while test_file_has_meta_with_matching_total
    # still passed — it only checked total_reviews. Every meta breakdown
    # must recompute exactly from the reviews themselves.
    meta = payload.get("meta", {})
    total = len(reviews)

    # Countries: recompute from rankings.json (institution_id -> country_name).
    ranking_data = json.loads(RANKINGS.read_text(encoding="utf-8"))
    country_by_id = {
        i["id"]: i["country_name"] for i in ranking_data.get("institutions", [])
    }
    by_country: dict[str, int] = {}
    for r in reviews:
        name = country_by_id.get(r["institution_id"])
        assert name, f"{r['id']}: no country_name in rankings.json"
        by_country[name] = by_country.get(name, 0) + 1
    assert meta.get("countries") == by_country, (
        f"meta.countries {meta.get('countries')} != recomputed {by_country}"
    )

    # Sources, institutions and levels must also sum to the total.
    by_source: dict[str, int] = {}
    for r in reviews:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    assert meta.get("sources") == by_source, (
        f"meta.sources {meta.get('sources')} != recomputed {by_source}"
    )
    assert meta.get("institutions") == len({r["institution_id"] for r in reviews})
    levels = meta.get("levels", {})
    assert sum(levels.values()) == total, (
        f"meta.levels sums to {sum(levels.values())}, expected {total}"
    )
    by_level: dict[str, int] = {}
    for r in reviews:
        key = r["level"] if r["level"] is not None else "null"
        by_level[key] = by_level.get(key, 0) + 1
    assert levels == by_level, f"meta.levels {levels} != recomputed {by_level}"
