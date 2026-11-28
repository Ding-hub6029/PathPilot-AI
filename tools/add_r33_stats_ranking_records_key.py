"""Round 33: swap the homepage stats-strip label key.

Removes ``common.languages`` (Round 30 F5, stats-strip "Languages"
label) and adds ``home.rankingRecords`` ("Ranking records") in all
6 locale files, as one-line textual edits so the diff stays two
lines per file (the files are not fully key-sorted; a json round
trip would churn ~994 lines).

Run: python3 tools/add_r33_stats_ranking_records_key.py (from the
project root).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

OLD_KEY = "common.languages"
OLD_VALUES = {
    "en": "Languages",
    "zh-CN": "语言",
    "es": "Idiomas",
    "fr": "Langues",
    "pt-BR": "Idiomas",
    "ar": "اللغات",
}

NEW_KEY = "home.rankingRecords"
NEW_VALUES = {
    "en": "Ranking records",
    "zh-CN": "排名记录",
    "es": "Registros de ranking",
    "fr": "Records de classement",
    "pt-BR": "Registros de ranking",
    "ar": "سجلات التصنيف",
}

# Insert the new key directly after this existing key.
AFTER_KEY = "home.programsTitle"


def main() -> None:
    for loc in LOCALES:
        path = MESSAGES / f"{loc}.json"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        old_line = f' "{OLD_KEY}": {json.dumps(OLD_VALUES[loc], ensure_ascii=False)},\n'
        assert old_line in lines, f"{loc}: {OLD_KEY} line not found as expected"
        assert not any(f'"{NEW_KEY}"' in ln for ln in lines), f"{loc}: {NEW_KEY} already exists"
        after_line = next(
            ln for ln in lines if ln.startswith(f' "{AFTER_KEY}":')
        )
        new_line = f' "{NEW_KEY}": {json.dumps(NEW_VALUES[loc], ensure_ascii=False)},\n'
        out = []
        for ln in lines:
            if ln == old_line:
                continue  # drop the removed key
            out.append(ln)
            if ln == after_line:
                out.append(new_line)
        path.write_text("".join(out), encoding="utf-8")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert OLD_KEY not in data, f"{loc}: {OLD_KEY} still present"
        assert data[NEW_KEY] == NEW_VALUES[loc], f"{loc}: {NEW_KEY} wrong value"
        print(f"{loc}.json: {len(data)} keys")


if __name__ == "__main__":
    main()
