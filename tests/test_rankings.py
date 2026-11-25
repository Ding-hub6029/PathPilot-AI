"""Rankings endpoints (Day 3, spec Ch9 FR15/FR16, T20-T22, BR15/BR16).

Top 100 institutions per provider (QS 2027, THE 2027, ARWU 2026) = 300
entries, 148 institutions, verified against the official sources on
2026-11-25; see data/versions/v2/rankings.json and docs/RANKINGS_SOURCES.md.
A fourth provider was removed entirely on 2026-11-25 at the user's
direction — it must not appear in any endpoint, payload, file or test
(see DECISIONS.md #89).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.data import RANKINGS
from app.main import app, reset_rate_limits

client = TestClient(app)


def setup_function():
    reset_rate_limits()


def all_rankings(params=None):
    """Follow the cursor through every page (backend caps limit at 20)."""
    items = []
    cursor = None
    for _ in range(50):
        q = dict(params or {})
        if cursor:
            q["cursor"] = cursor
        r = client.get("/api/v1/rankings", params=q)
        assert r.status_code == 200
        body = r.json()
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    else:
        raise AssertionError("rankings pagination did not terminate")
    return items


def test_providers_lists_three_with_editions_and_rights():
    r = client.get("/api/v1/rankings/providers")
    assert r.status_code == 200
    providers = r.json()["providers"]
    assert [p["id"] for p in providers] == ["qs", "the", "arwu"]
    by_id = {p["id"]: p for p in providers}
    assert by_id["qs"]["edition_label"] == "2027"
    assert by_id["the"]["edition_label"] == "2027"
    assert by_id["arwu"]["edition_label"] == "2026"
    assert by_id["qs"]["rights_status"] == "conditional-attribution"
    assert "With permission" in (by_id["qs"]["attribution"] or "")
    assert by_id["the"]["rights_status"] == "permission-not-obtained"
    assert by_id["arwu"]["rights_status"] == "terms-unclear"


def test_editions_lists_one_per_provider():
    r = client.get("/api/v1/rankings/editions")
    assert r.status_code == 200
    editions = r.json()["editions"]
    assert len(editions) == 3
    assert {(e["provider"], e["edition_label"]) for e in editions} == {
        ("qs", "2027"), ("the", "2027"), ("arwu", "2026")}


def test_rankings_lists_three_hundred_entries_paginated():
    r = client.get("/api/v1/rankings")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 20  # default limit, capped at 20
    assert body["next_cursor"] is not None
    assert body["data_version"] == "v2"
    items = all_rankings()
    assert len(items) == 300
    keys = {(e["provider"], e["institution_id"]) for e in items}
    assert len(keys) == 300
    assert {e["provider"] for e in items} == {"qs", "the", "arwu"}


def test_rankings_filter_by_provider_and_country_and_query():
    assert len(all_rankings({"provider": "qs"})) == 100
    assert len(all_rankings({"provider": "the"})) == 100
    assert len(all_rankings({"provider": "arwu"})) == 100
    assert len(all_rankings({"provider": "QS"})) == 100  # case-insensitive
    assert len(all_rankings({"country": "SG"})) == 6  # NUS + NTU x 3 providers
    assert len(all_rankings({"country": "US"})) == 99
    assert len(all_rankings({"country": "GB"})) == 35
    assert len(all_rankings({"query": "National University"})) == 8
    assert len(all_rankings({"query": "University of California"})) == 15
    assert len(all_rankings({"ranking_type": "world"})) == 300
    assert len(all_rankings({"provider": "nosuchprovider"})) == 0


def test_rankings_subject_filter_returns_empty_not_invented():
    # No subject entries were verified for this build (RANKINGS_SOURCES.md
    # section 6); a subject rank must never be invented (T21).
    r = client.get("/api/v1/rankings", params={"subject": "Computer Science"})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_rankings_pagination_and_bad_cursor():
    r1 = client.get("/api/v1/rankings", params={"limit": 5})
    assert len(r1.json()["items"]) == 5
    cursor = r1.json()["next_cursor"]
    assert cursor
    r2 = client.get("/api/v1/rankings", params={"limit": 5, "cursor": cursor})
    assert len(r2.json()["items"]) == 5
    assert r2.json()["items"][0] != r1.json()["items"][0]
    r3 = client.get("/api/v1/rankings", params={"cursor": "!!!not-a-cursor"})
    assert r3.status_code == 400
    assert r3.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rank_display_verbatim_ties_and_scores():
    # Ties keep the '=' prefix exactly as published (T20); scores are the
    # provider-published overall scores, never computed by PathPilot.
    # The 12 original entries are unchanged.
    qs = {e["institution_id"]: e for e in all_rankings({"provider": "qs"})}
    assert qs["ucl"]["rank_display"] == "=8"
    assert qs["ucl"]["rank_kind"] == "tie"
    assert qs["imperial"]["rank_display"] == "=2"
    assert qs["nus"]["rank_display"] == "10"
    assert qs["nus"]["rank_kind"] == "single"
    assert qs["ntu"]["rank_display"] == "12"
    assert qs["imperial"]["score"] == 99.2
    assert qs["university-of-zurich"]["rank_display"] == "=98"  # QS top-100 last row
    assert qs["ecole-polytechnique-federale-de-lausanne"]["rank_display"] == "=22"  # EPFL, merged from 'EPFL'
    assert qs["universite-psl"]["rank_display"] == "34"  # merged from 'PSL University' / 'Université PSL'
    assert qs["korea-advanced-institute-of-science-and-technology"]["rank_display"] == "65"  # KAIST
    assert qs["lmu-munich"]["rank_display"] == "61"  # merged from 'Ludwig-Maximilians-Universität München'
    assert qs["heidelberg-university"]["rank_display"] == "86"
    the = {e["institution_id"]: e for e in all_rankings({"provider": "the"})}
    assert the["ucl"]["rank_display"] == "=17"
    assert the["imperial"]["rank_display"] == "8"
    assert the["nus"]["rank_display"] == "15"
    assert the["ntu"]["rank_display"] == "28"
    assert the["university-of-california-irvine"]["rank_display"] == "=97"  # THE top-100 last row
    assert the["ecole-polytechnique-federale-de-lausanne"]["rank_display"] == "36"
    assert the["universite-psl"]["rank_display"] == "57"
    assert the["heidelberg-university"]["rank_display"] == "=45"
    assert the["university-of-new-south-wales"]["rank_display"] == "=75"  # merged from 'UNSW Sydney'; tied with Institut Polytechnique de Paris
    arwu = {e["institution_id"]: e for e in all_rankings({"provider": "arwu"})}
    assert arwu["ucl"]["rank_display"] == "17"
    assert arwu["ucl"]["score"] == 49.4  # official payload wins over the image's 49.6
    assert arwu["imperial"]["rank_display"] == "29"
    assert arwu["nus"]["rank_display"] == "53"
    assert arwu["ntu"]["rank_display"] == "84"
    assert arwu["purdue-university"]["rank_display"] == "100"  # ARWU top-100 last row
    assert arwu["university-of-minnesota-twin-cities"]["rank_display"] == "52"
    assert arwu["university-of-minnesota-twin-cities"]["score"] == 33.4  # official payload wins over the image's 22.4
    assert arwu["ecole-polytechnique-federale-de-lausanne"]["rank_display"] == "=43"
    assert arwu["universite-psl"]["rank_display"] == "33"
    assert arwu["heidelberg-university"]["rank_display"] == "59"


def test_no_combined_or_average_rank_anywhere():
    # BR15: different providers must never be averaged into one rank.
    # No entry or provider carries a combined/average field; the word
    # appears only in the file's explanatory notes, never as data.
    def no_combined_field(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert "combined" not in k.lower() and "average" not in k.lower(), k
                no_combined_field(v)
        elif isinstance(obj, list):
            for v in obj:
                no_combined_field(v)
    no_combined_field(RANKINGS["entries"])
    no_combined_field(RANKINGS["providers"])
    no_combined_field(RANKINGS["institutions"])
    r = client.get("/api/v1/rankings")
    no_combined_field(r.json()["items"])


def test_institution_rankings_records_and_ielts_reference():
    r = client.get("/api/v1/institutions/ucl/rankings")
    assert r.status_code == 200
    body = r.json()
    assert body["institution"]["official_name"] == "University College London"
    assert len(body["rankings"]) == 3
    assert {e["provider"] for e in body["rankings"]} == {"qs", "the", "arwu"}
    # IELTS reference: compiled from the user-supplied THE table images,
    # labelled as a reference, never a verified programme requirement.
    assert body["institution"]["ielts_reference"] == "6.5 (6.0)"
    assert "user-supplied" in (body["institution"]["ielts_reference_source"] or "").lower()
    assert body["institution"]["official_website"] == "https://www.ucl.ac.uk"
    r = client.get("/api/v1/institutions/university-of-oxford/rankings")
    assert r.status_code == 200
    assert len(r.json()["rankings"]) == 3
    assert r.json()["institution"]["ielts_reference"] == "7.5 (7.0)"
    assert r.json()["institution"]["official_website"] is None
    r = client.get("/api/v1/institutions/national-taiwan-university/rankings")
    assert r.status_code == 200
    assert len(r.json()["rankings"]) == 1  # QS only; distinct from Nanyang 'ntu'
    assert r.json()["rankings"][0]["provider"] == "qs"
    assert r.json()["institution"]["ielts_reference"] is None  # no THE top-100 entry
    r = client.get("/api/v1/institutions/hogwarts/rankings")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "INSTITUTION_NOT_FOUND"


def test_rankings_data_file_rules():
    # 300 entries (top 100 x 3 providers), 148 institutions, keyed by
    # (provider, institution, edition).
    assert len(RANKINGS["entries"]) == 300
    assert len(RANKINGS["institutions"]) == 148
    keys = {(e["provider"], e["institution_id"], e["edition_label"])
            for e in RANKINGS["entries"]}
    assert len(keys) == len(RANKINGS["entries"])
    ids = {i["id"] for i in RANKINGS["institutions"]}
    assert {"ucl", "imperial", "nus", "ntu",
            "university-of-oxford", "national-taiwan-university"} <= ids
    # The two NTUs are distinct institutions and must never be conflated.
    assert "ntu" in ids and "national-taiwan-university" in ids
    # IELTS reference exists exactly for the 100 THE institutions.
    with_ielts = [i for i in RANKINGS["institutions"] if i.get("ielts_reference")]
    assert len(with_ielts) == 100
    assert all(i.get("ielts_reference_source") for i in with_ielts)
    # Every institution has at least one provider profile link; official
    # websites exist only for the four institutions whose programmes
    # PathPilot covers — never guessed for the rest.
    assert all(i.get("provider_profiles") for i in RANKINGS["institutions"])
    assert {i["id"] for i in RANKINGS["institutions"] if i.get("official_website")} == {
        "ucl", "imperial", "nus", "ntu"}
    # Exactly three providers ship, in every record.
    assert {e["provider"] for e in RANKINGS["entries"]} == {"qs", "the", "arwu"}
    assert {p["id"] for p in RANKINGS["providers"]} == {"qs", "the", "arwu"}


def test_rankings_never_leak_into_match():
    # BR16: rankings must not affect eligibility; the /match response
    # carries no ranking data at all — and no IELTS reference either.
    profile = {"track": "undergraduate", "curriculum": "uk_alevel",
               "alevels": "A*A*A", "mathsGrade": "A*",
               "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
               "ieltsWriting": 6.0, "ieltsSpeaking": 6.5,
               "budget": 50000, "budgetCurrency": "GBP"}
    r = client.post("/api/v1/match",
                    json={"profile": profile, "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200
    body = json.dumps(r.json()).lower()
    assert "ranking" not in body
    assert "ielts_reference" not in body
