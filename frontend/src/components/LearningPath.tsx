'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';

/**
 * LearningPath — the homepage "How it works" section as a learning
 * journey (design upgrade, Worker C). It replaces the old 3-card list
 * (the coordinator swaps it in — see the insertion snippet in the
 * round report); the section heading and all copy come from existing
 * locale keys only, no new copy.
 *
 * Framing: each step is something the user LEARNS, not a form to fill —
 * the step title (home.step1/2/3) plus its explainer line
 * (home.step1Learn/2Learn/3Learn) underneath. A route line links the
 * three numbered nodes to a final affordance node (the wizard CTA):
 * on md+ screens the nodes sit on a rail and the line draws itself
 * (reused global .anim-route, pathLength 600) when the section scrolls
 * into view (IntersectionObserver, once); on phones the rail is hidden
 * and the numbers live inside the cards, as before. The line is
 * direction-neutral geometry flipped in RTL (rtl: variant), and the
 * final node's arrow flips the same way — the path always runs
 * inline-start → inline-end.
 *
 * Entrance reuses the existing .line-mask heading reveal, .anim-fade-up
 * and stagger-1..4 classes. Keyboard-safe: the final node is a real
 * <Link> to /wizard; the numbered nodes are plain spans, not buttons.
 */

const STEPS = [
  { title: 'home.step1', learn: 'home.step1Learn' },
  { title: 'home.step2', learn: 'home.step2Learn' },
  { title: 'home.step3', learn: 'home.step3Learn' },
] as const;

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="rtl:-scale-x-100">
      <path d="M4 12h14M13 6l6 6-6 6" fill="none" stroke="#0B1F3A" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function LearningPath() {
  const { t } = useApp();
  const sectionRef = useRef<HTMLElement>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold: 0.25 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section ref={sectionRef} className="section-rule mt-10" aria-labelledby="how-title">
      <h2 id="how-title" className="line-mask text-2xl font-bold"><span>{t('home.howTitle')}</span></h2>

      {/* Node rail (md+ only): the numbered nodes sit on the route line,
          each with a paper ring so the line reads as passing behind
          them; the final node is the wizard link. On phones the rail is
          hidden and the numbers live inside the cards below. */}
      <div className="relative mt-6 hidden md:block">
        <svg
          className="pointer-events-none absolute inset-x-0 top-[17px] h-[3px] w-full rtl:-scale-x-100"
          viewBox="0 0 600 4"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M0 2 H600"
            pathLength={600}
            fill="none"
            stroke="#0E7C7B"
            strokeOpacity="0.35"
            strokeWidth="3"
            strokeLinecap="round"
            style={inView ? undefined : { strokeDasharray: 600, strokeDashoffset: 600 }}
            className={inView ? 'anim-route' : undefined}
          />
        </svg>
        <div className="grid-12 relative">
          {STEPS.map((s, i) => (
            <div key={s.title} className="md:col-span-3">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-teal font-bold text-white ring-4 ring-paper">
                {i + 1}
              </span>
            </div>
          ))}
          <div className="md:col-span-3">
            <Link
              href="/wizard"
              aria-label={t('home.ctaWizard')}
              className="btn-press inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber text-navy ring-4 ring-paper"
            >
              <ArrowIcon />
            </Link>
          </div>
        </div>
      </div>

      <ol className="grid-12 mt-4">
        {STEPS.map((s, i) => (
          <li
            key={s.title}
            className={`card-lift anim-fade-up stagger-${i + 1} rounded-2xl border border-navy/10 bg-white p-5 card-surface md:col-span-3`}
          >
            {/* Number badge: inside the card on phones; on md+ the rail
                above carries the numbers, so this one hides. */}
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-teal font-bold text-white md:hidden">
              {i + 1}
            </span>
            <p className="mt-3 font-semibold md:mt-0">{t(s.title)}</p>
            <p className="mt-1 text-sm text-navy/70">{t(s.learn)}</p>
          </li>
        ))}
        <li className="anim-fade-up stagger-4 md:col-span-3">
          <Link
            href="/wizard"
            className="btn-press card-lift flex h-full min-h-[7rem] flex-col justify-between rounded-2xl bg-amber p-5 text-navy card-surface"
          >
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-white/70">
              <ArrowIcon />
            </span>
            <span className="mt-3 font-bold">{t('home.ctaWizard')}</span>
          </Link>
        </li>
      </ol>
    </section>
  );
}
