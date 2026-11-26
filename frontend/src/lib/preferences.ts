import { ClimateClass, MatchResult, Profile, Program } from './types';
import { CLIMATE_CITIES } from './climate';
import { programMatchesField } from './fields';

/** Countries offered as quick-reply chips for the preferences step. */
export const PREF_COUNTRY_CODES = ['GB', 'US', 'SG', 'AU', 'CA', 'JP', 'KR', 'DE', 'FR', 'NL', 'CH', 'HK'] as const;

/** Chip value -> display label, so summaries show words, never raw enums.
 * Free text passes through unchanged. */
export function climateLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'warm' ? t('wizard.prefClimateWarm') : v === 'cool' ? t('wizard.prefClimateCool')
    : v === 'four_seasons' ? t('wizard.prefClimateFourSeasons') : v === 'mild' ? t('wizard.prefClimateMild') : (v ?? '');
}

const FIELD_LABEL_KEYS: Record<string, string> = {
  business: 'wizard.fieldBusiness',
  computing: 'wizard.fieldComputing',
  engineering: 'wizard.fieldEngineering',
  science: 'wizard.fieldScience',
  medicine: 'wizard.fieldMedicine',
  humanities: 'wizard.fieldHumanities',
  arts: 'wizard.fieldArts',
};

/** Localised field label ("Computing"); the raw value when the field
 * is not one of the known directions, '' when none is chosen. */
export function fieldDisplayLabel(field: string | null | undefined, t: (key: string) => string): string {
  if (!field) return '';
  const key = FIELD_LABEL_KEYS[field];
  return key ? t(key) : field;
}

/** Localised track label ("Undergraduate" / "Taught masters"); ''
 * when no track is chosen yet. */
export function trackDisplayLabel(track: string | null | undefined, t: (key: string) => string): string {
  if (track === 'undergraduate') return t('wizard.trackUndergrad');
  if (track === 'taught_masters') return t('wizard.trackMasters');
  return '';
}
export function environmentLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'big_city' ? t('wizard.prefEnvironmentBigCity') : v === 'small_city' ? t('wizard.prefEnvironmentSmallCity')
    : v === 'campus' ? t('wizard.prefEnvironmentCampus') : v === 'quiet_town' ? t('wizard.prefEnvironmentQuietTown') : (v ?? '');
}
export function afterGradLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'stay' ? t('wizard.prefAfterGradStay') : v === 'return_home' ? t('wizard.prefAfterGradReturnHome')
    : v === 'hometown' ? t('wizard.prefAfterGradHometown') : v === 'undecided' ? t('wizard.prefAfterGradUndecided') : (v ?? '');
}
export function pressureLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'low' ? t('wizard.prefPressureLow') : v === 'medium' ? t('wizard.prefPressureMedium')
    : v === 'high' ? t('wizard.prefPressureHigh') : (v ?? '');
}
export function teachingLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'lecture' ? t('wizard.prefTeachingLecture') : v === 'seminar' ? t('wizard.prefTeachingSeminar')
    : v === 'hands_on' ? t('wizard.prefTeachingHandsOn') : (v ?? '');
}

export function hasPreferences(profile: Profile): boolean {
  return !!(
    profile.prefClimate ||
    (profile.prefCountries?.length ?? 0) > 0 ||
    profile.prefCountriesNote ||
    profile.prefEnvironment ||
    profile.prefCity ||
    profile.prefAfterGrad ||
    (profile.prefSalary !== '' && profile.prefSalary !== undefined) ||
    profile.prefPressure ||
    profile.prefTeaching
  );
}

/** One-line summary of the saved preferences, in the user's own words.
 * Only the user's stated preferences — never a course attribute.
 * Round 8: a part that repeats an earlier part (a free-text note that
 * says the same as a chosen enum, e.g. note "大学城·校园氛围" next to
 * the campus label "大学城校园氛围") is dropped instead of rendered
 * twice — the results-page summary had the same tautology as the
 * PrefChat confirmation bubble. */
export function prefSummary(profile: Profile, t: (k: string) => string): string {
  // One entry per preference, tagged when it came from the free-text
  // countries note: only note atoms may lose a single segment (below).
  const parts: { text: string; fromNote: boolean }[] = [];
  if (profile.prefClimate) parts.push({ text: climateLabel(profile.prefClimate, t), fromNote: false });
  if (profile.prefCountries?.length) parts.push({ text: profile.prefCountries.map((c) => t(`country.${c}`)).join(', '), fromNote: false });
  if (profile.prefCountriesNote) parts.push({ text: profile.prefCountriesNote, fromNote: true });
  if (profile.prefEnvironment) parts.push({ text: environmentLabel(profile.prefEnvironment, t), fromNote: false });
  if (profile.prefCity) parts.push({ text: cityDisplayName(profile.prefCity, t), fromNote: false });
  if (profile.prefAfterGrad) parts.push({ text: afterGradLabel(profile.prefAfterGrad, t), fromNote: false });
  if (profile.prefSalary !== '' && profile.prefSalary !== undefined) parts.push({ text: `${profile.prefSalary} ${profile.prefSalaryCurrency ?? ''}`.trim(), fromNote: false });
  if (profile.prefPressure) parts.push({ text: pressureLabel(profile.prefPressure, t), fromNote: false });
  if (profile.prefTeaching) parts.push({ text: teachingLabel(profile.prefTeaching, t), fromNote: false });
  const norm = (s: string) => s.toLowerCase().replace(/[·、，,；;。.\s]/g, '');
  // Round 13: the Round 10 whole-part containment dedupe regressed
  // because a part can itself hold TWO values. The countries note is
  // built by joining reasons with '；' (saveReason in PrefChat,
  // profilePatchFromExtracted in chat.ts), so one part can read
  // "环境优美；校园氛围" while the environment label reads
  // "大学城·校园氛围": neither whole string contains the other, so
  // the old check passed both through and "校园氛围" showed twice.
  // Split every part into atoms on the joining separators first
  // ('；' ';' '、' '，' — never '·' or ',', which live inside the
  // campus label and the multi-country list), then dedupe atoms.
  const atoms = parts.flatMap((p) =>
    p.text.split(/[；;、，]+/).map((s) => s.trim()).filter(Boolean)
      .map((text) => ({ text, fromNote: p.fromNote })),
  );
  // Round 10, R2: exact-match dedupe was not enough — a free-text value
  // can repeat an enum label in fewer words (e.g. city/note "大学城"
  // next to the campus label "大学城·校园氛围"), and the summary then
  // showed the same preference twice ("…大学城·校园氛围 · 大学城").
  // An atom whose normalised form is contained in another atom's (or
  // contains it) is the same preference in fewer/more words: keep the
  // longer, more informative wording, drop the shorter. The 2-character
  // floor keeps a single character shared by chance from ever dropping
  // a real preference. Exact duplicates still keep the first.
  const deduped: { text: string; fromNote: boolean }[] = [];
  for (const a of atoms) {
    const n = norm(a.text);
    if (!n) continue;
    if (deduped.some((k) => norm(k.text) === n)) continue;
    const sub = deduped.findIndex((k) => {
      const kn = norm(k.text);
      return n.length >= 2 && kn.length >= 2 && (kn.includes(n) || n.includes(kn));
    });
    if (sub >= 0) {
      if (n.length > norm(deduped[sub].text).length) deduped[sub] = a;
      continue;
    }
    deduped.push(a);
  }
  // Round 13: a note atom joined with '·' ("环境优美·校园氛围") is
  // not split above — the '·' also lives inside the campus label, so
  // splitting it everywhere would shred the label. Only a NOTE atom
  // may lose a '·'-segment that duplicates another surviving atom:
  // the label itself is never rewritten, it only ever wins.
  const final = deduped.map((a) => {
    if (!a.fromNote || !a.text.includes('·')) return a.text;
    const kept = a.text.split('·').map((s) => s.trim()).filter(Boolean).filter((seg) => {
      const sn = norm(seg);
      if (sn.length < 2) return true;
      return !deduped.some((k) => k !== a && norm(k.text).includes(sn));
    });
    return kept.join('·');
  }).filter(Boolean);
  return final.join(' · ');
}

/** Localised city name for chips and filters: `city.<slug>` when the
 * locale file has one (zh-CN carries the standard exonyms; other
 * locales fall back through t() to the English name, which is the
 * correct display name there). Never a raw key, never an invented
 * name — an untranslated city renders in English. */
export function cityKey(city: string): string {
  const slug = city.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return `city.${slug}`;
}

export function cityDisplayName(city: string, t: (k: string) => string): string {
  if (!city) return city;
  const v = t(cityKey(city));
  return v === cityKey(city) ? city : v;
}

/**
 * Preference hints for one programme: only matches between the user's
 * stated preferences and the programme's VERIFIED data (country, city).
 * A hint is never a course attribute, never a score, and climate /
 * salary / pressure / teaching style are never matched against a
 * programme — there is no official data for them.
 */
export function prefHints(profile: Profile, p: Program, t: (k: string) => string): string[] {
  const hints: string[] = [];
  if ((profile.prefCountries ?? []).includes(p.country)) hints.push(t(`country.${p.country}`));
  const want = (profile.prefCity ?? '').trim().toLowerCase();
  if (want && p.city && p.city.toLowerCase().includes(want)) hints.push(cityDisplayName(p.city, t));
  return hints;
}

// --- Climate (round 6) -------------------------------------------------------
// Mirrors backend/domain/climate.py exactly: same classes, same fit rule.
// A city with no entry gets no signal — its programmes are never demoted.

/** Normalise a stored preference value; free text returns null. */
export function normaliseClimatePref(v: string | undefined): ClimateClass | null {
  return v === 'warm' || v === 'cool' || v === 'four_seasons' || v === 'mild' ? v : null;
}

/** The climate class for a city name, or null when the city is not in
 * the curated table. Prefix match handles campus/area suffixes
 * ("London Bloomsbury" -> "London"). */
export function cityClimate(city: string | undefined): ClimateClass | null {
  if (!city) return null;
  const name = city.trim();
  if (CLIMATE_CITIES[name]) return CLIMATE_CITIES[name].climate;
  for (const known of Object.keys(CLIMATE_CITIES)) {
    if (name.startsWith(known + ' ')) return CLIMATE_CITIES[known].climate;
  }
  return null;
}

/** The climate class for a programme (v2 or converted expansion). */
export function programmeClimate(p: Program): ClimateClass | null {
  return cityClimate(p.city);
}

/** 'fit' | 'neutral' | 'conflict', or null when there is no signal.
 * Conflict = opposite pair {cool, warm}, or four_seasons wanted but the
 * city is warm (no cold winter at all). Never an eligibility verdict. */
export function climateFit(
  pref: ClimateClass | null,
  cityClass: ClimateClass | null,
): 'fit' | 'neutral' | 'conflict' | null {
  if (!pref || !cityClass) return null;
  if (pref === cityClass) return 'fit';
  if ((pref === 'cool' && cityClass === 'warm')
      || (pref === 'warm' && cityClass === 'cool')) return 'conflict';
  if (pref === 'four_seasons' && cityClass === 'warm') return 'conflict';
  return 'neutral';
}

/** The city with the most programmes of a wanted climate class (v2 +
 * expansion), for the pet's climate opinion. Ties break alphabetically
 * so the answer is deterministic. Returns null when no programme's city
 * has that class. Round 8: `track` scopes the count to the applicant's
 * own level — an undergraduate must not be told Zurich has 11
 * programmes when all 11 are taught-master's (the count in the opinion
 * is labelled with the level, and must agree with what the results
 * page will show for that track). */
export function bestCityForClimate(
  pref: ClimateClass,
  programs: Program[],
  track?: string,
): { city: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const p of programs) {
    if (track && p.degreeLevel !== track) continue;
    if (cityClimate(p.city) !== pref || !p.city) continue;
    // Normalise campus-suffixed cities to the table city ("London
    // Bloomsbury" counts as London).
    const tableCity = Object.keys(CLIMATE_CITIES)
      .find((k) => p.city === k || (p.city ?? '').startsWith(k + ' ')) ?? p.city;
    counts.set(tableCity, (counts.get(tableCity) ?? 0) + 1);
  }
  let best: { city: string; count: number } | null = null;
  for (const [city, count] of [...counts.entries()].sort()) {
    if (!best || count > best.count) best = { city, count };
  }
  return best;
}

// --- Country-scoped cities + climate (round 7) ------------------------------
// Fix 1 + Fix 4: no chip or opinion may ever name a city the user did
// not choose. City chips come from the verified programme cities of
// the user's chosen countries only; climate opinions talk about the
// best city of the wanted class WITHIN those countries, and say so
// honestly when the chosen country has no city of that class.

/** Normalise a programme's city to its climate-table city
 * ("London Bloomsbury" -> "London"); the table city is the display
 * name chips and opinions use. */
export function tableCityOf(city: string | undefined): string | null {
  if (!city) return null;
  const match = Object.keys(CLIMATE_CITIES)
    .find((k) => city === k || city.startsWith(k + ' '));
  return match ?? city;
}

/** Verified programme cities in the given countries, unique, sorted
 * by programme count desc (then alphabetically). Switzerland ->
 * Zurich + Lausanne ONLY. Empty when no chosen country has a verified
 * programme city — the caller must then show free text only, never
 * unrelated cities. */
export function citiesInCountries(
  countries: string[],
  programs: Program[],
): { city: string; count: number }[] {
  if (!countries.length) return [];
  const counts = new Map<string, number>();
  for (const p of programs) {
    if (!countries.includes(p.country) || !p.city) continue;
    const city = tableCityOf(p.city) ?? p.city;
    counts.set(city, (counts.get(city) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([city, count]) => ({ city, count }))
    .sort((a, b) => b.count - a.count || a.city.localeCompare(b.city));
}

/** The city with the most programmes of a wanted climate class WITHIN
 * the given countries. Null when no programme city in those countries
 * has that class — the caller must say so honestly instead of pivoting
 * to another country. `track` scopes the count as in
 * bestCityForClimate. */
export function bestCityForClimateIn(
  pref: ClimateClass,
  countries: string[],
  programs: Program[],
  track?: string,
): { city: string; count: number } | null {
  if (!countries.length) return null;
  return bestCityForClimate(pref, programs.filter((p) => countries.includes(p.country)), track);
}

/** True when free text says more than the country names it contains
 * (e.g. a reason): the remainder after removing every catalogue
 * country name (localised + English + code), separators and
 * conjunctions is non-empty. "瑞士" -> false; "瑞士和英国" -> false;
 * "我想去瑞士，因为那边环境优美" -> true. Used by the offline
 * fallback so a sentence that carried a reason never collapses to a
 * bare country keyword. */
export function hasExtraWordsBeyondCountries(
  text: string,
  t: (k: string) => string,
  enMessages: Record<string, string>,
): boolean {
  let rest = text.toLowerCase();
  for (const code of PREF_COUNTRY_CODES) {
    for (const name of [t(`country.${code}`), enMessages[`country.${code}`] ?? '', code]) {
      if (!name) continue;
      rest = rest.split(name.toLowerCase()).join('');
    }
  }
  rest = rest.replace(/[、，,；;。.\s]/g, '').replace(/和|与|及|and|or/g, '');
  return rest.length > 0;
}

/** Every verified programme city of the given countries with its
 * climate class (null when the city is not in the table) and programme
 * count — the honest material for a "no city of that class here"
 * answer: the actual classes of the country's real cities. */
export function countryCitiesWithClimate(
  countries: string[],
  programs: Program[],
): { city: string; climate: ClimateClass | null; count: number }[] {
  return citiesInCountries(countries, programs).map(({ city, count }) => ({
    city,
    climate: cityClimate(city),
    count,
  }));
}

// --- Switzerland honesty (round 8) ----------------------------------------
// A chosen country with no programme in the filtered set is a silent
// zero unless the page says so. These helpers are shared by the results
// page and RecChat: which preferred countries are missing from the
// evaluated set, and the closest verified alternatives in the full
// catalogue (same track first, then the same field on another track —
// e.g. for a Swiss undergraduate in computing: EPFL engineering UG,
// then Swiss taught-master's CS). Worker E is collecting Swiss UG CS
// programmes in parallel; when they land they flow through the same
// helpers and the zero disappears on its own.

/** Preferred country codes with no programme in the evaluated results. */
export function missingPrefCountries(
  profile: Profile,
  resultPrograms: Program[],
): string[] {
  const have = new Set(resultPrograms.map((p) => p.country));
  return (profile.prefCountries ?? []).filter((c) => !have.has(c));
}

/** Closest verified alternatives in one country: up to 3 on the same
 * track (any field) and up to 3 in the same field on another track.
 * Only matchable programmes (display-only ones cannot be checked).
 * Deterministic order: same track by institution then id, same field
 * by institution then id. */
export function countryAlternatives(
  country: string,
  profile: Profile,
  programs: Program[],
): { sameTrack: Program[]; sameField: Program[] } {
  const inCountry = programs.filter(
    (p) => p.country === country && p.matchable !== false,
  );
  const byInstitution = (a: Program, b: Program) =>
    a.institution.localeCompare(b.institution) || a.id.localeCompare(b.id);
  const sameTrack = inCountry
    .filter((p) => !profile.track || p.degreeLevel === profile.track)
    .sort(byInstitution)
    .slice(0, 3);
  const sameTrackIds = new Set(sameTrack.map((p) => p.id));
  const field = profile.field;
  const sameField = field
    ? inCountry
      .filter((p) => !sameTrackIds.has(p.id) && programMatchesField(p, field))
      .sort(byInstitution)
      .slice(0, 3)
    : [];
  return { sameTrack, sameField };
}

/** How many verified programmes the full catalogue holds in a country
 * (any track or field) — the honest denominator for a "no programme
 * in these results" note. */
export function catalogueCountInCountry(country: string, programs: Program[]): number {
  return programs.filter((p) => p.country === country).length;
}

// --- Preference-first recommendation order (round 9, R1) ------------------
// The old order was eligibility-first (MET, then PARTIAL_UNKNOWN, then
// NOT_MET), so a user whose stated first choice was Switzerland saw
// UCL / Imperial / Peking / Tsinghua / MIT in both batches while the
// five verified Swiss UG programmes sat buried mid-list — a silent
// zero for the preference the user actually stated. Recommendations
// are now ordered: (1) the user's preferred countries first, in the
// order they listed them; (2) eligibility rank within that; (3) the
// preferred city first within the same country + eligibility; (4)
// climate conflicts last. A preferred country with no programme in
// the set is still explained by missingPrefCountries / the results
// page — never silently zero. Pure (no mutation): returns a new array.

export function sortRecsByPreference(
  recs: MatchResult[],
  programs: Program[],
  profile: Profile,
): MatchResult[] {
  const rank = (s: string) => s === 'MET' ? 0 : s === 'PARTIAL_UNKNOWN' ? 1 : s === 'NOT_MET' ? 2 : 3;
  const prefCountries = profile.prefCountries ?? [];
  const wantCity = (profile.prefCity ?? '').trim().toLowerCase();
  const byId = new Map(programs.map((p) => [p.id, p]));
  return [...recs].sort((a, b) => {
    const pa = byId.get(a.programId);
    const pb = byId.get(b.programId);
    const ca = pa ? prefCountries.indexOf(pa.country) : -1;
    const cb = pb ? prefCountries.indexOf(pb.country) : -1;
    const ra = ca === -1 ? Infinity : ca;
    const rb = cb === -1 ? Infinity : cb;
    if (ra !== rb) return ra - rb;
    const ea = rank(a.eligibilitySummary);
    const eb = rank(b.eligibilitySummary);
    if (ea !== eb) return ea - eb;
    if (wantCity) {
      const ma = pa && (pa.city ?? '').toLowerCase() === wantCity ? 0 : 1;
      const mb = pb && (pb.city ?? '').toLowerCase() === wantCity ? 0 : 1;
      if (ma !== mb) return ma - mb;
    }
    const fa = a.preferenceFit === 'conflict' ? 1 : 0;
    const fb = b.preferenceFit === 'conflict' ? 1 : 0;
    if (fa !== fb) return fa - fb;
    return a.programId.localeCompare(b.programId);
  });
}
