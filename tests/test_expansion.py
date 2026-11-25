"""Tests for the Day-3 programme expansion (v3 catalogue).

Covers: the expansion loader/validator (empty file loads; banned strings,
v2 id collisions, matchable=true, unknown institutions/sources are
refused), the new institution endpoints, and the extended /programs
filters. The default /programs response must stay byte-identical to the
Day-2 contract (v2 only) — see tests/test_day2.py.

Run from the project root:
    .venv/bin/python -m pytest tests/test_expansion.py -q
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.data import (EXPANSION, EXPANSION_INSTITUTIONS, EXPANSION_PROGRAMS,
                      PROGRAMS, RANKINGS, load_expansion,
                      validate_expansion_data)
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

RANKING_IDS = {i["id"] for i in RANKINGS.get("institutions", [])}
V2_IDS = set(PROGRAMS.keys())


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

def test_empty_expansion_loads():
    assert EXPANSION.get("data_version") == "v3"
    assert EXPANSION_PROGRAMS == {}
    assert EXPANSION_INSTITUTIONS == {}
    assert load_expansion()["data_version"] == "v3"


def test_validator_accepts_good_program():
    assert validate_expansion_data(_good_data([_good_program()]), RANKING_IDS, V2_IDS) == []


def test_validator_rejects_v2_collision():
    prog = _good_program(pid="ucl-cs-bsc-2026", iid="ucl")
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("collides with a v2 program" in e for e in errors)


def test_validator_rejects_matchable_true():
    prog = _good_program()
    prog["matchable"] = True
    errors = validate_expansion_data(_good_data([prog]), RANKING_IDS, V2_IDS)
    assert any("matchable must be false" in e for e in errors)


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


def test_institution_detail_ucl_v2_only_for_now():
    body = client.get("/api/v1/institutions/ucl").json()
    assert body["institution"]["id"] == "ucl"
    assert body["stats"] is None  # no stats profile collected yet
    assert {e["provider"] for e in body["rankings"]} == {"qs", "the", "arwu"}
    assert [p["id"] for p in body["programs"]] == [
        "ucl-cs-bsc-2026", "ucl-cs-msc-2027"]
    assert all(p["catalogue"] == "v2" and p["matchable"] is True
               for p in body["programs"])


def test_institution_detail_unknown_404():
    resp = client.get("/api/v1/institutions/university-of-nowhere")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INSTITUTION_NOT_FOUND"


def test_institution_detail_never_invents_stats():
    # Every institution without a collected profile returns stats null.
    body = client.get("/api/v1/institutions/massachusetts-institute-of-technology").json()
    assert body["stats"] is None
    assert body["programs"] == []


# --- /programs extension -----------------------------------------------------

def test_programs_default_still_v2_only():
    body = client.get("/api/v1/programs").json()
    assert [p["id"] for p in body["items"]] == [
        "ucl-cs-bsc-2026", "nus-mcomp-cs", "imperial-comp-beng-2027",
        "imperial-msc-computing-2027", "ucl-cs-msc-2027", "nus-bcomp-cs-2027",
        "ntu-bcomp-cs-2027", "ntu-msai-2027"]
    assert "catalogue" not in body["items"][0]  # byte-identical contract


def test_programs_catalogue_expansion_empty_for_now():
    body = client.get("/api/v1/programs", params={"catalogue": "expansion"}).json()
    assert body["items"] == []


def test_programs_catalogue_all_flags_items():
    body = client.get("/api/v1/programs", params={"catalogue": "all"}).json()
    assert len(body["items"]) == 8
    assert all(p["catalogue"] == "v2" and p["matchable"] is True
               for p in body["items"])


def test_programs_catalogue_bad_value_400():
    resp = client.get("/api/v1/programs", params={"catalogue": "bogus"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_programs_filter_institution_and_field():
    ucl = client.get("/api/v1/programs",
                     params={"institution": "ucl"}).json()
    assert [p["id"] for p in ucl["items"]] == [
        "ucl-cs-bsc-2026", "ucl-cs-msc-2027"]
    cs = client.get("/api/v1/programs", params={
        "field": "computer-science", "catalogue": "all"}).json()
    assert len(cs["items"]) == 8
    none = client.get("/api/v1/programs", params={
        "field": "data-science", "catalogue": "all"}).json()
    assert none["items"] == []


def test_no_banned_provider_in_expansion_responses():
    blob = json.dumps([
        client.get("/api/v1/institutions").json(),
        client.get("/api/v1/institutions/ucl").json(),
        client.get("/api/v1/programs", params={"catalogue": "all"}).json(),
    ], ensure_ascii=False).lower()
    assert "u.s. news" not in blob and "us news" not in blob
