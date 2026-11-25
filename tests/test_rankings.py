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


# --- Chinese display names (language fix 2026-11-25) -----------------------
# name_zh is transcribed from the user-supplied THE 2027 / ARWU 2026
# ranking-table images (THE preferred where the two compilations differ),
# plus National Taiwan University and Korea University verified on their
# own official sites. Nothing is invented: institutions with no verified
# Chinese name carry no name_zh and the UI falls back to official_name.
QS_ONLY_MISSING = {
    "adelaide-university", "durham-university",
    "freie-universitat-berlin", "institute-of-science-tokyo",
    "king-fahd-university-of-petroleum-minerals",
    "kth-royal-institute-of-technology", "lund-university",
    "osaka-university", "pennsylvania-state-university",
    "politecnico-di-milano", "trinity-college-dublin",
    "universidad-de-buenos-aires", "universiti-malaya",
    "university-of-alberta", "university-of-auckland",
    "university-of-leeds", "university-of-nottingham",
    "university-of-sheffield", "university-of-technology-sydney",
    "university-of-warwick", "university-of-western-australia",
}


def test_institution_chinese_names_present_and_missing():
    by_id = {i["id"]: i for i in RANKINGS["institutions"]}
    with_zh = [i for i in RANKINGS["institutions"] if i.get("name_zh")]
    assert len(with_zh) == 127
    assert len(RANKINGS["institutions"]) == 148
    # Spot checks from the images (THE preferred on conflicts).
    assert by_id["ucl"]["name_zh"] == "伦敦大学学院"
    assert by_id["university-of-oxford"]["name_zh"] == "牛津大学"
    assert by_id["nus"]["name_zh"] == "新加坡国立大学"
    assert by_id["ntu"]["name_zh"] == "新加坡南洋理工大学"
    assert by_id["tsinghua-university"]["name_zh"] == "清华大学"
    assert by_id["peking-university"]["name_zh"] == "北京大学"
    assert by_id["universite-psl"]["name_zh"] == "巴黎文理研究大学"  # not ARWU's 巴黎文理大学
    assert by_id["university-of-california-berkeley"]["name_zh"] == "加州大学伯克利分校"
    assert by_id["university-of-minnesota-twin-cities"]["name_zh"] == "明尼苏达大学"
    # Verified on the institutions' own official sites.
    assert by_id["national-taiwan-university"]["name_zh"] == "国立台湾大学"
    assert by_id["korea-university"]["name_zh"] == "高丽大学"
    # Exactly the 21 QS-only institutions without a verified official
    # Chinese name are missing — no invented names anywhere.
    missing = {i["id"] for i in RANKINGS["institutions"] if not i.get("name_zh")}
    assert missing == QS_ONLY_MISSING
    assert all(i.get("name_zh") for i in with_zh)
    # The endpoint exposes name_zh.
    r = client.get("/api/v1/institutions/ucl/rankings")
    assert r.json()["institution"]["name_zh"] == "伦敦大学学院"
    r = client.get("/api/v1/institutions/adelaide-university/rankings")
    assert r.json()["institution"].get("name_zh") is None


def test_rank_entries_unchanged_by_name_zh():
    # Adding name_zh must not touch any rank value or score: the 300
    # entries keep their verified values, and no entry gains a name field.
    assert len(RANKINGS["entries"]) == 300
    assert all("name_zh" not in e for e in RANKINGS["entries"])
    qs = {e["institution_id"]: e for e in all_rankings({"provider": "qs"})}
    assert qs["ucl"]["rank_display"] == "=8" and qs["ucl"]["score"] == 96.3
    assert qs["imperial"]["rank_display"] == "=2" and qs["imperial"]["score"] == 99.2
    the = {e["institution_id"]: e for e in all_rankings({"provider": "the"})}
    assert the["university-of-oxford"]["rank_display"] == "1"
    arwu = {e["institution_id"]: e for e in all_rankings({"provider": "arwu"})}
    assert arwu["ucl"]["rank_display"] == "17" and arwu["ucl"]["score"] == 49.4


def test_query_matches_chinese_name():
    # Search by Chinese name finds the institution (official name alone
    # would miss it).
    items = all_rankings({"query": "牛津"})
    assert {e["institution_id"] for e in items} == {"university-of-oxford"}
    assert len(items) == 3
    items = all_rankings({"query": "清华"})
    assert {e["institution_id"] for e in items} == {"tsinghua-university"}
    assert len(items) == 3


def test_country_locale_map_covers_all_countries():
    # Every country code in the data has a country.<code> key in all six
    # locale files, non-empty; the English value matches the data's
    # country_name exactly.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    codes = {i["country"] for i in RANKINGS["institutions"]}
    assert len(codes) == 26
    data_names = {}
    for i in RANKINGS["institutions"]:
        data_names.setdefault(i["country"], i["country_name"])
    for locale in ("en", "zh-CN", "es", "fr", "pt-BR", "ar"):
        msgs = json.loads((root / "frontend" / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        for code in codes:
            v = msgs.get(f"country.{code}")
            assert isinstance(v, str) and v.strip(), f"{locale} missing country.{code}"
        assert msgs["country.GB"] != "GB"  # a real name, not the code
    en = json.loads((root / "frontend" / "messages" / "en.json").read_text(encoding="utf-8"))
    for code, name in data_names.items():
        assert en[f"country.{code}"] == name, code


# --- Rankings page: vertical list with crests (2026-11-25) ------------------
# The /rankings page is a single-column vertical list (one <ol>, rows
# top-to-bottom by rank) with a crest per row. The crest manifest is
# frontend/src/lib/crests.ts; real crests are freely-usable Commons files
# (Public domain / CC BY / CC BY-SA) stored locally under
# frontend/public/crests/, everything else an explicit monogram fallback.
# No rank value, score or sort order is changed by this (existing tests
# above pin all 300 entries).
import re
from pathlib import Path

CRESTS_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "crests.ts"
CRESTS_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "crests"
RANKINGS_PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "app" / "rankings" / "page.tsx"

REAL_CREST_IDS = {
    "harvard-university", "massachusetts-institute-of-technology",
    "university-of-oxford", "imperial", "stanford-university",
    "princeton-university", "university-of-cambridge",
    "university-of-california-berkeley", "columbia-university",
    "eth-zurich", "yale-university", "tsinghua-university",
    "cornell-university", "peking-university",
    "chinese-university-of-hong-kong", "universite-paris-saclay",
    "university-of-california-los-angeles", "university-of-pennsylvania",
    "university-of-california-san-diego",
}

MONOGRAM_TOP_IDS = {
    # Top-20 by best rank (plus the four covered institutions) with no
    # freely-usable Commons crest found on 2026-11-25: trademarked logos
    # absent from Commons or held on Wikipedia under a non-free rationale.
    "california-institute-of-technology", "ucl", "university-of-chicago",
    "nus", "university-of-hong-kong", "ntu",
}


def _parse_crest_manifest():
    text = CRESTS_TS.read_text(encoding="utf-8")
    block = text.split("export const CRESTS", 1)[1].split("};", 1)[0]
    real, mono = {}, set()
    for m in re.finditer(
            r"'([^']+)':\s*\{\s*src:\s*'([^']+)',\s*source_url:\s*'([^']+)',\s*licence:\s*'([^']+)'\s*\}",
            block):
        real[m.group(1)] = {"src": m.group(2), "source_url": m.group(3), "licence": m.group(4)}
    for m in re.finditer(r"'([^']+)':\s*\{\s*monogram:\s*true\s*\}", block):
        mono.add(m.group(1))
    return real, mono


def test_crest_manifest_covers_every_institution():
    real, mono = _parse_crest_manifest()
    ids = {i["id"] for i in RANKINGS["institutions"]}
    assert len(ids) == 148
    assert set(real) | mono == ids  # every institution resolves to one or the other
    assert not (set(real) & mono)
    assert set(real) == REAL_CREST_IDS
    assert MONOGRAM_TOP_IDS <= mono
    assert "imperial" in real  # covered institution with a real crest


def test_crest_manifest_real_crests_have_source_and_licence():
    real, _ = _parse_crest_manifest()
    assert len(real) == 19
    for inst_id, entry in real.items():
        assert entry["src"].startswith("/crests/"), inst_id
        assert entry["source_url"].startswith(
            "https://commons.wikimedia.org/wiki/File:"), inst_id
        assert entry["licence"] in {"Public domain", "CC BY 3.0", "CC BY-SA 3.0"}, inst_id
        # No tokenised / expiring link anywhere in the manifest.
        for value in entry.values():
            assert "?" not in value and "utm_" not in value, (inst_id, value)
            assert "token" not in value.lower() and "expires" not in value.lower(), (inst_id, value)


def test_crest_local_files_exist_and_are_valid_images():
    real, _ = _parse_crest_manifest()
    for inst_id, entry in real.items():
        local = CRESTS_DIR / entry["src"].removeprefix("/crests/")
        assert local.is_file(), (inst_id, local)
        data = local.read_bytes()
        assert len(data) > 500, inst_id  # not an empty / error page
        if local.suffix == ".svg":
            assert data.lstrip().startswith((b"<svg", b"<?xml")), inst_id
        elif local.suffix == ".png":
            assert data.startswith(b"\x89PNG"), inst_id
        else:  # pragma: no cover - no other formats are used
            raise AssertionError(f"unexpected crest format for {inst_id}: {local.suffix}")


def test_rankings_page_is_vertical_list_with_crests():
    text = RANKINGS_PAGE.read_text(encoding="utf-8")
    # Single-column vertical list, not the old 2-column card grid. The one
    # remaining sm:grid-cols-2 is the provider-cards section above it.
    assert "<ol" in text and "flex flex-col" in text
    assert text.count("sm:grid-cols-2") == 1
    assert "grid gap-3 sm:grid-cols-2" not in text.split("<ol")[1]
    # Crests come from the manifest; monogram fallback uses the theme colours.
    assert "from '../../lib/crests'" in text
    assert "crestFor(inst.id)" in text and "monogramFor(inst.official_name)" in text
    assert "#0B1F3A" in text
    # Sort order is untouched: selected provider's rank, else best rank.
    assert "Math.min(...visibleEntries.filter((e) => e.institution_id === a.id).map(rankValue))" in text
    # Localised names / countries and the filters / compare still render.
    assert "displayInstitutionName(inst, locale)" in text
    assert "displayCountryName(inst, t)" in text
    assert "toggleSelect" in text and "compareInstitutions" in text
