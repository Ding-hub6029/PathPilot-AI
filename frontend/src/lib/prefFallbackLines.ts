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
 * the stored reply as-is. `climate_turn` rides along for the
 * scoping mapping in `PrefChat.tsx` (the backend's marker for the
 * climate turn, Round 29 W2); this helper itself never reads it —
 * `hasFallbackCitiesBlock` keys on the evidence block only. */
export interface PrefFallbackReplyLike {
  lines?: string[];
  ai_status?: string | null;
  evidence_cities?: PrefFallbackEvidenceCity[] | null;
  climate_wanted?: PrefFallbackClimate | string | null;
  next_question?: string | null;
  climate_turn?: boolean;
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

/** Round 29 E3: does this reply carry the structured cities block
 * (so localisedFallbackLines will produce a re-localised cities
 * line for it)? The same gate localisedFallbackLines applies —
 * model replies (ai_status 'available') never carry it, and a
 * reply without valid items or without lines does not either.
 * Exported so PrefChat can tell, per turn, whether the turn's
 * lines[0] IS the cities line (the scoping rule in
 * scopeCitiesLines keys on exactly that). */
export function hasFallbackCitiesBlock(
  reply: PrefFallbackReplyLike | null | undefined,
): boolean {
  if (!reply || typeof reply !== 'object') return false;
  if (reply.ai_status === 'available') return false;
  if (!validItems(reply.evidence_cities)) return false;
  return Array.isArray(reply.lines) && reply.lines.length > 0;
}

// --- Round 29 E1: known offline-template lines ----------------------
// THE DEFECT (re-test 23 item a): the six guidance answers
// (environment, city, afterGrad, salary, pressure, teaching) came
// back as the backend offline template's generic unknown pair and
// stayed in the REQUEST locale after a switch — verbatim, 6 times:
// "这个我从已核实的数据里查不到，不知道。可以开始资格检查，逐项核对你的背景。"
// The source is backend/ai/assistant.py `_STRINGS` "unknown" +
// "unknown_2" (returned as the template's two lines by
// `assistant_ask` / `_fallback_result` in ai/pref_chat.py when the
// gateway is down and nothing matched). The cities line already had
// a structured re-render (D2 above); the unknown pair had none.
//
// THE FIX: a reverse map from the exact stored template line, in
// any of the 6 locales, to its frontend locale key — the same
// render-time mechanism as the confirmed notes (R28 D1). The
// strings below are copied VERBATIM from backend/ai/assistant.py
// (no translation invented); tests/test_r29_w1.py re-derives them
// from that file and fails on any drift. "unknown" has no frontend
// key, so Round 29 adds `wizard.prefFallbackUnknown` in all 6
// locales (same backend wording); "unknown_2" reuses the existing
// `pet.suggestUnknown2`, whose 6 values are already byte-identical
// to the backend's in every locale. Only these two fixed template
// lines map — every other line (model narration, a country line,
// free text, a fee line with a programme name) stays verbatim.
// A model reply is NEVER passed through this map (localisedReplyLines
// vetoes ai_status 'available'); only offline turns re-localise.

/** Frontend locale key -> the backend template line in every locale. */
const TEMPLATE_LINE_FORMS: Record<string, Record<string, string>> = {
  'wizard.prefFallbackUnknown': {
    en: "I can't find that in the verified data, so I don't know.",
    'zh-CN': '这个我从已核实的数据里查不到，不知道。',
    es: 'No lo encuentro en los datos verificados; no lo sé.',
    fr: 'Je ne trouve pas cela dans les données vérifiées ; je ne sais pas.',
    'pt-BR': 'Não encontro isso nos dados verificados; não sei.',
    ar: 'لا أجد ذلك في البيانات الموثّقة؛ لا أعرف.',
  },
  'pet.suggestUnknown2': {
    en: 'Start the eligibility check to go through your background rule by rule.',
    'zh-CN': '可以开始资格检查，逐项核对你的背景。',
    es: 'Inicia la comprobación de requisitos para revisar tu perfil regla por regla.',
    fr: "Lancez la vérification d'éligibilité pour revoir votre profil règle par règle.",
    'pt-BR': 'Inicie a verificação de elegibilidade para revisar seu perfil regra por regra.',
    ar: 'ابدأ فحص الأهلية لمراجعة ملفك قاعدةً قاعدة.',
  },
};

/** Lower-cased stored line -> frontend locale key. */
const TEMPLATE_LINE_REVERSE: Record<string, string> = Object.fromEntries(
  Object.entries(TEMPLATE_LINE_FORMS).flatMap(([key, forms]) =>
    Object.values(forms).map((form) => [form.toLowerCase(), key])),
);

/** Lower-cased JOINED pair (unknown + unknown_2 concatenated in one
 * locale, exactly as the re-test quoted it) -> both keys, in order.
 * A stored turn normally carries the pair as two lines; the joined
 * form is defence in depth for a snapshot that stored them as one. */
const JOINED_TEMPLATE_LINES: Record<string, [string, string]> = Object.fromEntries(
  (['en', 'zh-CN', 'es', 'fr', 'pt-BR', 'ar'] as const).map((loc) => [
    (TEMPLATE_LINE_FORMS['wizard.prefFallbackUnknown'][loc]
      + TEMPLATE_LINE_FORMS['pet.suggestUnknown2'][loc]).toLowerCase(),
    ['wizard.prefFallbackUnknown', 'pet.suggestUnknown2'] as [string, string],
  ]),
);

/** Re-localise known offline-template lines in the current locale,
 * one stored line at a time. A line that exactly equals a known
 * template form (any locale) renders through its key; a line that
 * exactly equals a joined unknown pair splits into the two keys;
 * anything else returns verbatim. Pure; never touches model
 * narration — the caller gates on ai_status first. */
export function localiseTemplateLines(
  lines: string[],
  t: PrefFallbackTranslate,
): string[] {
  const out: string[] = [];
  for (const line of lines) {
    const joined = JOINED_TEMPLATE_LINES[line.trim().toLowerCase()];
    if (joined) {
      out.push(t(joined[0]), t(joined[1]));
      continue;
    }
    const key = TEMPLATE_LINE_REVERSE[line.trim().toLowerCase()];
    out.push(key ? t(key) : line);
  }
  return out;
}

/** Round 29 E3: drop exact-duplicate lines within one turn, keeping
 * the first occurrence. A backend-appended sentence that repeats a
 * line the frontend already rendered (e.g. the cities line appended
 * behind the structured replacement) never renders twice in one
 * turn. Pure; a non-empty input always returns a non-empty output. */
export function dedupeTemplateLines(lines: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of lines) {
    if (seen.has(line)) continue;
    seen.add(line);
    out.push(line);
  }
  return out;
}

/** Round 29 E3 — conversation-wide cities-line scoping (see
 * scopeCitiesLines below). One turn's already-localised reply
 * lines, plus whether its lines[0] is the re-localised cities line
 * and whether the turn answered the climate question. */
export interface PrefTurnLinesForScope {
  lines: string[];
  /** True when this turn's lines[0] is the re-localised cities line
   * (its reply carries the structured evidence block). */
  carriesCitiesLine: boolean;
  /** True when this turn's extraction recorded a climate value —
   * this turn IS the climate turn, where the cities line belongs. */
  answeredClimate: boolean;
}

/**
 * Round 29 E3: the cities line appears ONCE per conversation, on
 * the climate turn. Re-test 23 round 1 showed it verbatim twice —
 * the countries turn AND the climate turn — because the backend
 * places it whenever climate is the next question as well as when
 * the turn answers climate. The fix is render-side, over the whole
 * turn list at once: the first carrier turn that answered climate
 * keeps its cities line (lines[0]); every other carrier drops
 * lines[0]. When no carrier answered climate (the climate question
 * is still open), the first carrier keeps it — the line must appear
 * somewhere. Non-carriers and model turns pass through untouched
 * (a model reply never carries the block, so it can never be a
 * carrier). A carrier left with no lines still renders its offline
 * line + question bubble in the component, so dropping never
 * produces a bare empty bubble. Pure.
 *
 * Contract with the backend (Worker 2, in parallel): backend lines
 * are authoritative — Worker 2 appends the missing deterministic
 * sentences and the cities line to the reply lines and attaches the
 * structured evidence_cities/climate_wanted block. This function
 * only suppresses the FRONTEND's re-rendered cities line on
 * non-climate carriers; it never invents, edits or re-orders a
 * backend sentence, and within-turn duplicates are already removed
 * by dedupeTemplateLines in localisedReplyLines before this runs.
 */
export function scopeCitiesLines(turns: PrefTurnLinesForScope[]): string[][] {
  let keepIndex = -1;
  for (let i = 0; i < turns.length; i++) {
    if (turns[i].carriesCitiesLine && turns[i].answeredClimate) {
      keepIndex = i;
      break;
    }
  }
  if (keepIndex === -1) {
    for (let i = 0; i < turns.length; i++) {
      if (turns[i].carriesCitiesLine) {
        keepIndex = i;
        break;
      }
    }
  }
  return turns.map((turn, i) => {
    if (!turn.carriesCitiesLine || i === keepIndex) return [...turn.lines];
    return turn.lines.slice(1);
  });
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
 * reason.
 *
 * Round 29 E1: when there is no cities replacement (model replies
 * aside — those return verbatim below), the composed lines still
 * pass through localiseTemplateLines: a stored offline-template
 * line (the generic unknown pair) re-localises in the current
 * locale, while every other line stays verbatim. The tail
 * (`lines.slice(2)`) gets the same treatment, so a backend-appended
 * template sentence behind the replacement localises too.
 * Round 29 E3: the result passes through dedupeTemplateLines, so
 * an identical line never renders twice in one turn.
 * Returns `lines` verbatim for non-offline turns and for any reply
 * whose ai_status is 'available' (model narration is never
 * re-rendered or re-localised — trust over translation, decided).
 */
export function localisedReplyLines(
  lines: string[],
  reply: PrefFallbackReplyLike | null | undefined,
  offline: boolean,
  t: PrefFallbackTranslate,
  locale: string,
): string[] {
  if (!offline) return lines;
  if (reply?.ai_status === 'available') return lines;
  const replacement = localisedFallbackLines(reply, t, locale);
  const composed = replacement ? [...replacement, ...lines.slice(2)] : lines;
  return dedupeTemplateLines(localiseTemplateLines(composed, t));
}
