"""Tests for the Day-3 programme expansion (v3 catalogue).

Covers: the expansion loader/validator (empty file loads; banned strings,
v2 id collisions, matchable=true without an evaluable rule, unknown
institutions/sources are refused), the new institution endpoints, and the
extended /programs filters. The default /programs response must stay
byte-identical to the Day-2 contract (v2 only) — see tests/test_day2.py.

Run from the project root:
    .venv/bin/python -m pytest tests/test_expansion.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.data import (EXPANSION, EXPANSION_INSTITUTIONS, EXPANSION_PROGRAMS,
                      PROGRAMS, RANKINGS, load_expansion,
                      validate_expansion_data)
from app.main import app, reset_rate_limits
from domain.expansion_eval import evaluable_rules

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # The TestClient shares one IP, so the 60/min general bucket is shared
    # across the whole suite; cursor paging over a 200+ programme catalogue
    # would otherwise 429 late tests in this file.
    reset_rate_limits()

RANKING_IDS = {i["id"] for i in RANKINGS.get("institutions", [])}
V2_IDS = set(PROGRAMS.keys())


def _page_all(path: str, params: dict | None = None) -> list:
    """Walk a cursor-paginated list endpoint to the end."""
    items, cursor = [], None
    # 832 expansion programmes at 20/page need 42 pages; keep headroom for
    # later fields (loop exits early when next_cursor is None).
    for _ in range(100):
        query = dict(params or {})
        if cursor:
            query["cursor"] = cursor
        body = client.get(path, params=query).json()
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    return items


def _good_program(pid="mit-cs-sb-2027", iid="massachusetts-institute-of-technology"):
    return {
        "id": pid, "institution_id": iid,
        "institution": "Massachusetts Institute of Technology",
        "country": "US", "degree_level": "undergraduate",
        "official_name": "Computer Science and Engineering",
        "name_localized": {"zh-CN": "计算机科学与工程理学学士"},
        "field": "computer-science", "field_zh": "计算机科学",
        "subject": "computer-science",
        "fees": {"currency": "USD", "period": "per_year", "amount": None,
                 "notes": "Fee not stated on the cited page — unknown."},
        "application_status": "unknown",
        "application_status_as_of": None, "application_status_source": None,
        "requirements": [],
        "sources": [{"id": "mit-adm", "url": "https://mitadmissions.org/",
                     "retrieved_at": "2026-11-25T00:00:00Z"}],
        "matchable": False, "catalogue": "expansion", "synthetic": False,
    }


def _good_data(programs=None, institutions=None):
    return {"data_version": "v3", "institutions": institutions or [],
            "programs": programs or [],
            "sources": [{"id": "mit-adm", "url": "https://mitadmissions.org/",
                         "retrieved_at": "2026-11-25T00:00:00Z"}],
            "traceability": []}


# --- Loader / validator ------------------------------------------------------

def test_merged_expansion_loads():
    # The merged file (band B, official-only subset) loads and validates.
    assert EXPANSION.get("data_version") == "v3"
    assert load_expansion()["data_version"] == "v3"
    assert validate_expansion_data(EXPANSION, RANKING_IDS, V2_IDS) == []
    assert len(EXPANSION_PROGRAMS) == len(EXPANSION.get("programs", []))
    assert len(EXPANSION_INSTITUTIONS) == len(EXPANSION.get("institutions", []))
    # Round 6 promotion rule: matchable=true exactly for UG/TM programmes
    # with at least one evaluable rule (fee / language / academic).
    promoted = [p for p in EXPANSION_PROGRAMS.values()
                if p["matchable"] is True]
    assert len(promoted) == 593
    assert len(EXPANSION_PROGRAMS) - len(promoted) == 293
    for p in EXPANSION_PROGRAMS.values():
        expect = (p["degree_level"] in ("undergraduate", "taught_masters")
                  and any(evaluable_rules(p).values()))
        assert p["matchable"] is expect, p["id"]


def test_validator_accepts_good_program():
    assert validate_expansion_data(_good_data([_good_program()]), RANKING_IDS, V2_IDS) == []


def test_validator_language_of_instruction():
    # Round 9 (R5): the field is optional, but when present it must name
    # the language, carry an https source URL, and that URL must be one
    # of the programme's own listed sources (traceability).
    good = _good_program()
    good["language_of_instruction"] = {
        "language": "German",
        "note": "Main teaching language is German.",
        "source_url": "https://mitadmissions.org/",
    }
    assert validate_expansion_data(_good_data([good]), RANKING_IDS, V2_IDS) == []

    no_language = _good_program()
    no_language["language_of_instruction"] = {"source_url": "https://mitadmissions.org/"}
    assert validate_expansion_data(_good_data([no_language]), RANKING_IDS, V2_IDS) != []

    http_url = _good_program()
    http_url["language_of_instruction"] = {
        "language": "German", "source_url": "http://mitadmissions.org/"}
    assert validate_expansion_data(_good_data([http_url]), RANKING_IDS, V2_IDS) != []

    unlisted = _good_program()
    unlisted["language_of_instruction"] = {
        "language": "German", "source_url": "https://example.com/other-page"}
    assert validate_expansion_data(_good_data([unlisted]), RANKING_IDS, V2_IDS) != []


def test_validator_rejects_v2_collision():
    prog = _good_program(pid="ucl-cs-bsc-2026", iid="ucl")
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("collides with a v2 program" in e for e in errors)


def test_validator_rejects_matchable_true_without_evaluable_rule():
    # The fixture has no fee amount and no structured threshold, so
    # matchable=true has no evaluable rule and is refused.
    prog = _good_program()
    prog["matchable"] = True
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("at least one evaluable rule" in e for e in errors)


def test_validator_accepts_matchable_true_with_fee_amount():
    prog = _good_program()
    prog["fees"]["amount"] = 66720
    prog["matchable"] = True
    assert validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS) == []


def test_validator_rejects_matchable_true_for_foundation():
    # A foundation programme with an evaluable fee rule still stays
    # display-only: the wizard has no foundation track.
    prog = _good_program()
    prog["degree_level"] = "foundation"
    prog["fees"]["amount"] = 29500
    prog["matchable"] = True
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("undergraduate/taught_masters" in e for e in errors)


def test_validator_rejects_matchable_non_bool():
    prog = _good_program()
    prog["matchable"] = "yes"
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("matchable must be a boolean" in e for e in errors)


def test_validator_rejects_synthetic():
    prog = _good_program()
    prog["synthetic"] = True
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("synthetic=true" in e for e in errors)


def test_validator_rejects_unknown_institution():
    prog = _good_program(iid="university-of-nowhere")
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("not in v2 rankings" in e for e in errors)


def test_validator_rejects_unknown_source():
    prog = _good_program()
    prog["sources"] = [{"id": "nope", "url": "https://example.org/",
                        "retrieved_at": "2026-11-25T00:00:00Z"}]
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("unknown source" in e for e in errors)


def test_validator_rejects_banned_provider_string():
    data = _good_data([_good_program()])
    data["programs"][0]["fees"]["notes"] = "Ranked by U.S. News."
    errors = validate_expansion_data(data, RANKING_IDS, V2_IDS)
    assert any("U.S. News" in e for e in errors)


def test_validator_rejects_missing_zh_name():
    prog = _good_program()
    prog["name_localized"] = {}
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("zh-CN" in e for e in errors)


def test_validator_rejects_bad_field():
    prog = _good_program()
    prog["field"] = "astrophysics"
    prog["subject"] = "astrophysics"
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("controlled list" in e for e in errors)


# --- Institution endpoints ---------------------------------------------------

def test_institutions_list_paginates_all_148():
    seen, cursor = [], None
    for _ in range(20):
        body = client.get("/api/v1/institutions",
                          params={"cursor": cursor} if cursor else {}).json()
        assert body["data_version"] == "v2"
        assert body["expansion_version"] == "v3"
        seen.extend(i["id"] for i in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 148
    assert len(set(seen)) == 148


def test_institutions_list_filters():
    gb = client.get("/api/v1/institutions", params={"country": "GB"}).json()
    assert gb["items"] and all(i["country"] == "GB" for i in gb["items"])
    assert any(i["id"] == "ucl" for i in gb["items"])
    found = client.get("/api/v1/institutions", params={"query": "牛津"}).json()
    assert [i["id"] for i in found["items"]] == ["university-of-oxford"]
    for item in gb["items"]:
        assert "has_stats_profile" in item and "programmes_count" in item


def test_institution_detail_ucl_v2_first_then_expansion():
    body = client.get("/api/v1/institutions/ucl").json()
    assert body["institution"]["id"] == "ucl"
    assert {e["provider"] for e in body["rankings"]} == {"qs", "the", "arwu"}
    v2_progs = [p for p in body["programs"] if p["catalogue"] == "v2"]
    exp_progs = [p for p in body["programs"] if p["catalogue"] == "expansion"]
    assert [p["id"] for p in v2_progs] == [
        "ucl-cs-bsc-2026", "ucl-cs-msc-2027"]
    assert all(p["matchable"] is True for p in v2_progs)
    # Expansion flags are the stored flags (round 6: promoted ones true).
    assert [p["matchable"] for p in exp_progs] == [
        EXPANSION_PROGRAMS[p["id"]]["matchable"] for p in exp_progs]
    assert [p["id"] for p in exp_progs] == [
        p["id"] for p in EXPANSION_PROGRAMS.values()
        if p.get("institution_id") == "ucl"]


def test_institution_detail_unknown_404():
    resp = client.get("/api/v1/institutions/university-of-nowhere")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INSTITUTION_NOT_FOUND"


def test_institution_detail_never_invents_stats():
    # Every institution without a collected profile returns stats null.
    # (Computed from the live merged data so later bands don't break it.)
    unprofiled = [i["id"] for i in RANKINGS.get("institutions", [])
                  if i["id"] not in EXPANSION_INSTITUTIONS]
    assert unprofiled, "all 148 institutions unexpectedly have profiles"
    body = client.get(f"/api/v1/institutions/{unprofiled[0]}").json()
    assert body["stats"] is None
    # And a profiled institution returns the profile, never a bare number.
    profiled = next(iter(EXPANSION_INSTITUTIONS))
    body = client.get(f"/api/v1/institutions/{profiled}").json()
    assert body["stats"]["institution_id"] == profiled
    assert isinstance(body["stats"]["stats"], dict)


# --- /programs extension -----------------------------------------------------

def test_programs_default_still_v2_only():
    body = client.get("/api/v1/programs").json()
    assert [p["id"] for p in body["items"]] == [
        "ucl-cs-bsc-2026", "nus-mcomp-cs", "imperial-comp-beng-2027",
        "imperial-msc-computing-2027", "ucl-cs-msc-2027", "nus-bcomp-cs-2027",
        "ntu-bcomp-cs-2027", "ntu-msai-2027"]
    assert "catalogue" not in body["items"][0]  # byte-identical contract


def test_programs_catalogue_expansion_lists_merged():
    items = _page_all("/api/v1/programs", {"catalogue": "expansion"})
    assert [p["id"] for p in items] == [
        p["id"] for p in EXPANSION.get("programs", [])]
    assert all(p["catalogue"] == "expansion" for p in items)
    # Flags are the stored flags: 593 promoted, 293 display-only.
    assert sum(1 for p in items if p["matchable"] is True) == 593
    assert sum(1 for p in items if p["matchable"] is False) == 293
    assert all(p["matchable"] is EXPANSION_PROGRAMS[p["id"]]["matchable"]
               for p in items)


def test_programs_catalogue_all_flags_items():
    items = _page_all("/api/v1/programs", {"catalogue": "all"})
    assert len(items) == 8 + len(EXPANSION_PROGRAMS)
    v2_items = [p for p in items if p["catalogue"] == "v2"]
    exp_items = [p for p in items if p["catalogue"] == "expansion"]
    assert len(v2_items) == 8
    assert len(exp_items) == len(EXPANSION_PROGRAMS)
    assert all(p["matchable"] is True for p in v2_items)
    assert all(p["matchable"] is EXPANSION_PROGRAMS[p["id"]]["matchable"]
               for p in exp_items)
    assert sum(1 for p in exp_items if p["matchable"] is True) == 593


def test_programs_catalogue_bad_value_400():
    resp = client.get("/api/v1/programs", params={"catalogue": "bogus"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_programs_filter_institution_and_field():
    ucl = client.get("/api/v1/programs",
                     params={"institution": "ucl"}).json()
    assert [p["id"] for p in ucl["items"]] == [
        "ucl-cs-bsc-2026", "ucl-cs-msc-2027"]
    cs = _page_all("/api/v1/programs", {
        "field": "computer-science", "catalogue": "all"})
    # 8 v2 programmes + every merged expansion programme in the field.
    expected_cs = 8 + sum(
        1 for p in EXPANSION_PROGRAMS.values() if p.get("field") == "computer-science")
    assert len(cs) == expected_cs
    assert all(p.get("field", p.get("subject", "")).replace(" ", "-")
               == "computer-science" for p in cs)
    ds = _page_all("/api/v1/programs", {
        "field": "data-science", "catalogue": "all"})
    assert [p["id"] for p in ds] == [
        p["id"] for p in EXPANSION_PROGRAMS.values()
        if p.get("field") == "data-science"]


def test_no_banned_provider_in_expansion_responses():
    blob = json.dumps([
        client.get("/api/v1/institutions").json(),
        client.get("/api/v1/institutions/ucl").json(),
        client.get("/api/v1/programs", params={"catalogue": "all"}).json(),
    ], ensure_ascii=False).lower()
    assert "u.s. news" not in blob and "us news" not in blob
