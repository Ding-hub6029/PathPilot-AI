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
  const fmt = (iso: string) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString(locale, { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <section className="mt-10" aria-labelledby="timeline-title">
      <p className="microcopy text-teal-dark">{t('home.timelineTitle')}</p>
      <h2 id="timeline-title" className="mt-1 text-2xl font-bold tracking-tight">{t('home.timelineTitle')}</h2>
      <p className="mt-2 text-sm text-navy/70">{t('home.timelineNote')}</p>

      <div className="perspective-1200 mt-5">
        <div className="tilt-panel anim-tilt-in rounded-3xl border border-navy/10 bg-white p-5 shadow-lg sm:p-6">
          {/* Horizontal track (desktop): amber NOW line + dated nodes */}
          <div className="relative hidden h-24 md:block" aria-hidden="true">
            <div className="absolute inset-x-0 top-1/2 h-px bg-navy/15" />
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-amber"
              style={{ insetInlineStart: `${nowPct}%` }}
            >
              <span className="absolute -top-1 start-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-amber ring-4 ring-amber/25 [dir=rtl]:translate-x-1/2" />
            </div>
            {NODES.map((n) => (
              <span key={n.id} className="absolute top-1/2 -translate-y-1/2" style={{ insetInlineStart: `${pct(n.date)}%` }}>
                <span className="block h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-navy shadow [dir=rtl]:translate-x-1/2" />
              </span>
            ))}
            <span
              className="microcopy absolute -bottom-1 -translate-x-1/2 text-amber-dark [dir=rtl]:translate-x-1/2"
              style={{ insetInlineStart: `${nowPct}%` }}
            >
              {t('home.timelineNow')}
            </span>
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

          {/* Vertical list for small screens: same data, no tilt */}
          <ul className="mt-4 space-y-3 md:hidden">
            {NODES.map((n) => (
              <li key={n.id} className="flex items-start gap-3 border-t border-navy/10 pt-3 text-sm">
                <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-navy" aria-hidden="true" />
                <span>
                  <span className="font-bold" dir="ltr">{fmt(n.date)}</span>
                  {' — '}{t(n.labelKey)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
