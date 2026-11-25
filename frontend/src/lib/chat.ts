/**
 * Shared helpers for the three model-wired chats (round 6, Job A):
 * the desktop pet (CompassPet), the preference chat (PrefChat) and the
 * recommend chat (RecChat).
 *
 * All three talk to the same two endpoints through the Next.js proxy
 * (frontend/next.config.js rewrites /api/:path* to the backend's
 * /api/v1/:path*):
 * - POST /assistant/chat — grounded free-text chat. ai_status is
 *   "available" ONLY when a validated model output was actually used;
 *   anything else is the template fallback and must NEVER be shown as
 *   an AI answer (see the honest-offline rule in each component).
 * - POST /profile/parse — free text -> StudentProfile-shaped dict.
 *   NEVER applies a profile; the caller applies only after the user
 *   confirms.
 *
 * No programme data, fee, requirement or opinion is invented here:
 * next-step links are derived from the reply's source ids (never from
 * model text), and the suggestion message is built only from the
 * user's own guided answers (degree, country, budget band).
 */

/** One /assistant/chat reply. */
export interface ChatReply {
  lines: string[];
  evidence_url?: string | null;
  ai_status?: string;
  model?: string | null;
  sources?: { id: string; url: string | null; title: string }[];
}

/** One /profile/parse reply (StudentProfile-shaped, parse only). */
export interface ParseReply {
  parsed_profile: Record<string, unknown>;
  unparsed: string[];
  confidence: Record<string, string>;
  confirmation_required: boolean;
  parser?: string;
  ai_status?: string;
  note?: string;
}

/** One history turn for /assistant/chat (max 6 are kept server-side). */
export interface ChatHistoryTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** True only when the backend actually used a validated model output
 * for this reply. Anything else (template fallback, or no status at
 * all) is offline content, never an AI answer. */
export function isModelReply(reply: ChatReply | null | undefined): boolean {
  return !!reply && reply.ai_status === 'available';
}

/**
 * Next-step links derived from a chat reply's source ids — never from
 * model text. Programme pages come from `src:<program-id>:` ids,
 * institution pages from `rank:` / `profile:` / `site:` ids (see
 * backend/ai/grounding.py for the id formats).
 */
export function deriveChatLinks(
  sources: ChatReply['sources'],
): { program?: string | null; institution?: string | null } {
  let program: string | null = null;
  let institution: string | null = null;
  for (const s of sources ?? []) {
    if (!program) {
      const m = /^src:([^:]+):/.exec(s.id);
      if (m) program = `/programs/${m[1]}`;
    }
    if (!institution) {
      const m = /^(?:rank|profile):[^:]+:(.+)$/.exec(s.id)
        ?? /^site:(.+)$/.exec(s.id);
      if (m) institution = `/institutions/${m[1]}`;
    }
    if (program && institution) break;
  }
  return { program, institution };
}

const QUESTION_MARKERS = [
  '?', '？', '吗', '么', '哪', '什么', '怎么', '为什么', '为何',
  '是否', '能不能', '可以吗', '有吗', '推荐', '建议', '怎样', '如何',
  '多久', '多少',
];
const QUESTION_WORDS_EN =
  /\b(what|which|how|why|when|where|is there|are there|any|recommend|suggest|do you|can you|could you|should i|would you)\b/i;

/**
 * True when free text is a question (or a request for a recommendation),
 * not an answer to the question being asked. A question goes to the
 * model; an answer goes to /profile/parse + the local mapping.
 */
export function looksLikeQuestion(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (QUESTION_MARKERS.some((m) => t.includes(m))) return true;
  return QUESTION_WORDS_EN.test(t);
}

export type DegreeLevel = 'undergraduate' | 'taught_masters';
export type BudgetBand = 'low' | 'mid' | 'high';

export interface BudgetCeiling {
  currency: string;
  amount: number;
  /** 'per year' for undergraduate bands, 'total' for taught-masters totals. */
  period: 'per year' | 'total';
}

/**
 * The guided 3-question flow's suggestion as one constructed message
 * for /assistant/chat: degree + country (English name for the model to
 * read, plus the explicit country-code marker the backend's retrieval
 * keys on) + budget band + ceiling when the band has one. Built only
 * from the user's own guided answers — no programme is named, so the
 * model suggests from the verified evidence the backend retrieves.
 */
export function suggestMessage(
  degree: DegreeLevel,
  countryCode: string,
  countryNameEn: string,
  band: BudgetBand,
  ceiling: BudgetCeiling | null,
): string {
  const level = degree === 'undergraduate' ? 'undergraduate' : 'taught masters';
  const base = `Recommend a ${level} programme in ${countryNameEn} ` +
    `(country code ${countryCode}). Budget band: ${band}.`;
  if (!ceiling) return base;
  return `${base} Budget: under ${ceiling.currency} ` +
    `${ceiling.amount.toLocaleString('en-US')} ${ceiling.period}.`;
}
