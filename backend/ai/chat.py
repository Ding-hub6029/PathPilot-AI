"""Model-backed free-text chat for the pet 小罗盘 (Day 3).

The template assistant in ``ai.assistant`` stays the fast path: when no
AI provider is configured, or when the model fails / its output fails
citation validation, the answer is the template ``ask()`` result with
``ai_status="unavailable"`` — a model answer is never faked.

Model path (only when a provider is configured):

- the personal-data guard runs FIRST (reused from ``ai.assistant``);
  a message that looks like it contains a name/phone/email is refused
  with the fixed refusal line — the value is never echoed and never
  stored;
- retrieval finds verified facts only: programme fee/IELTS/deadline and
  rank lookup via the template assistant's helpers, plus the verified
  Gaokao-route facts when the message mentions Gaokao/高考;
- the model sees ONLY those retrieved sources, as an evidence catalogue
  in a JSON envelope (``{task: "chat", prompt_version, locale, message,
  history, evidence_catalog}``); its structured JSON output is validated
  by ``ai.grounding.check_model_output`` (id whitelist, numeric
  cross-check, no probabilities/guarantees, no raw URLs), with one
  repair retry; on any failure the template answer is returned;
- evidence URLs are resolved server-side from cited source ids, never
  taken from model text. The final answer is at most 3 lines,
  conclusion first; unknown stays unknown, with the eligibility-check
  offer as the next step.

Nothing is logged or stored: no message, history or key ever leaves
this call except inside the provider request itself.
"""
from __future__ import annotations

import json
import re

from ai.assistant import (LOCALES, _match_programmes, _norm, _t,
                          ask as assistant_ask, check_no_forbidden,
                          contains_personal_data)
from ai.grounding import (FORBIDDEN_PATTERNS, Source,
                          check_model_output, gaokao_sources,
                          programme_fact_texts, programme_sources,
                          ranking_sources, resolve_url)
from ai.prompts import PROMPT_VERSION, chat_system
from ai.provider import ProviderAdapter, ProviderError
from app.data import DATA_DIR, PROGRAMS

MAX_HISTORY_TURNS = 6


# ---------------------------------------------------------------------------
# Model-JSON parsing (same fence tolerance as ai.explain)
# ---------------------------------------------------------------------------

def _parse_model_json(text: str) -> dict | None:
    """Parse a model reply as JSON, tolerating ```json fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Retrieval: verified facts only, enriched with manifest fact texts
# ---------------------------------------------------------------------------

_MANIFEST_FACTS: dict | None = None


def _manifest_facts() -> dict[tuple[str, str], list[str]]:
    """(program_id, source_id) -> manifest fact texts, e.g. the fee line
    "Overseas fees 2026/27: GBP 46,700 per year".

    Programme sources on their own carry only a page-title excerpt, so
    without these the model could never state a fee or deadline — and
    the numeric cross-check could never pass one either.
    """
    global _MANIFEST_FACTS
    if _MANIFEST_FACTS is None:
        grouped: dict[tuple[str, str], list[str]] = {}
        try:
            with open(DATA_DIR / "source-manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)
            for fact in manifest.get("facts", []):
                key = (fact.get("program_id", ""), fact.get("source_id", ""))
                grouped.setdefault(key, []).append(
                    f"{fact.get('field', '')}: {fact.get('value', '')}. "
                    f"{fact.get('excerpt', '')}")
        except (OSError, ValueError):
            grouped = {}
        _MANIFEST_FACTS = grouped
    return _MANIFEST_FACTS


def _enriched_programme_sources(program_id: str) -> list[Source]:
    """Programme sources whose excerpts carry the manifest fact texts
    (and rule details) for their own source id — verified facts only,
    never anything from outside the programme's own sources."""
    sources = programme_sources(program_id)
    facts = _manifest_facts()
    details = programme_fact_texts(program_id)
    out: list[Source] = []
    for s in sources:
        sid = s.id[len(f"src:{program_id}:"):] if s.id.startswith(f"src:{program_id}:") else s.id
        extra = list(facts.get((program_id, sid), []))
        detail = details.get(f"src:{program_id}:{sid}", "")
        if detail:
            extra.append(detail)
        excerpt = s.excerpt + (" " + " ".join(extra) if extra else "")
        out.append(Source(id=s.id, url=s.url, title=s.title, excerpt=excerpt))
    return out


def _retrieve(message: str, locale: str):
    """(template ask() result, retrieved sources, programme ids).

    Retrieval reuses the template assistant: its ``ask()`` already does
    the programme fee/IELTS/deadline match and the rank lookup, and its
    ``_match_programmes`` covers the ambiguous two-programme case where
    ``ask()`` returns no single programme. Gaokao keywords add the
    verified Gaokao-route facts for the matched programme (or the
    general routes when no programme matched).
    """
    template = assistant_ask(message, locale)
    sources: list[Source] = []
    seen: set[str] = set()

    def _add(new: list[Source]) -> None:
        for s in new:
            if s.id not in seen:
                seen.add(s.id)
                sources.append(s)

    pids: list[str] = []
    if template.get("program_id"):
        pids.append(template["program_id"])
    else:
        for pid in _match_programmes(_norm(message or "")):
            if pid in PROGRAMS and pid not in pids:
                pids.append(pid)
    for pid in pids:
        _add(_enriched_programme_sources(pid))
    if template.get("institution_id"):
        _add(ranking_sources(template["institution_id"]))
    lowered = (message or "").lower()
    if "gaokao" in lowered or "高考" in (message or ""):
        _add(gaokao_sources(pids[0] if pids else None))
    return template, sources, pids


def _evidence_texts(sources: list[Source], programme_ids: list[str]) -> dict[str, str]:
    """Evidence id -> text for the numeric cross-check: the enriched
    source excerpts, plus the manifest fact texts under their own fact
    ids (so a model citing a fact id is checked against that fact)."""
    texts = {s.id: s.excerpt for s in sources}
    for pid in programme_ids:
        for fid, txt in programme_fact_texts(pid).items():
            if txt:
                texts.setdefault(fid, txt)
    return texts


def _clean_history(history: list[dict] | None) -> list[dict]:
    """Last 6 turns only; user/assistant roles, string content capped
    at 500 chars. Anything else is dropped, never repaired."""
    out: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        out.append({"role": role, "content": content[:500]})
    return out[-MAX_HISTORY_TURNS:]


# ---------------------------------------------------------------------------
# Validation of the structured model output
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"(?:GBP|SGD|USD|£|S\$|¥)?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,})")
_MEASURE_RE = re.compile(
    r"(GBP|SGD|USD|£|S\$|¥|%|percent|per year|total|overall|score)", re.IGNORECASE)


def _numbers_in(text: str) -> list[str]:
    """Measurement-like numbers only (same rule as ai.grounding)."""
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


def _safety_errors(text: str, evidence_joined: str) -> list[str]:
    """Extra checks check_model_output does not apply to the summary /
    action text: no raw URLs, no admission-probability/guarantee
    phrasing, no API-key-like material, and no number that is not in
    the cited evidence (a fact not in the retrieved sources)."""
    errors: list[str] = []
    lowered = text.lower()
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        errors.append("text contains a raw URL; cite an evidence_id instead")
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, lowered):
            errors.append("text contains forbidden admission-probability/guarantee phrasing")
            break
    found = check_no_forbidden([text])
    if found:
        errors.append(f"text contains forbidden wording: {', '.join(found)}")
    if "api key" in lowered or "api_key" in lowered or "sk-" in lowered:
        errors.append("text mentions an API key")
    cited_norm = evidence_joined.replace(",", "")
    for num in _numbers_in(text):
        if _norm_number(num) not in cited_norm and num not in cited_norm:
            errors.append(f"text states number {num} which is not in the cited evidence")
    return errors


def _validate_chat_payload(payload: dict, sources: list[Source],
                           evidence_texts: dict[str, str],
                           locale: str) -> list[str]:
    """All validation errors for one structured model output (empty =
    valid). check_model_output covers claims/actions; the summary and
    action explanations get the extra safety scan as well."""
    check = check_model_output(
        payload, allowed_evidence_ids=set(evidence_texts),
        allowed_rule_ids=set(), rule_status={},
        evidence_texts=evidence_texts, locale=locale)
    errors = list(check.errors)
    joined = " ".join(evidence_texts.values())
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        errors.extend(_safety_errors(summary, joined))
    for action in payload.get("actions") or []:
        if isinstance(action, dict) and isinstance(action.get("explanation"), str):
            errors.extend(_safety_errors(action["explanation"], joined))
    return errors


# ---------------------------------------------------------------------------
# Rendering a validated payload into at most 3 lines, conclusion first
# ---------------------------------------------------------------------------

def _render_lines(payload: dict, locale: str, sources: list[Source]) -> list[str]:
    lines: list[str] = []
    summary = (payload.get("summary") or "").strip()
    for part in summary.splitlines():
        part = part.strip()
        if part and part not in lines:
            lines.append(part)
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        text = (claim.get("text") or "").strip()
        if text and text not in lines and len(lines) < MAX_HISTORY_TURNS - 3:
            lines.append(text)
    added_action = False
    for action in payload.get("actions") or []:
        if not isinstance(action, dict):
            continue
        text = (action.get("explanation") or "").strip()
        if text and text not in lines and len(lines) < 3:
            lines.append(text)
            added_action = True
    unknowns = payload.get("unknowns") or []
    is_unknown = bool(unknowns) or not sources
    if len(lines) < 3:
        if is_unknown:
            offer = _t(locale, "unknown_2")
            if offer not in lines:
                lines.append(offer)
        elif not added_action:
            nxt = _t(locale, "next")
            if nxt not in lines:
                lines.append(nxt)
    return lines[:3]


def _resolve_evidence_url(payload: dict, sources: list[Source]) -> str | None:
    """First cited evidence id that resolves to a URL; else the first
    retrieved source with a URL; else None. Never from model text."""
    for section in (payload.get("claims") or [], payload.get("actions") or []):
        for item in section:
            if not isinstance(item, dict):
                continue
            for eid in item.get("evidence_ids") or []:
                url = resolve_url(eid, sources)
                if url:
                    return url
    for s in sources:
        if s.url:
            return s.url
    return None


def _template_result(template: dict, sources: list[Source]) -> dict:
    return {"lines": template["lines"],
            "evidence_url": template.get("evidence_url"),
            "ai_status": "unavailable", "model": None,
            "sources": [{"id": s.id, "url": s.url, "title": s.title}
                        for s in sources]}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def answer(message: str, locale: str = "en",
           history: list[dict] | None = None,
           provider: ProviderAdapter | None = None) -> dict:
    """Answer one free-text question for 小罗盘.

    Returns ``{lines, evidence_url, ai_status, model, sources}``:
    ``lines`` at most 3, conclusion first; ``evidence_url`` resolved
    server-side from a cited source id (or the template's evidence
    link); ``ai_status`` is ``"available"`` only when a validated model
    output was actually used; ``model`` is ``"provider/model"`` or None;
    ``sources`` is the retrieved evidence catalogue.
    """
    loc = locale if locale in LOCALES else "en"
    msg = message or ""

    # (a) Personal-data guard first — the value is never echoed.
    if contains_personal_data(msg):
        template = assistant_ask(msg, loc)
        return {"lines": template["lines"], "evidence_url": None,
                "ai_status": "unavailable", "model": None, "sources": []}

    provider = provider or ProviderAdapter()
    template, sources, pids = _retrieve(msg, loc)
    sources_out = [{"id": s.id, "url": s.url, "title": s.title} for s in sources]

    # (c) No key: the template assistant is the honest answer.
    if not provider.available:
        return _template_result(template, sources)

    # (d) Key present: model over the retrieved sources only.
    evidence_texts = _evidence_texts(sources, pids)
    envelope = {
        "task": "chat",
        "prompt_version": PROMPT_VERSION,
        "locale": loc,
        "message": msg,
        "history": _clean_history(history),
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
    }
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]
    try:
        result = provider.chat(messages, system=chat_system(loc), timeout_s=12.0)
    except ProviderError:
        return _template_result(template, sources)
    parsed = _parse_model_json(result.text)
    if parsed is None:
        return _template_result(template, sources)
    errors = _validate_chat_payload(parsed, sources, evidence_texts, loc)
    if errors:
        # One repair retry: send the validation errors back, ask to fix
        # only those. Anything still invalid falls back to the template.
        repair = ("Your previous output failed validation. Fix ONLY these "
                  f"problems and output JSON only: {'; '.join(errors)}\n\n"
                  f"Previous output:\n{result.text[:4000]}")
        try:
            retry = provider.chat(
                messages + [{"role": "user", "content": repair}],
                system=chat_system(loc), timeout_s=8.0)
        except ProviderError:
            return _template_result(template, sources)
        parsed2 = _parse_model_json(retry.text)
        if parsed2 is None:
            return _template_result(template, sources)
        errors2 = _validate_chat_payload(parsed2, sources, evidence_texts, loc)
        if errors2:
            return _template_result(template, sources)
        parsed = parsed2
    lines = _render_lines(parsed, loc, sources)
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return _template_result(template, sources)
    return {"lines": lines,
            "evidence_url": _resolve_evidence_url(parsed, sources),
            "ai_status": "available",
            "model": f"{result.provider}/{result.model}",
            "sources": sources_out}
