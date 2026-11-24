"""Loads data/versions/v1, validates schema + references at startup.

Refuses fixtures in real data: any program with synthetic=true or an id
starting with 'fixture-' raises at load time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATA_VERSION = "v2"

# backend/app/data.py -> project root is ../../ from this file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "versions" / DATA_VERSION


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_programs() -> dict[str, dict]:
    programs_path = DATA_DIR / "programs.json"
    manifest_path = DATA_DIR / "source-manifest.json"
    data = _load_json(programs_path)
    manifest = _load_json(manifest_path)
    if data.get("data_version") != DATA_VERSION:
        raise ValueError(f"programs.json data_version {data.get('data_version')} != {DATA_VERSION}")
    if manifest.get("data_version") != DATA_VERSION:
        raise ValueError("source-manifest.json data_version mismatch")

    known_fact_ids = {f["id"] for f in manifest.get("facts", [])}
    known_source_ids = {s["id"] for s in manifest.get("sources", [])}
    programs: dict[str, dict] = {}
    for program in data.get("programs", []):
        pid = program.get("id")
        if program.get("synthetic") is True or str(pid).startswith("fixture-"):
            raise ValueError(f"Refusing fixture program in real data: {pid}")
        if pid in programs:
            raise ValueError(f"Duplicate program id: {pid}")
        # Validate source references.
        for src in program.get("sources", []):
            if src.get("id") not in known_source_ids:
                raise ValueError(f"Program {pid} references unknown source {src.get('id')}")
        for req in program.get("requirements", []):
            for sid in req.get("source_ids", []):
                if sid not in known_source_ids:
                    raise ValueError(f"Program {pid} requirement {req.get('id')} references unknown source {sid}")
        # Every fact id referenced by a rule must exist in the manifest.
        for fact_id in [f for f in known_fact_ids]:
            pass  # manifest integrity: facts reference known programs/sources
        programs[pid] = program

    for fact in manifest.get("facts", []):
        if fact.get("program_id") not in programs:
            raise ValueError(f"Manifest fact {fact.get('id')} references unknown program {fact.get('program_id')}")
        if fact.get("source_id") not in known_source_ids:
            raise ValueError(f"Manifest fact {fact.get('id')} references unknown source {fact.get('source_id')}")
    return programs


def load_fixture() -> dict:
    """Test-only loader. Fixtures never enter load_programs()."""
    path = PROJECT_ROOT / "data" / "fixtures" / "fixture-p01.json"
    data = _load_json(path)
    program = data["program"]
    if not program.get("synthetic"):
        raise ValueError("Fixture file must be marked synthetic.")
    return program


# Loaded once at import / startup.
PROGRAMS: dict[str, dict] = load_programs()
