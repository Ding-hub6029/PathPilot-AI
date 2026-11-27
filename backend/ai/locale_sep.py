"""Locale-aware list separator (Round 24, W2).

Every chat reply that lists names — programmes, institutions, cities,
rule labels — must join them with the separator of the ACTIVE locale,
never another locale's punctuation. Before this module, each call site
hard-coded its own rule (``"、" if locale == "zh-CN" else ", "``), and
two sites in ``ai.assistant`` joined with a bare ``"、"`` in every
locale, so an English reply read "MSc in Computer Science、Bachelor
of Science in Computer Science". The Arabic separator was missing
everywhere (ar fell through to the Latin ", ").

Standard enumeration separators:

- en, es, fr, pt-BR: ", " (comma + space; French enumerations take
  no space before the comma)
- zh-CN: "、" (enumeration comma, no space)
- ar: "، " (Arabic comma + space)

Unknown locales fall back to ", ". The internal evidence excerpts in
``ai.chat`` (``_country_source``, ``_ranking_overview_sources``) keep
their canonical "; " join — that string is a machine format parsed
back by regex — and only the RENDERED line re-joins with this helper.
"""
from __future__ import annotations

from collections.abc import Iterable

LIST_SEPARATORS = {
    "en": ", ",
    "zh-CN": "、",
    "es": ", ",
    "fr": ", ",
    "pt-BR": ", ",
    "ar": "، ",
}


def list_separator(locale: str) -> str:
    """Enumeration separator for ``locale`` (", " for unknown locales)."""
    return LIST_SEPARATORS.get(locale, ", ")


def join_list(items: Iterable[str], locale: str) -> str:
    """Join ``items`` with the active locale's enumeration separator."""
    return list_separator(locale).join(items)
