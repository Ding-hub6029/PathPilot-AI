import { joinList, parenNote } from './format';
import { cityDisplayName, climateLabel } from './preferences';

/**
 * Round 28 D2 — localised re-render of the offline pref-chat
 * fallback's deterministic prefix lines.
 *
 * THE DEFECT: the model-led chat path's offline reply comes from the
 * backend's `_fallback_result`, whose first line is the cities line
 * (`evidence_cities_line`) — a stored string in the REQUEST locale.
 * After a language switch it stayed in the old locale, and it
 * carried no "no cool city" / "climate is only a preference"
 * sentence at all (the Round 27 W5 rewording of
 * `wizard.chatOpClimateNoMatch` fixed a string the failing path
 * never renders — the guided queue's `opinion('climate')`).
 *
 * THE FIX: the backend now attaches the structured block
 * `evidence_cities: [{city, climate, count}]` (+ `climate_wanted`)
 * to the fallback result ONLY when the cities line was actually
 * placed into `lines[0]`. This pure helper re-renders, in the
 * CURRENT locale, the replacement for the stored deterministic
 * prefix lines `lines[0..1]` (cities line + generic suggest line):
 *
 * - (a) the cities line, from the structured items through the new
 *   keys `wizard.prefFallbackCitiesLine` /
 *   `wizard.prefFallbackCityItem` (wording copied verbatim from the
 *   backend's `_EVIDENCE_CITIES_LINES` / `_CITY_ITEM` tables);
 *   city names via `cityDisplayName`, the climate class via the
 *   existing climate labels (`climateLabel`) — the same labels the
 *   guided `opinion('climate')` uses, so e.g. en reads "Four
 *   seasons" where the backend's stored line reads "four-season"
 *   (a pre-existing frontend label, not a new translation);
 * - (b) when `climate_wanted` is set AND no listed city has that
 *   class, the existing `wizard.chatOpClimateNoMatch` sentence
 *   (reworded in R27 W5) with `{want, cities}` — `cities` here is
 *   the same city list WITHOUT counts, exactly as the guided
 *   `opinion('climate')` builds it (`City (class)` items via
 *   `parenNote`, joined with `joinList`);
 * - (c) in the no-match case the generic suggest line is dropped
 *   (the climate sentence replaces it — the user is already inside
 *   the eligibility check); in the match case (some city HAS the
 *   wanted class) only the cities line is returned.
 *
 * CALLER CONTRACT (the coordinator wires this into `renderPrefTurns`
 * in one place): for an OFFLINE fallback turn, render
 * `[...localisedFallbackLines(reply, t, locale), ...reply.lines.slice(2)]`
 * when this returns non-null, else `reply.lines` verbatim. The
 * return value replaces ONLY `lines[0..1]` — the trailing question
 * line (`lines[2]`, or absent on a WHY turn) is NOT this helper's:
 * another worker (D1) re-localises it from the stored
 * `next_question`, and this helper must never touch or drop it.
 * Model replies are NEVER passed the structured block by the
 * backend (only the fallback result carries it), and this helper
 * returns null for any reply with `ai_status === 'available'` —
 * model narration lines are never re-rendered or re-localised.
 * A reply without the block (old snapshots, model replies) returns
 * null, so the caller keeps the stored lines verbatim.
 */

export type PrefFallbackClimate = 'warm' | 'cool' | 'four_seasons' | 'mild';

export interface PrefFallbackEvidenceCity {
  city: string;
  climate: PrefFallbackClimate;
  count: number;
}

/** The reply fields this helper reads — a structural subset of
 * `PrefChatReply` (see `lib/chat.ts`), so the coordinator can pass
 * the stored reply as-is. */
export interface PrefFallbackReplyLike {
  lines?: string[];
  ai_status?: string | null;
  evidence_cities?: PrefFallbackEvidenceCity[] | null;
  climate_wanted?: PrefFallbackClimate | string | null;
  next_question?: string | null;
}

/** Translate with optional vars — the app's `tf` (see `useApp()`).
 * Plain lookups (`cityDisplayName`, `climateLabel`) call it with a
 * key only, so it is assignable to their `(k: string) => string`. */
export type PrefFallbackTranslate = (
  key: string,
  vars?: Record<string, string | number>,
) => string;

const CLIMATES: readonly string[] = ['warm', 'cool', 'four_seasons', 'mild'];

function isClimate(v: unknown): v is PrefFallbackClimate {
  return typeof v === 'string' && CLIMATES.includes(v);
}

function validItems(
  raw: PrefFallbackReplyLike['evidence_cities'],
): PrefFallbackEvidenceCity[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const items: PrefFallbackEvidenceCity[] = [];
  for (const it of raw) {
    if (!it || typeof it !== 'object') continue;
    const city = typeof it.city === 'string' ? it.city.trim() : '';
    if (!city) continue;
    if (!isClimate(it.climate)) continue;
    if (typeof it.count !== 'number' || !Number.isFinite(it.count)) continue;
    items.push({ city, climate: it.climate, count: it.count });
  }
  return items.length > 0 ? items : null;
}

export function localisedFallbackLines(
  reply: PrefFallbackReplyLike | null | undefined,
  t: PrefFallbackTranslate,
  locale: string,
): string[] | null {
  if (!reply || typeof reply !== 'object') return null;
  // Model narration is never re-rendered or re-localised.
  if (reply.ai_status === 'available') return null;
  const items = validItems(reply.evidence_cities);
  if (!items) return null;
  if (!Array.isArray(reply.lines) || reply.lines.length === 0) return null;

  const withCounts = joinList(
    items.map((it) =>
      t('wizard.prefFallbackCityItem', {
        city: cityDisplayName(it.city, t),
        climate: climateLabel(it.climate, t),
        count: it.count,
      }),
    ),
    locale,
  );
  const citiesLine = t('wizard.prefFallbackCitiesLine', { cities: withCounts });

  const wanted = isClimate(reply.climate_wanted) ? reply.climate_wanted : null;
  if (wanted && !items.some((it) => it.climate === wanted)) {
    // No-match: the cities (with their actual classes) first, then
    // the no-match + preference-only sentence — the same order and
    // wording as the guided opinion('climate') no-match branch.
    // `cities` here takes plain "City (class)" items, no counts.
    const plainDesc = joinList(
      items.map((it) =>
        parenNote(cityDisplayName(it.city, t), climateLabel(it.climate, t), locale),
      ),
      locale,
    );
    const noMatch = t('wizard.chatOpClimateNoMatch', {
      want: climateLabel(wanted, t),
      cities: plainDesc,
    });
    return [citiesLine, noMatch];
  }
  // Match (or no wanted class): only the cities line replaces the
  // stored prefix — the generic suggest line goes with it.
  return [citiesLine];
}

/**
 * Round 28 integration — the composed render lines for one stored
 * pref-chat reply bubble.
 *
 * `lines` are the BUBBLE lines from `prefTurnBubbles` (lib/chat.ts),
 * NOT the raw `reply.lines`: the D1 worker already moved the
 * trailing deterministic question line out of them into a separate
 * `question` bubble, so `lines.slice(2)` here drops exactly the
 * stored prefix lines (`lines[0..1]`, cities + generic suggest)
 * that `localisedFallbackLines` replaces — never the question line,
 * which renders separately via `t(ASK_KEY[...])`. The D2 helper's
 * docstring writes the contract against raw `reply.lines`
 * (`[...replacement, ...reply.lines.slice(2)]`); on raw lines that
 * would re-include the question — this function is the one place
 * the two halves compose, and it takes the bubble lines for that
 * reason. Returns `lines` verbatim for every case the helper
 * returns null (model replies, no structured block, old snapshots),
 * and for non-offline turns.
 */
export function localisedReplyLines(
  lines: string[],
  reply: PrefFallbackReplyLike | null | undefined,
  offline: boolean,
  t: PrefFallbackTranslate,
  locale: string,
): string[] {
  if (!offline) return lines;
  const replacement = localisedFallbackLines(reply, t, locale);
  if (!replacement) return lines;
  return [...replacement, ...lines.slice(2)];
}
