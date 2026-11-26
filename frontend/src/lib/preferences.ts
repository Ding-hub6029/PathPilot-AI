import { ClimateClass, Profile, Program } from './types';
import { CLIMATE_CITIES } from './climate';

/** Countries offered as quick-reply chips for the preferences step. */
export const PREF_COUNTRY_CODES = ['GB', 'US', 'SG', 'AU', 'CA', 'JP', 'KR', 'DE', 'FR', 'NL', 'CH', 'HK'] as const;

/** Chip value -> display label, so summaries show words, never raw enums.
 * Free text passes through unchanged. */
export function climateLabel(v: string | undefined, t: (k: string) => string): string {
  return v === 'warm' ? t('wizard.prefClimateWarm') : v === 'cool' ? t('wizard.prefClimateCool')
    : v === 'four_seasons' ? t('wizard.prefClimateFourSeasons') : v === 'mild' ? t('wizard.prefClimateMild') : (v ?? '');
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
 * Only the user's stated preferences — never a course attribute. */
export function prefSummary(profile: Profile, t: (k: string) => string): string {
  const parts: string[] = [];
  if (profile.prefClimate) parts.push(climateLabel(profile.prefClimate, t));
  if (profile.prefCountries?.length) parts.push(profile.prefCountries.map((c) => t(`country.${c}`)).join(', '));
  if (profile.prefCountriesNote) parts.push(profile.prefCountriesNote);
  if (profile.prefEnvironment) parts.push(environmentLabel(profile.prefEnvironment, t));
  if (profile.prefCity) parts.push(profile.prefCity);
  if (profile.prefAfterGrad) parts.push(afterGradLabel(profile.prefAfterGrad, t));
  if (profile.prefSalary !== '' && profile.prefSalary !== undefined) parts.push(`${profile.prefSalary} ${profile.prefSalaryCurrency ?? ''}`.trim());
  if (profile.prefPressure) parts.push(pressureLabel(profile.prefPressure, t));
  if (profile.prefTeaching) parts.push(teachingLabel(profile.prefTeaching, t));
  return parts.filter(Boolean).join(' · ');
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
  if (want && p.city && p.city.toLowerCase().includes(want)) hints.push(p.city);
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
 * has that class. */
export function bestCityForClimate(
  pref: ClimateClass,
  programs: Program[],
): { city: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const p of programs) {
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
 * to another country. */
export function bestCityForClimateIn(
  pref: ClimateClass,
  countries: string[],
  programs: Program[],
): { city: string; count: number } | null {
  if (!countries.length) return null;
  return bestCityForClimate(pref, programs.filter((p) => countries.includes(p.country)));
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
