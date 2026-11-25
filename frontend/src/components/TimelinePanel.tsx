'use client';
import { useApp } from '../lib/store';

/**
 * Application timeline (design upgrade 2026-11-25, ref 2 — tessel film):
 * a 3D-tilted panel with an amber "now" line and dated nodes along it;
 * node cards slide in one by one. Every date is a verified official fact
 * (UCAS 13 Jan 2027, TMUA second sitting 8 Jan 2027, UCL UPC close
 * 18 Jun 2027, 2027 intakes from Sep 2027 — see the Gaokao research file).
 * Positions are computed from real dates on a Dec 2026 → Oct 2027 scale,
 * so the amber NOW marker is always where today actually falls.
 * Logical positioning (insetInlineStart) keeps the line correct in RTL.
 *
 * Fix 2026-11-25 (user testing: "这个不应该是横着的吗？你竖着人家怎么看"):
 * the horizontal track now shows on ALL screen sizes — on phones it
 * scrolls horizontally (min-width 560px inside overflow-x-auto) instead
 * of collapsing into a vertical list, which is deleted. The old
 * below-the-line NOW label wrapped letter-by-letter and overlapped the
 * line on narrow screens; it is now a pill ABOVE the line, clamped to
 * 10–90% so it never clips, and the marker dot is clamped to 2–98%.
 */
const SCALE_START = new Date('2026-12-01T00:00:00Z').getTime();
const SCALE_END = new Date('2027-10-01T00:00:00Z').getTime();

const NODES = [
  { id: 'tmua', date: '2027-01-08', labelKey: 'home.timelineTmua' },
  { id: 'ucas', date: '2027-01-13', labelKey: 'home.timelineUcas' },
  { id: 'upc', date: '2027-06-18', labelKey: 'home.timelineUpc' },
  { id: 'intake', date: '2027-09-01', labelKey: 'home.timelineIntake' },
] as const;

function pct(iso: string): number {
  const t = new Date(`${iso}T00:00:00Z`).getTime();
  return Math.min(100, Math.max(0, ((t - SCALE_START) / (SCALE_END - SCALE_START)) * 100));
}

export function TimelinePanel() {
  const { t, locale } = useApp();
  const nowPct = pct(new Date().toISOString().slice(0, 10));
  // Clamp the visible marker/label so neither clips at the track edges
  // (today can fall outside the Dec 2026 → Oct 2027 scale).
  const markerPct = Math.min(98, Math.max(2, nowPct));
  const labelPct = Math.min(90, Math.max(10, nowPct));
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
            <div className="relative h-28 min-w-[560px]" aria-hidden="true">
              <span
                className="absolute top-0 -translate-x-1/2 whitespace-nowrap rounded-full bg-amber px-2.5 py-0.5 text-xs font-bold text-navy [dir=rtl]:translate-x-1/2"
                style={{ insetInlineStart: `${labelPct}%` }}
              >
                {t('home.timelineNow')}
              </span>
              <div className="absolute inset-x-0 top-1/2 h-px bg-navy/15" />
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-amber"
                style={{ insetInlineStart: `${markerPct}%` }}
              >
                <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber ring-4 ring-amber/25 [dir=rtl]:translate-x-1/2" />
              </div>
              {NODES.map((n) => (
                <span key={n.id} className="absolute top-1/2 -translate-y-1/2" style={{ insetInlineStart: `${pct(n.date)}%` }}>
                  <span className="block h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-navy shadow [dir=rtl]:translate-x-1/2" />
                </span>
              ))}
            </div>
          </div>

          {/* Node cards slide in one by one */}
          <ul className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {NODES.map((n, i) => (
              <li
                key={n.id}
                className={`anim-timeline-card stagger-${i + 1} rounded-2xl border border-navy/10 bg-paper p-4`}
              >
                <p className="microcopy text-teal-dark" dir="ltr">{fmt(n.date)}</p>
                <p className="mt-2 text-sm font-semibold leading-snug">{t(n.labelKey)}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
