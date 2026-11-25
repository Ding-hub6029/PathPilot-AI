"""Schema tests for data/expansions/applicant_routes.json (Job 1, Day 3).

Every factual claim must carry a non-empty source_url + retrieved_at.
Unknowns must be explicit (a non-empty list of strings), never silently
absent. No U.S. News content anywhere. Stdlib only.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "expansions" / "applicant_routes.json"

REQUIRED_BACKGROUND_FIELDS = {
    "id", "name", "name_zh", "national_exam", "notes",
    "academic_routes", "admission_tests", "language_tests",
    "foundation_routes", "deadlines", "unknowns", "sources",
}

# fact array -> required fields per fact
FACT_FIELDS = {
    "academic_routes": {"route", "detail", "source_url", "retrieved_at"},
    "admission_tests": {"test", "required_for", "detail", "source_url", "retrieved_at"},
    "language_tests": {"test", "detail", "source_url", "retrieved_at"},
    "foundation_routes": {"route", "detail", "source_url", "retrieved_at"},
    "deadlines": {"event", "date", "source_url", "retrieved_at"},
}


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def parse_iso(value):
    """ISO 8601 with Z or numeric offset."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_file_loads_and_version():
    data = load()
    assert data["data_version"] == "v1"
    assert isinstance(data["backgrounds"], list)
    assert len(data["backgrounds"]) >= 9


def test_background_ids_unique_and_fields_present():
    data = load()
    ids = [b["id"] for b in data["backgrounds"]]
    assert len(ids) == len(set(ids)), f"duplicate background ids: {ids}"
    for b in data["backgrounds"]:
        missing = REQUIRED_BACKGROUND_FIELDS - set(b)
        assert not missing, f"{b.get('id')}: missing fields {missing}"
        for field in ("id", "name", "name_zh", "national_exam", "notes"):
            assert isinstance(b[field], str) and b[field].strip(), (
                f"{b['id']}: {field} must be a non-empty string"
            )


def test_china_entry_is_a_summary_not_new_research():
    data = load()
    china = [b for b in data["backgrounds"] if b["id"] == "china-gaokao"]
    assert len(china) == 1
    assert "gaokao" in china[0]["notes"].lower()


def test_every_fact_has_source_and_retrieved_at():
    data = load()
    for b in data["backgrounds"]:
        for array, fields in FACT_FIELDS.items():
            facts = b[array]
            assert isinstance(facts, list), f"{b['id']}: {array} must be a list"
            for fact in facts:
                missing = fields - set(fact)
                assert not missing, (
                    f"{b['id']}/{array}: missing fields {missing} in {fact}"
                )
                for field in fields:
                    value = fact[field]
                    assert isinstance(value, str) and value.strip(), (
                        f"{b['id']}/{array}: {field} must be a non-empty string: {fact}"
                    )
                assert fact["source_url"].startswith(("http://", "https://")), (
                    f"{b['id']}/{array}: source_url must be a URL: {fact['source_url']}"
                )
                parse_iso(fact["retrieved_at"])  # raises if not ISO 8601


def test_every_fact_source_is_registered():
    data = load()
    for b in data["backgrounds"]:
        registered = {s["url"] for s in b["sources"]}
        assert registered, f"{b['id']}: sources must not be empty"
        for array in FACT_FIELDS:
            for fact in b[array]:
                assert fact["source_url"] in registered, (
                    f"{b['id']}/{array}: source_url not in sources: "
                    f"{fact['source_url']}"
                )


def test_sources_have_unique_ids_and_urls():
    data = load()
    for b in data["backgrounds"]:
        ids = [s["id"] for s in b["sources"]]
        assert len(ids) == len(set(ids)), f"{b['id']}: duplicate source ids"
        for s in b["sources"]:
            assert s["id"].strip() and s["url"].strip(), (
                f"{b['id']}: source id/url must be non-empty: {s}"
            )
            assert s["url"].startswith(("http://", "https://"))
            parse_iso(s["retrieved_at"])


def test_unknowns_are_explicit():
    data = load()
    for b in data["backgrounds"]:
        unknowns = b["unknowns"]
        assert isinstance(unknowns, list) and unknowns, (
            f"{b['id']}: unknowns must be a non-empty list — "
            "unknowns are explicit, not silently absent"
        )
        for item in unknowns:
            assert isinstance(item, str) and item.strip(), (
                f"{b['id']}: each unknown must be a non-empty string"
            )


def test_no_empty_strings_anywhere_in_facts():
    data = load()

    def walk(value, path):
        if isinstance(value, str):
            assert value.strip(), f"empty string at {path}"
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")

    for b in data["backgrounds"]:
        for array in FACT_FIELDS:
            walk(b[array], f"{b['id']}.{array}")


def test_no_us_news_content():
    text = DATA.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "u.s. news" not in lowered
    assert "usnews" not in lowered
    assert "u.s.news" not in lowered


def test_no_placeholder_text():
    text = DATA.read_text(encoding="utf-8")
    for placeholder in ("TODO", "TBD", "XXX", "Lorem ipsum"):
        assert placeholder not in text, f"placeholder {placeholder!r} in data file"
