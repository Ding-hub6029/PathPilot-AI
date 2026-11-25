"""Climate preference signal (Day 3, round 6).

Pure functions only — no I/O. The curated city -> climate table lives
in data/expansions/climate.json and is loaded by app/data.py; this
module only decides what a (preference, city class) pair means.

Classes (see docs/CLIMATE.md for the per-city basis):
  warm / cool / four_seasons / mild — the same four values the wizard
  offers as climate preferences (frontend/src/lib/preferences.ts).

Fit rule (deliberately narrow — only clear mismatches demote):
  - same class            -> "fit"
  - cool <-> warm         -> "conflict" (opposite ends of the scale)
  - four_seasons vs warm  -> "conflict" (a warm city has no cold winter
                             at all, so it cannot give four seasons)
  - everything else       -> "neutral" (a partial overlap: a
                             four-season city does have cold winters for
                             a cool-seeker, and hot summers for a
                             warm-seeker; a mild city is neither hot
                             nor cold)
  - unknown preference, unknown city class, or no preference at all
                          -> None (no signal; the programme is never
                             demoted or excluded on climate)

Climate is a preference, never an eligibility rule: it never produces
NOT_MET and never changes a rule status — it only orders results.
"""
from __future__ import annotations

CLIMATE_CLASSES = ("warm", "cool", "four_seasons", "mild")


def normalise_preference(value: object) -> str | None:
    """One of the four known preference values, else None.

    Free-text preferences (the wizard allows typing anything) produce
    no signal rather than a guessed mapping.
    """
    if isinstance(value, str) and value.strip() in CLIMATE_CLASSES:
        return value.strip()
    return None


def climate_fit(preference: str | None, city_climate: str | None) -> str | None:
    """'fit' | 'neutral' | 'conflict', or None when there is no signal."""
    pref = normalise_preference(preference)
    if pref is None or city_climate not in CLIMATE_CLASSES:
        return None
    if pref == city_climate:
        return "fit"
    if {pref, city_climate} == {"cool", "warm"}:
        return "conflict"
    if pref == "four_seasons" and city_climate == "warm":
        return "conflict"
    return "neutral"


# v2 institution ids (rankings.json) -> city. Verified by the v2
# programme data itself: UCL/Imperial programmes are in London
# ("London Bloomsbury", "London South Kensington"), NUS/NTU programmes
# are in Singapore (country SG). The expansion institution records use
# different ids, so these four are kept here, not inferred.
V2_INSTITUTION_CITIES: dict[str, str] = {
    "ucl": "London", "imperial": "London",
    "nus": "Singapore", "ntu": "Singapore",
}


def resolve_city_climate(program: dict, climate_table: dict[str, dict],
                         institution_cities: dict[str, str],
                         program_institution: dict[str, str] | None = None
                         ) -> str | None:
    """The climate class for a programme, or None when it cannot be
    resolved from verified data.

    Resolution order (never invented):
    1. the programme's own city, exact match in the table;
    2. the programme's own city with a campus/area suffix
       ("London Bloomsbury" -> "London");
    3. the city of the programme's institution (expansion institution
       records carry a verified city; v2 programmes resolve through
       the program_institution mapping — programme id -> institution
       id — plus V2_INSTITUTION_CITIES above).
    A programme whose city cannot be resolved gets no signal.
    """
    city = program.get("city")
    if isinstance(city, str) and city.strip():
        name = city.strip()
        if name in climate_table:
            return climate_table[name].get("climate")
        for known in climate_table:
            if name.startswith(known + " "):
                return climate_table[known].get("climate")
    inst_id = program.get("institution_id")
    if not inst_id and program_institution:
        inst_id = program_institution.get(program.get("id", ""))
    cities = dict(institution_cities)
    cities.update(V2_INSTITUTION_CITIES)
    if inst_id and inst_id in cities:
        return climate_table.get(cities[inst_id], {}).get("climate")
    return None
