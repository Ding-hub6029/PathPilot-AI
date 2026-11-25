'use client';
import { useApp } from '../lib/store';

/**
 * Application timeline (design upgrade 2026-11-25, ref 2 — tessel film):
 * a 3D-tilted panel with an amber "now" line and dated nodes along it.
 * Every date is a verified official fact (UCAS 13 Jan 2027, TMUA second
 * sitting 8 Jan 2027, UCL UPC close 18 Jun 2027, 2027 intakes from
 * Sep 2027 — see the Gaokao research file). Positions are computed from
 * real dates on a Dec 2026 → Oct 2027 scale, so the amber NOW marker is
 * always where today actually falls. Logical positioning
 * (insetInlineStart) keeps the line correct in RTL.
 *
 * Fix 2026-11-25 (user testing: "这个不应该是横着的吗？你竖着人家怎么看"):
 * the horizontal track now shows on ALL screen sizes — on phones it
 * scrolls horizontally (min-width 560px inside overflow-x-auto) instead
 * of collapsing into a vertical list, which is deleted. The old
 * below-the-line NOW label wrapped letter-by-letter and overlapped the
 * line on narrow screens; it is now a pill ABOVE the line, clamped to
 * 10–90% so it never clips, and the marker dot is clamped to 2–98%.
 *
 * Fix 2026-11-25 (user testing: "这两个阶段的点是不是挨在一起了"):
 * TMUA (8 Jan 2027) and UCAS (13 Jan 2027) are only 5 days apart — 1.6%
 * of the 304-day scale, ~9px on the 560px track, less than the 14px dot
 * diameter — so the two dots were drawn on top of each other. The fix is
 * generic, not hardcoded to this pair: each node is a card + stem + dot
 * attached to the line in an above/below lane, and a greedy pass assigns
 * lanes so no two nodes on the same lane are closer than one card width
 * plus a gap (measured at the 560px minimum track width, so the rule also
 * holds on wider screens). Dates and text are never changed to make room
 * and close nodes are never merged — two different deadlines stay two
 * nodes. The dot of a staggered node sits 17px off the line with a short
 * stem connecting it back, so dots and cards never overlap or cover each
 * other. The NOW pill lives in a reserved 28px row at the top of the
 * track, above all cards, and its vertical line spans only the central
 * band (±28px around the line) instead of the full track height, so it
 * can never draw over a card when "today" falls near a node date; the
 * pill itself and the marker dot are unchanged.
 */
const SCALE_START = new Date('2026-12-01T00:00:00Z').getTime();
const SCALE_END = new Date('2027-10-01T00:00:00Z').getTime();

const NODES = [
  { id: 'tmua', date: '2027-01-08', labelKey: 'home.timelineTmua' },
  { id: 'ucas', date: '2027-01-13', labelKey: 'home.timelineUcas' },
  { id: 'upc', date: '2027-06-18', labelKey: 'home.timelineUpc' },
  { id: 'intake', date: '2027-09-01', labelKey: 'home.timelineIntake' },
] as const;

// Minimum centre-to-centre separation for two cards on the same lane:
// card width (144px, w-36) + 12px gap, measured at the track's minimum
// width (560px) so the rule also holds on wider screens.
const CARD_W_PX = 144;
const CARD_GAP_PX = 12;
const TRACK_MIN_W_PX = 560;
const SAME_LANE_MIN_GAP_PCT = ((CARD_W_PX + CARD_GAP_PX) / TRACK_MIN_W_PX) * 100;

function pct(iso: string): number {
  const t = new Date(`${iso}T00:00:00Z`).getTime();
  return Math.min(100, Math.max(0, ((t - SCALE_START) / (SCALE_END - SCALE_START)) * 100));
}

/**
 * Generic lane assignment: lane 0 = above the line, 1 = below. Nodes are
 * processed in date order; a node takes the first lane whose previous
 * node is at least SAME_LANE_MIN_GAP_PCT away. A node that fits neither
 * lane takes the lane whose nearest neighbour is farthest (best effort —
 * with the current dates this never happens: TMUA/UPC above, UCAS/intake
 * below).
 */
function assignLanes(pcts: number[]): number[] {
  const order = pcts.map((_, i) => i).sort((a, b) => pcts[a] - pcts[b]);
  const lanes = new Array<number>(pcts.length).fill(0);
  const last: (number | undefined)[] = [];
  for (const i of order) {
    let lane = 0;
    while (last[lane] !== undefined && pcts[i] - pcts[last[lane] as number] < SAME_LANE_MIN_GAP_PCT) {
      lane += 1;
    }
    if (lane > 1) {
      const gap = (l: number) => (last[l] === undefined ? Infinity : pcts[i] - pcts[last[l] as number]);
      lane = gap(0) >= gap(1) ? 0 : 1;
    }
    lanes[i] = lane;
    last[lane] = i;
  }
  return lanes;
}

export function TimelinePanel() {
  const { t, locale } = useApp();
  const nowPct = pct(new Date().toISOString().slice(0, 10));
  // Clamp the visible marker/label so neither clips at the track edges
  // (today can fall outside the Dec 2026 → Oct 2027 scale).
  const markerPct = Math.min(98, Math.max(2, nowPct));
  const labelPct = Math.min(90, Math.max(10, nowPct));
  const nodePcts = NODES.map((n) => pct(n.date));
  const lanes = assignLanes(nodePcts);
  const fmt = (iso: string) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString(locale, { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <section className="section-rule mt-10" aria-labelledby="timeline-title">
      <p className="microcopy text-teal-dark">{t('home.timelineTitle')}</p>
      <h2 id="timeline-title" className="line-mask mt-1 text-2xl font-bold tracking-tight"><span>{t('home.timelineTitle')}</span></h2>
      <p className="mt-2 text-sm text-navy/70">{t('home.timelineNote')}</p>

      <div className="perspective-1200 mt-5">
        <div className="tilt-panel anim-tilt-in rounded-3xl border border-navy/10 bg-white p-5 shadow-lg sm:p-6">
          {/* Horizontal track on every screen size; scrolls sideways on phones. */}
          <div className="overflow-x-auto">
            <div className="relative h-[360px] min-w-[560px]">
              {/* NOW pill — reserved 28px row at the top, above all cards. */}
              <span
                className="absolute top-0 -translate-x-1/2 whitespace-nowrap rounded-full bg-amber px-2.5 py-0.5 text-xs font-bold text-navy [dir=rtl]:translate-x-1/2"
                style={{ insetInlineStart: `${labelPct}%` }}
              >
                {t('home.timelineNow')}
              </span>
              {/* Horizontal line at the centre. */}
              <div className="absolute inset-x-0 top-1/2 h-px bg-navy/15" aria-hidden="true" />
              {/* NOW vertical marker: central band only (±28px around the
                  line) so it can never draw over a card; dot sits on the
                  line. Pill and dot unchanged. */}
              <div
                className="absolute top-[calc(50%-28px)] h-14 w-0.5 bg-amber"
                style={{ insetInlineStart: `${markerPct}%` }}
                aria-hidden="true"
              >
                <span className="absolute top-1/2 left-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber ring-4 ring-amber/25 [dir=rtl]:translate-x-1/2" />
              </div>
              {NODES.map((n, i) => {
                const p = nodePcts[i];
                const above = lanes[i] === 0;
                // The card extends toward the centre of the track so it
                // never clips at the edges: flex-start/flex-end are
                // direction-aware, so the same rule works in RTL.
                const cardAlign = p < 50 ? 'flex-start' : 'flex-end';
                const card = (
                  <article
                    className={`anim-timeline-card stagger-${i + 1} w-36 shrink-0 rounded-2xl border border-navy/10 bg-paper p-3`}
                    style={{ alignSelf: cardAlign }}
                  >
                    <p className="microcopy text-teal-dark" dir="ltr">{fmt(n.date)}</p>
                    <p className="mt-1.5 line-clamp-3 text-sm font-semibold leading-snug">{t(n.labelKey)}</p>
                  </article>
                );
                const dot = (
                  <span className="block h-3.5 w-3.5 shrink-0 self-center rounded-full border-2 border-white bg-navy shadow" aria-hidden="true" />
                );
                const stem = (
                  <span className="min-h-1.5 w-px flex-1 self-center bg-navy/25" aria-hidden="true" />
                );
                const connector = (
                  <span className="h-2.5 w-px shrink-0 self-center bg-navy/25" aria-hidden="true" />
                );
                return (
                  <div
                    key={n.id}
                    className={`absolute flex w-0 flex-col ${above ? 'top-7 bottom-1/2 justify-end' : 'top-1/2 bottom-0 justify-start'}`}
                    style={{ insetInlineStart: `${p}%` }}
                  >
                    {above ? (
                      <>
                        {card}
                        {stem}
                        {dot}
                        {connector}
                      </>
                    ) : (
                      <>
                        {connector}
                        {dot}
                        {stem}
                        {card}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
