#!/usr/bin/env python3
"""Promote expansion programmes into matching (Day 3, round 6).

Sets matchable=true in data/expansions/expansion.json for every
programme with at least one evaluable rule (see
domain/expansion_eval.evaluable_rules) whose degree_level is
undergraduate / taught_masters, and matchable=false for all others.

The file is edited by raw-text replacement of each programme's own
"matchable" value (located after the programme's "id" and before the
next programme's "id"), so every other byte of the file is preserved
exactly. After editing, the file is reloaded through
app.data.validate_expansion_data and the promotion counts are printed.

Run from the project root:
    .venv/bin/python tools/promote_expansion.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from domain.expansion_eval import evaluable_rules  # noqa: E402

PATH = ROOT / "data" / "expansions" / "expansion.json"


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    promote = set()
    for p in data["programs"]:
        if p.get("degree_level") in ("undergraduate", "taught_masters") \
                and any(evaluable_rules(p).values()):
            promote.add(p["id"])
    text = PATH.read_text(encoding="utf-8")
    # The file is json.dump(indent=1): programme objects are array
    # elements whose keys sit at exactly 3 spaces, so ^   "id": ...$
    # matches programme ids only (requirement/source ids are deeper).
    # Each programme's own "matchable" is the first ^   "matchable":
    # in its segment (nested objects never carry a "matchable" key).
    id_re = re.compile(r'^   "id": "([a-z0-9][a-z0-9\-]*)",$', re.MULTILINE)
    flag_re = re.compile(r'^   "matchable": (true|false),$',
                         re.MULTILINE)
    matches = list(id_re.finditer(text))
    # Programme-level ids are the ones followed (before the next id) by
    # a "matchable" key; nested ids are skipped by checking for it.
    flips = 0
    out = []
    pos = 0
    for i, m in enumerate(matches):
        pid = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end]
        flag = flag_re.search(seg)
        if not flag:
            continue
        want = "true" if pid in promote else "false"
        if flag.group(1) != want:
            seg = seg[:flag.start(1)] + want + seg[flag.end(1):]
            flips += 1
        out.append(text[pos:m.start()])
        out.append(seg)
        pos = end
    out.append(text[pos:])
    PATH.write_text("".join(out), encoding="utf-8")

    # Verify: reload and validate.
    from app.data import validate_expansion_data  # noqa: E402
    fresh = json.loads(PATH.read_text(encoding="utf-8"))
    ranking_ids = set()
    import json as _json
    rankings = _json.loads(
        (ROOT / "data" / "versions" / "v2" / "rankings.json").read_text(
            encoding="utf-8"))
    ranking_ids = {inst["id"] for inst in rankings["institutions"]}
    programs = _json.loads(
        (ROOT / "data" / "versions" / "v2" / "programs.json").read_text(
            encoding="utf-8"))
    v2_ids = {p["id"] for p in programs["programs"]}
    errors = validate_expansion_data(fresh, ranking_ids, v2_ids)
    if errors:
        raise SystemExit(f"validation failed: {errors[:5]}")
    now_true = sum(1 for p in fresh["programs"]
                   if p.get("matchable") is True)
    print(f"flipped flags: {flips}")
    print(f"matchable=true: {now_true} / {len(fresh['programs'])}")
    print(f"display-only: {len(fresh['programs']) - now_true}")
    assert now_true == len(promote), (now_true, len(promote))


if __name__ == "__main__":
    main()
