"""小罗盘 desktop-pet assistant (Day 3) — policy tests.

Pinned rules (see backend/ai/assistant.py):
- unknown stays unknown (no invented requirement, fee or rank);
- no admission probabilities, no guarantees;
- no personal data collected, echoed or stored;
- answers are at most 3 lines, conclusion first;
- the 3-question flow stops asking after the third answer;
- the compiled IELTS reference is never used as a programme fact.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ai.assistant import (ask, check_no_forbidden, contains_personal_data,
                          fee_fit, program_fee_range, suggest)
from app.data import PROGRAMS, RANKINGS
from app.main import app, reset_rate_limits

client = TestClient(app)


def setup_function():
    reset_rate_limits()


# ---------------------------------------------------------------------------
# Suggestion flow: all 4 track/country combos x 3 budget bands
# ---------------------------------------------------------------------------
def _all_suggestions(locale="en"):
    out = []
    for level in ("undergraduate", "taught_masters"):
        for country in ("GB", "SG"):
            for band in ("low", "mid", "high"):
                out.append((level, country, band,
                            suggest(level, country, band, locale)))
    return out


def test_suggest_all_combos_have_programme_and_evidence():
    for level, country, band, r in _all_suggestions():
        assert r["program_id"] in PROGRAMS, (level, country, band)
        assert r["ai_status"] == "unavailable"
        # ONE evidence link, and it is the programme's own official page.
        program = PROGRAMS[r["program_id"]]
        assert r["evidence_url"] == program["sources"][0]["url"]
        assert r["next_steps"]["wizard"] == "/wizard"
        assert r["next_steps"]["program"] == f"/programs/{r['program_id']}"
        assert len(r["lines"]) <= 3


def test_suggest_fee_fit_is_honest():
    # GB UG: overseas fees 48,600 / 47,800 -> mid band (30-50k) fits,
    # low band (<30k) does not; cheapest within mid is Imperial (47,800).
    assert suggest("undergraduate", "GB", "mid")["program_id"] == "imperial-comp-beng-2027"
    assert suggest("undergraduate", "GB", "mid")["fee_fit"] == "within"
    assert suggest("undergraduate", "GB", "low")["fee_fit"] == "above"
    assert suggest("undergraduate", "GB", "low")["program_id"] == "imperial-comp-beng-2027"
    # GB TM: cheapest is UCL MSc 44,400.
    assert suggest("taught_masters", "GB", "mid")["program_id"] == "ucl-cs-msc-2027"
    assert suggest("taught_masters", "GB", "low")["fee_fit"] == "above"
    # SG TM: totals 65,748.80 (NTU) / 69,215 (NUS) -> mid band (50-80k)
    # fits, low band (<50k total) does not; cheapest is NTU MSAI.
    assert suggest("taught_masters", "SG", "mid")["program_id"] == "ntu-msai-2027"
    assert suggest("taught_masters", "SG", "mid")["fee_fit"] == "within"
    assert suggest("taught_masters", "SG", "low")["fee_fit"] == "above"
    # SG UG: NTU range 36,350-40,600 is cheapest by its lower bound.
    assert suggest("undergraduate", "SG", "mid")["program_id"] == "ntu-bcomp-cs-2027"
    assert suggest("undergraduate", "SG", "low")["fee_fit"] == "above"


def test_suggest_fee_range_keeps_ntu_range():
    # NTU BComp lab vs non-lab is unverified, so both verified figures
    # are kept as a range — never collapsed to a single invented figure.
    fr = program_fee_range(PROGRAMS["ntu-bcomp-cs-2027"])
    assert fr[0] == 36_350 and fr[1] == 40_600 and fr[2] == "SGD"
    assert fee_fit(fr, "undergraduate", "SG", "mid") == "within"
    assert fee_fit(fr, "undergraduate", "SG", "low") == "above"


def test_suggest_stops_asking_after_three_answers():
    # The suggestion is the end of the flow: no line asks another
    # question (no trailing ? / ？ anywhere).
    for _level, _country, _band, r in _all_suggestions():
        for line in r["lines"]:
            assert not line.rstrip().endswith(("?", "？")), line


def test_suggest_endpoint_validates_enums():
    for body, field in (
            ({"degree_level": "phd", "country": "GB", "budget_band": "mid"}, "degree_level"),
            ({"degree_level": "undergraduate", "country": "GB", "budget_band": "huge"}, "budget_band")):
        r = client.post("/api/v1/assistant/suggest", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post("/api/v1/assistant/suggest",
                    json={"degree_level": "undergraduate", "country": "GB",
                          "budget_band": "mid", "locale": "zh-CN"})
    assert r.status_code == 200
    assert "本科" in r.json()["lines"][0]
    assert r.json()["ai_status"] == "unavailable"


# ---------------------------------------------------------------------------
# Free-text questions: verified facts only
# ---------------------------------------------------------------------------
def test_ask_fee_from_verified_data():
    r = ask("UCL本科的学费是多少", "zh-CN")
    assert r["program_id"] == "ucl-cs-bsc-2026"
    assert "48,600" in r["lines"][0]
    assert r["evidence_url"].startswith("https://www.ucl.ac.uk/")
    r = ask("What is the Imperial MSc Computing tuition fee?", "en")
    assert r["program_id"] == "imperial-msc-computing-2027"
    assert "48,300" in r["lines"][0]


def test_ask_ielts_from_programme_threshold():
    r = ask("帝国理工硕士雅思要求", "zh-CN")
    assert r["program_id"] == "imperial-msc-computing-2027"
    assert "7.0" in r["lines"][0] and "6.5" in r["lines"][0]
    r = ask("NUS本科雅思", "zh-CN")
    assert r["program_id"] == "nus-bcomp-cs-2027"
    assert "6.5" in r["lines"][0]


def test_ask_ielts_unknown_stays_unknown():
    # UCL MSc: the course page states no English level — the pet must
    # say so, not borrow the UCL BSc level or the compiled reference.
    r = ask("UCL硕士雅思要求", "zh-CN")
    assert r["program_id"] == "ucl-cs-msc-2027"
    assert "没有说明" in r["lines"][0]
    assert "6.5" not in r["lines"][0]


def test_ask_deadline_verified_and_unknown():
    r = ask("UCL本科申请截止", "zh-CN")
    assert "13 January 2027" in r["lines"][0]
    r = ask("NUS硕士申请截止", "zh-CN")
    assert r["program_id"] == "nus-mcomp-cs"
    assert "查不到" in r["lines"][0]
    # No date is invented for NUS MComp.
    assert "2027" not in r["lines"][0]


def test_ask_rank_from_verified_entries():
    # NUS: QS 10, THE 15, ARWU 53 (verified 2026-11-25).
    r = ask("新加坡国立大学排名", "zh-CN")
    assert r["institution_id"] == "nus"
    assert "QS 2027 第 10 名" in r["lines"][0]
    assert "THE 2027 第 15 名" in r["lines"][0]
    assert "ARWU 2026 第 53 名" in r["lines"][0]
    r = ask("What is Oxford's rank?", "en")
    assert r["institution_id"] == "university-of-oxford"
    assert "QS 2027 #4" in r["lines"][0] or "QS 2027" in r["lines"][0]
    r = ask("What is the National University of Singapore rank?", "en")
    assert r["institution_id"] == "nus"
    assert "QS 2027 #10" in r["lines"][0]
    r = ask("What is the National Taiwan University rank?", "en")
    assert r["institution_id"] == "national-taiwan-university"
    assert "QS 2027 #54" in r["lines"][0]


def test_ask_rank_not_in_top_100_is_honest():
    # An institution with no entry in a provider is "not in the top 100"
    # for that provider — derived from the data, not invented.
    r = ask("新加坡国立大学排名", "en")
    assert "QS 2027 #10" in r["lines"][0]


def test_ask_ambiguous_programme_asks_which():
    r = ask("UCL雅思要求", "zh-CN")
    assert r["program_id"] is None
    # Round 23 (W5): the count word is the rendered count (2).
    assert "2 个相关专业" in r["lines"][0]


def test_ask_no_programme_no_invented_fact():
    # Round 6: Oxford now has one verified promoted programme
    # (oxford-msc-adv-cs-2027, GBP 46,350/yr), so a fee question is
    # answered from it — never by borrowing another programme's fee.
    r = ask("牛津大学计算机硕士学费", "zh-CN")
    assert "46,350" in r["lines"][0]
    assert "48,600" not in r["lines"][0] and "48,300" not in r["lines"][0]
    assert r["program_id"] == "oxford-msc-adv-cs-2027"
    assert r["evidence_url"].startswith("https://www.ox.ac.uk")


def test_ask_unknown_question_stays_unknown():
    r = ask("我应该申几所学校", "zh-CN")
    assert "不知道" in r["lines"][0]
    assert len(r["lines"]) <= 3


def test_ask_greeting():
    r = ask("你好", "zh-CN")
    assert "小罗盘" in r["lines"][0]
    assert len(r["lines"]) == 1


# ---------------------------------------------------------------------------
# Personal data: refused, never echoed, never stored
# ---------------------------------------------------------------------------
def test_personal_data_guard():
    assert contains_personal_data("我的邮箱是 test@example.com，请联系我")
    assert contains_personal_data("电话 +65 8123 4567")
    assert contains_personal_data("call me at 138 1234 5678")
    # Ordinary facts must NOT trip the guard: years, fees, dates.
    assert not contains_personal_data("2027年入学")
    assert not contains_personal_data("UCL学费48,600是多少")
    assert not contains_personal_data("2026-11-25 截止吗")


def test_ask_personal_data_never_echoed():
    r = ask("我的邮箱是 zhangsan@example.com，电话 13812345678", "zh-CN")
    joined = "\n".join(r["lines"])
    assert "zhangsan@example.com" not in joined
    assert "13812345678" not in joined
    assert "不收集" in r["lines"][0]
    r = ask("my phone is +65 8123 4567, call me", "en")
    joined = "\n".join(r["lines"])
    assert "8123" not in joined and "4567" not in joined
    assert "don't collect" in r["lines"][0].lower()


def test_ask_endpoint_rejects_empty_and_oversize():
    assert client.post("/api/v1/assistant/ask", json={"message": ""}).status_code == 422
    assert client.post("/api/v1/assistant/ask",
                       json={"message": "x" * 501}).status_code == 422
    r = client.post("/api/v1/assistant/ask",
                    json={"message": "帝国理工硕士雅思要求", "locale": "zh-CN"})
    assert r.status_code == 200
    assert r.json()["program_id"] == "imperial-msc-computing-2027"


# ---------------------------------------------------------------------------
# Global policy: no probabilities/guarantees, max 3 lines, all locales
# ---------------------------------------------------------------------------
def _every_answer(locale):
    for _l, _c, _b, r in _all_suggestions(locale):
        yield r["lines"]
    for q in ("UCL本科的学费是多少", "帝国理工硕士雅思要求", "UCL硕士雅思要求",
              "UCL本科申请截止", "NUS硕士申请截止", "新加坡国立大学排名",
              "牛津大学计算机硕士学费", "我应该申几所学校", "你好",
              "我的邮箱是 a@b.com", "UCL雅思要求", "清华大学排名"):
        yield ask(q, locale)["lines"]


def test_no_forbidden_words_anywhere():
    for locale in ("en", "zh-CN", "es", "fr", "pt-BR", "ar"):
        for lines in _every_answer(locale):
            assert check_no_forbidden(lines) == [], (locale, lines)
            # "%" is allowed only inside the verified tax fact "9% GST".
            for line in lines:
                if "%" in line:
                    assert "GST" in line, (locale, line)
            assert len(lines) <= 3, lines
            assert len(lines) >= 1


def test_all_locales_cover_templates():
    # Every locale renders the suggestion without falling back to English
    # (a fallback would mean a missing template key).
    from ai.assistant import _T
    keys = set(_T["en"])
    for locale in ("zh-CN", "es", "fr", "pt-BR", "ar"):
        assert set(_T[locale]) == keys, locale
    for locale in ("es", "fr", "pt-BR", "ar"):
        r = suggest("undergraduate", "GB", "mid", locale)
        assert "Undergraduate" not in r["lines"][0], (locale, r["lines"])


def test_rankings_never_leak_into_suggest():
    # BR16: rankings never affect eligibility — and the pet's suggestion
    # is a programme route, never a rank claim.
    for _l, _c, _b, r in _all_suggestions():
        assert "QS" not in "\n".join(r["lines"])
        assert "THE" not in "\n".join(r["lines"])
        assert "ARWU" not in "\n".join(r["lines"])


def test_ielts_reference_never_used_as_programme_fact():
    # Oxford's compiled IELTS reference is 7.5 (7.0), but Oxford has no
    # verified programme: asking about it must not surface the reference.
    assert RANKINGS["institutions"] is not None
    oxford = next(i for i in RANKINGS["institutions"]
                  if i["id"] == "university-of-oxford")
    assert oxford.get("ielts_reference") == "7.5 (7.0)"
    r = ask("牛津大学雅思要求", "zh-CN")
    assert "7.5" not in "\n".join(r["lines"])


def test_assistant_endpoints_honour_locale_param():
    # The frontend sends the current locale on every /ask and /suggest
    # call and re-fetches on locale change, so the backend must answer
    # in the requested locale (a stale-locale answer would resurface in
    # the panel). Unknown locales fall back to English, never crash.
    r = client.post("/api/v1/assistant/suggest",
                    json={"degree_level": "undergraduate", "country": "GB",
                          "budget_band": "mid", "locale": "fr"})
    assert r.status_code == 200
    assert "Licence" in r.json()["lines"][0]
    r = client.post("/api/v1/assistant/ask",
                    json={"message": "UCL本科的学费是多少", "locale": "es"})
    assert r.status_code == 200
    assert "Matrícula" in r.json()["lines"][0]
    r = client.post("/api/v1/assistant/ask",
                    json={"message": "UCL本科的学费是多少", "locale": "xx"})
    assert r.status_code == 200
    assert "tuition" in r.json()["lines"][0].lower()


def test_suggest_degrades_gracefully_for_country_without_programmes():
    # Global scope: a country with no verified programme yet gets an
    # honest unknown answer — never a 422, never a crash, never an
    # invented programme, fee or route. GB/SG budget-band logic is
    # untouched (see test_suggest_fee_fit_is_honest).
    # Round 9: US/CN/JP now HAVE verified expansion programmes, so
    # they no longer degrade — the no-programme case is a country
    # with nothing in the catalogue at all (AQ).
    for level, country, band, locale, needle in (
            ("undergraduate", "AQ", "mid", "en", "no verified programme"),
            ("taught_masters", "AQ", "low", "zh-CN", "没有"),
            ("undergraduate", "AQ", "high", "es", "no hay programas verificados")):
        r = suggest(level, country, band, locale)
        assert r["program_id"] is None, (level, country, band)
        assert r["evidence_url"] is None
        assert r["next_steps"]["program"] is None
        assert len(r["lines"]) <= 3
        assert needle in r["lines"][0], r["lines"]
        # No programme, fee or rank is invented for the country.
        assert "48,600" not in "\n".join(r["lines"])
    # Same through the endpoint (was 422 before the global fix).
    r = client.post("/api/v1/assistant/suggest",
                    json={"degree_level": "undergraduate", "country": "AQ",
                          "budget_band": "mid", "locale": "en"})
    assert r.status_code == 200
    assert r.json()["program_id"] is None
    assert "no verified programme" in r.json()["lines"][0]
