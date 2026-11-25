"""Grounded context + citation checking for model output (Day 3, spec Ch13).

The model only ever sees VERIFIED catalogue data as context: programme
requirements/fees/deadlines from data/versions/v2 (source manifest),
expansion programmes, ranking entries, and the verified Gaokao route
facts in ai/gaokao_routes.py. Every factual claim in a model answer must
trace to a supplied source id; claims without a source are rejected and
the caller falls back to the deterministic template (spec Ch17: rejected
outputs reach the user only as templates, and the rejection is counted,
never hidden).

Validation chain (spec Ch13 "校验与拒绝链"):
1. schema + length; 2. evidence/rule id whitelist; 3. rule status
   immutable (a claim may not contradict the engine's rule status);
4. numeric/date/currency cross-check against the cited evidence;
5. no admission probabilities or guarantees; 6. no raw URLs in model
   text — URLs are resolved server-side from ids only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.data import DATA_DIR, EXPANSION, PROGRAMS, RANKINGS

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

@dataclass
class Source:
    id: str
    url: str | None  # None = verified fact whose URL was not re-captured; never rendered as a link
    title: str
    excerpt: str


def _load_manifest() -> dict:
    path = DATA_DIR / "source-manifest.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_MANIFEST: dict | None = None


def _manifest() -> dict:
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = _load_manifest()
    return _MANIFEST


def programme_sources(program_id: str) -> list[Source]:
    """Official sources for one v2 programme, from the source manifest."""
    manifest = _manifest()
    sources = {s["id"]: s for s in manifest.get("sources", [])}
    program = PROGRAMS.get(program_id) or {}
    out: list[Source] = []
    seen: set[str] = set()
    for src in program.get("sources", []):
        sid = src.get("id")
        if sid in seen or sid not in sources:
            continue
        seen.add(sid)
        s = sources[sid]
        excerpt = next((f["excerpt"] for f in manifest.get("facts", [])
                        if f.get("source_id") == sid and f.get("program_id") == program_id),
                       s.get("title", ""))
        out.append(Source(id=f"src:{program_id}:{sid}", url=s.get("url"),
                          title=s.get("title", sid), excerpt=excerpt or ""))
    for req in program.get("requirements", []):
        for sid in req.get("source_ids", []):
            if sid in seen or sid not in sources:
                continue
            seen.add(sid)
            s = sources[sid]
            out.append(Source(id=f"src:{program_id}:{sid}", url=s.get("url"),
                              title=s.get("title", sid),
                              excerpt=req.get("detail", "")))
    return out


def programme_fact_texts(program_id: str) -> dict[str, str]:
    """Evidence id -> text used by the numeric cross-check: rule details
    plus manifest excerpts for the programme."""
    manifest = _manifest()
    program = PROGRAMS.get(program_id) or {}
    texts: dict[str, str] = {}
    for req in program.get("requirements", []):
        texts[req.get("id", "")] = req.get("detail", "")
        for sid in req.get("source_ids", []):
            texts[f"src:{program_id}:{sid}"] = req.get("detail", "")
    for fact in manifest.get("facts", []):
        if fact.get("program_id") == program_id:
            texts[fact["id"]] = f"{fact.get('field', '')}: {fact.get('value', '')}. {fact.get('excerpt', '')}"
    return texts


def ranking_sources(institution_id: str) -> list[Source]:
    """Ranking entries + provider profile pages for one institution."""
    out: list[Source] = []
    inst = next((i for i in RANKINGS.get("institutions", [])
                 if i.get("id") == institution_id), None)
    if inst is None:
        return out
    for entry in RANKINGS.get("entries", []):
        if entry.get("institution_id") != institution_id:
            continue
        if entry.get("verification_status") != "verified":
            continue
        provider = entry.get("provider", "")
        out.append(Source(
            id=f"rank:{provider}:{institution_id}",
            url=entry.get("source_url"),
            title=f"{provider.upper()} {entry.get('edition_label')} rank",
            excerpt=f"{inst.get('official_name')} is ranked "
                    f"{entry.get('rank_display')} ({provider.upper()} "
                    f"{entry.get('edition_label')})"
                    + (f", score {entry.get('score')}" if entry.get("score") is not None else "")
                    + "."))
    for provider, url in (inst.get("provider_profiles") or {}).items():
        out.append(Source(id=f"profile:{provider}:{institution_id}", url=url,
                          title=f"{provider.upper()} profile page",
                          excerpt=f"Official {provider.upper()} profile page for "
                                  f"{inst.get('official_name')}."))
    if inst.get("official_website"):
        out.append(Source(id=f"site:{institution_id}",
                          url=inst.get("official_website"),
                          title=f"{inst.get('official_name')} official website",
                          excerpt=f"Official website of {inst.get('official_name')}."))
    return out


def gaokao_sources(program_id: str | None = None) -> list[Source]:
    from ai.gaokao_routes import facts_for_program
    return [Source(id=f["id"], url=f["url"], title=f["topic"],
                   excerpt=f["text"]) for f in facts_for_program(program_id)]


def build_context(sources: list[Source]) -> str:
    """Numbered source list the model must cite by id only."""
    lines = ["Verified sources (cite by id only, e.g. [src:ucl-cs-bsc-2026:ucl-bsc]). "
             "Never cite anything not listed here. Never invent a URL."]
    for s in sources:
        url = s.url or "(no link available — state the fact without a link)"
        lines.append(f"[{s.id}] {s.title} — {url}\n  {s.excerpt}")
    return "\n".join(lines)


def resolve_url(source_id: str, sources: list[Source]) -> str | None:
    for s in sources:
        if s.id == source_id:
            return s.url
    return None


# ---------------------------------------------------------------------------
# Citation checking (spec Ch13 validation chain)
# ---------------------------------------------------------------------------

CLAIM_KINDS = ("fact", "inference", "limitation", "recommendation")

# Admission-probability / guarantee phrasing, across the six locales.
# A bare "%" is NOT banned: verified stats (e.g. "32.6% international")
# legitimately contain one. Only admission-scoped probability/guarantee
# language is forbidden.
FORBIDDEN_PATTERNS = [
    r"probability of admission", r"admission probability", r"chance[s]? of admission",
    r"admission chances?", r"likelihood of (being )?admit", r"guaranteed? admission",
    r"guarantee[sd]? (you|that you)", r"will (definitely )?get in", r"will be admitted",
    r"录取概率", r"录取几率", r"录取机会", r"保证录取", r"保证能进", r"一定能进",
    r"probabilidad de admisi", r"admisión garantizada", r"probabilité d.admission",
    r"admission garantie", r"probabilidade de admiss", r"admissão garantida",
    r"احتمال القبول", r"قبول مضمون",
]

# Words that state a rule outcome, per language, mapped to engine status.
_STATUS_WORDS = {
    "MET": ["meets", "satisfies", "meets the stated minimum", "符合", "满足", "cumple", "satisfait", "atende"],
    "NOT_MET": ["does not meet", "doesn't meet", "fails", "does not satisfy", "不符合", "不满足",
                "no cumple", "ne satisfait pas", "não atende"],
    "UNKNOWN": ["cannot be decided", "can't be decided", "unknown", "无法判断", "未知",
                "no se puede determinar", "ne peut pas être déterminé", "não pode ser determinado"],
}

# Inference markers (en + zh checked; other locales are prompt-enforced
# and not marker-checked, documented in docs/AI_INTEGRATION.md).
_INFERENCE_MARKERS = ["likely", "suggests", "may ", "might ", "appears", "seems",
                      "could ", "可能", "或许", "看起来", "建议", "推测"]

_NUMBER_RE = re.compile(r"(?:GBP|SGD|USD|£|S\$|¥)?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,})")
_MEASURE_RE = re.compile(r"(GBP|SGD|USD|£|S\$|¥|%|percent|per year|total|overall|score)", re.IGNORECASE)


@dataclass
class CheckResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    def error_text(self) -> str:
        return "; ".join(self.errors)


def _numbers_in(text: str) -> list[str]:
    """Measurement-like numbers only: currency amounts, decimals (scores),
    4+ digit numbers (years, fees). Small bare integers (counts) are not
    cross-checked — a claim may say '3 rules' without a source number."""
    out = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"[^\d.]", "", raw)
        if not digits:
            continue
        if "." in digits or len(digits.replace(".", "")) >= 4 or _MEASURE_RE.search(raw):
            out.append(digits)
    return out


def _norm_number(n: str) -> str:
    return n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "")


def check_model_output(payload, *, allowed_evidence_ids,
                       allowed_rule_ids, rule_status,
                       evidence_texts: dict[str, str],
                       allowed_candidate_ids=frozenset(),
                       locale: str = "en") -> CheckResult:
    """Validate one structured model output (spec Ch13 output schema).

    ``rule_status`` maps rule_id -> engine status (MET/NOT_MET/UNKNOWN/
    NOT_APPLICABLE). ``evidence_texts`` maps evidence id -> the text the
    cited fact must be consistent with (rule detail / manifest excerpt).
    """
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    if not isinstance(payload, dict):
        return CheckResult(False, ["output is not a JSON object"])
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        fail("summary must be a non-empty string of at most 500 characters")
    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) > 20:
        fail("claims must be a list of at most 20 items")
        claims = []
    for i, claim in enumerate(claims):
        tag = f"claims[{i}]"
        if not isinstance(claim, dict):
            fail(f"{tag} is not an object")
            continue
        text = claim.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            fail(f"{tag}.text must be a non-empty string of at most 500 characters")
            continue
        kind = claim.get("kind")
        if kind not in CLAIM_KINDS:
            fail(f"{tag}.kind must be one of {list(CLAIM_KINDS)}")
            continue
        rule_ids = claim.get("rule_ids") or []
        evidence_ids = claim.get("evidence_ids") or []
        if not isinstance(rule_ids, list) or not isinstance(evidence_ids, list):
            fail(f"{tag}.rule_ids/evidence_ids must be lists")
            continue
        for rid in rule_ids:
            if rid not in allowed_rule_ids:
                fail(f"{tag} cites unknown rule_id {rid!r}")
        for eid in evidence_ids:
            if eid not in allowed_evidence_ids:
                fail(f"{tag} cites unknown evidence_id {eid!r}")
        if kind == "fact" and not evidence_ids:
            fail(f"{tag} is a fact claim with no evidence_ids")
        # No raw URLs in model text — URLs resolve server-side from ids.
        if "http://" in text or "https://" in text or "www." in text:
            fail(f"{tag} contains a raw URL; cite an evidence_id instead")
        # No admission probabilities or guarantees, in any locale.
        lowered = text.lower()
        for pat in FORBIDDEN_PATTERNS:
            if re.search(pat, lowered):
                fail(f"{tag} contains forbidden admission-probability/guarantee phrasing")
                break
        # Rule status immutable: a stated outcome must match the engine.
        for rid in rule_ids:
            expected = rule_status.get(rid)
            if expected is None:
                continue
            for status, words in _STATUS_WORDS.items():
                if any(w in lowered for w in words):
                    if status != expected:
                        fail(f"{tag} states rule {rid} as {status} but the engine says {expected}")
                    break
        # Inference claims must carry explicit inference language (en/zh).
        if kind == "inference" and locale in ("en", "zh-CN"):
            if not any(m in lowered for m in _INFERENCE_MARKERS):
                fail(f"{tag} is an inference claim without explicit inference language")
        # Numeric cross-check against the cited evidence text.
        if kind == "fact" and evidence_ids:
            cited = " ".join(evidence_texts.get(eid, "") for eid in evidence_ids)
            cited_norm = cited.replace(",", "")
            for num in _numbers_in(text):
                if _norm_number(num) not in cited_norm and num not in cited_norm:
                    fail(f"{tag} states number {num} which is not in the cited evidence")
    unknowns = payload.get("unknowns")
    if unknowns is not None:
        if not isinstance(unknowns, list):
            fail("unknowns must be a list")
        else:
            for j, u in enumerate(unknowns):
                if not isinstance(u, dict) or not all(
                        isinstance(u.get(k), str) for k in ("field", "reason", "question")):
                    fail(f"unknowns[{j}] must have string field/reason/question")
    actions = payload.get("actions")
    if actions is not None:
        if not isinstance(actions, list):
            fail("actions must be a list")
        else:
            for j, a in enumerate(actions):
                if not isinstance(a, dict) or not isinstance(a.get("explanation"), str):
                    fail(f"actions[{j}] must have a string explanation")
                    continue
                for eid in a.get("evidence_ids") or []:
                    if eid not in allowed_evidence_ids:
                        fail(f"actions[{j}] cites unknown evidence_id {eid!r}")
                cid = a.get("candidate_id")
                if cid is not None and cid not in allowed_candidate_ids:
                    fail(f"actions[{j}] references unknown candidate_id {cid!r}")
                if "http://" in (a.get("explanation") or "") or "https://" in (a.get("explanation") or ""):
                    fail(f"actions[{j}] contains a raw URL")
    limitations = payload.get("limitations")
    if limitations is not None:
        if not isinstance(limitations, list) or not all(isinstance(x, str) for x in limitations):
            fail("limitations must be a list of strings")
    return CheckResult(valid=not errors, errors=errors)


def render_structured_explanation(payload: dict, sources: list[Source]) -> str:
    """Deterministic rendering of a validated structured output into the
    plain-text `explanation` string the /explain contract already returns.
    URLs come from the server-side source list, never from model text."""
    url_by_id = {s.id: s.url for s in sources}
    lines = [payload.get("summary", "")]
    for claim in payload.get("claims", []):
        cites = ", ".join(claim.get("evidence_ids") or [])
        line = f"- {claim.get('text', '')}"
        if cites:
            links = "; ".join(f"{eid} ({url_by_id[eid]})" for eid in (claim.get("evidence_ids") or [])
                              if url_by_id.get(eid))
            line += f" [evidence: {cites}]" + (f" — {links}" if links else "")
        lines.append(line)
    for u in payload.get("unknowns", []):
        lines.append(f"- Unknown: {u.get('field', '')} — {u.get('question', '')}")
    for a in payload.get("actions", []):
        lines.append(f"- Next: {a.get('explanation', '')}")
    for lim in payload.get("limitations", []):
        lines.append(f"- Limitation: {lim}")
    return "\n".join(line for line in lines if line.strip())
