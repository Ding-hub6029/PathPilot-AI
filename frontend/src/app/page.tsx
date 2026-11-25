'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApp } from '../lib/store';
import { usePrograms } from '../lib/usePrograms';
import { sampleUndergrad, sampleMasters } from '../lib/types';
import { formatProgramLine } from '../lib/format';
import { displayProgramName } from '../lib/programs';
import { displayProgramInstitutionName } from '../lib/rankings';
import { WelcomeBanner } from '../components/WelcomeBanner';
import { TimelinePanel } from '../components/TimelinePanel';
import { CaseCard } from '../components/CaseCard';
import { NewsCard } from '../components/NewsCard';
import { ReviewCard } from '../components/ReviewCard';
import { FanCarousel } from '../components/FanCarousel';
import { ViewTransitionLink } from '../components/ViewTransitionLink';
import { vtRef } from '../lib/viewTransition';
import { SUCCESS_CASES } from '../lib/cases';
import { NEWS_ITEMS, POLICY_ITEMS } from '../lib/news';
import { SCHOOL_REVIEWS } from '../lib/reviews';

export default function HomePage() {
  const { t, locale, setProfile } = useApp();
  const { programs, live: programsLive, loading: programsLoading } = usePrograms();
  const router = useRouter();

  // No opening veil: the hero used to be covered by a solid navy veil on
  // the first visit of a session, which read as a black screen on open
  // (user feedback 2026-11-25). The hero keeps its line-mask/fade-up
  // entrances; nothing covers it anymore.

  const trySample = (which: 'ug' | 'pg') => {
    setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);
    router.push('/results');
  };

  return (
    <>
      <div className="mx-auto max-w-6xl px-4 py-8">
      {/* Welcome banner: in-flow at the top of the homepage, below the
          sticky nav and above the hero. In-flow (not fixed), so it never
          covers the nav or the hero. */}
      <WelcomeBanner />
      {/* Hero with compass-rose / route-line draw-in.
          12-column grid (research move 5): copy spans 7, the compass
          visual spans 5 — deliberate asymmetry instead of a 6/6 split. */}
      <section className="relative grid items-center gap-8 overflow-hidden rounded-3xl bg-navy p-8 text-white md:grid-cols-12">
        <div className="md:col-span-7">
          <p className="microcopy anim-fade-up text-amber">{t('tagline')}</p>
          <h1 className="hero-display line-mask mt-3"><span className="grad-amber-text" style={{ animationDelay: '.08s' }}>{t('home.heroTitle')}</span></h1>
          <p className="anim-fade-up stagger-2 mt-4 max-w-md text-white/85">{t('home.heroSub')}</p>
          <div className="anim-fade-up stagger-3 mt-6 flex flex-wrap gap-3">
            <Link href="/wizard" className="btn-press rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
            <button type="button" onClick={() => trySample('ug')} className="btn-press rounded-full border border-white/50 px-5 py-2.5 font-semibold">{t('home.ctaSample')}</button>
          </div>
          <p className="anim-fade-up stagger-4 mt-5 rounded-lg bg-white/10 p-3 text-sm text-white/90" role="note">{t('home.disclaimer')}</p>
          <p className="anim-fade-up stagger-4 mt-4 flex items-center justify-between gap-2">
            <span className="microcopy text-white/50" dir="ltr">NAVY · TEAL · AMBER</span>
            <span className="microcopy text-white/50">{t('home.heroKicker')}</span>
          </p>
        </div>
        <div aria-hidden="true" className="mx-auto w-full max-w-md md:col-span-5">
          <svg viewBox="0 0 400 260" className="w-full">
            <defs>
              <radialGradient id="sphereGrad" cx="35%" cy="30%" r="75%">
                <stop offset="0%" stopColor="#F7F5F0" />
                <stop offset="55%" stopColor="#0E7C7B" />
                <stop offset="100%" stopColor="#0B1F3A" />
              </radialGradient>
            </defs>
            <path className="anim-route" d="M30 220 C 110 200, 140 120, 200 110 S 320 60, 370 40" fill="none" stroke="#F2A541" strokeWidth="3" strokeLinecap="round" />
            <circle cx="30" cy="220" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="200" cy="110" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="370" cy="40" r="10" fill="#F2A541" stroke="#F7F5F0" strokeWidth="2" />
            {/* 3D compass sphere: orbit ring, concentric rings, gradient sphere, swaying needle */}
            <g>
              <circle className="anim-orbit" cx="330" cy="200" r="52" fill="none" stroke="#F7F5F0" strokeWidth="1.5" strokeDasharray="4 7" opacity=".55" />
              <circle cx="330" cy="200" r="42" fill="none" stroke="#F7F5F0" strokeWidth="1.5" opacity=".7" />
              <circle cx="330" cy="200" r="34" fill="url(#sphereGrad)" opacity=".95" />
              <g className="anim-needle">
                <path d="M330 172 L338 200 L330 228 L322 200 Z" fill="#F2A541" />
                <path d="M302 200 L330 192 L358 200 L330 208 Z" fill="#F7F5F0" opacity=".9" />
              </g>
              <circle cx="330" cy="200" r="3" fill="#F7F5F0" />
            </g>
          </svg>
        </div>
      </section>

      {/* Success cases first (user 2026-11-25): the homepage top shows
          real applicant-shared cases, not programme names — now as a
          3D fan carousel over all 55 cases (no stars: no rating data). */}
      <FanCarousel
        titleId="home-cases-title"
        title={t('home.casesTitle')}
        note={t('home.casesSub')}
        items={SUCCESS_CASES}
        renderCard={(c) => <CaseCard c={c} dark />}
        prevLabel={t('home.carouselPrev')}
        nextLabel={t('home.carouselNext')}
      />
      <p className="mt-4">
        <Link href="/cases" className="btn-press inline-block rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.casesViewAll')}</Link>
      </p>

      {/* Latest news & policy from verified official pages and feeds —
          same fan carousel; link-outs only, titles + one-line summaries. */}
      <FanCarousel
        titleId="home-news-title"
        title={t('home.newsTitle')}
        note={`${t('home.newsSub')} ${t('evidence.englishOnly')} · ${t('home.newsChecked')}`}
        items={[...NEWS_ITEMS, ...POLICY_ITEMS]}
        renderCard={(n) => <NewsCard n={n} />}
        prevLabel={t('home.carouselPrev')}
        nextLabel={t('home.carouselNext')}
      />

      {/* School reviews, same fan carousel. Hidden until the reviews
          data file lands (the mirror is an empty array meanwhile) —
          the section must never render an empty carousel. */}
      {SCHOOL_REVIEWS.length > 0 && (
        <FanCarousel
          titleId="home-reviews-title"
          title={t('home.reviewsTitle')}
          note={t('home.reviewsSub')}
          items={SCHOOL_REVIEWS}
          renderCard={(r) => <ReviewCard r={r} />}
          prevLabel={t('home.carouselPrev')}
          nextLabel={t('home.carouselNext')}
        />
      )}

      {/* How it works */}
      <section className="section-rule mt-10">
        <h2 className="line-mask text-2xl font-bold"><span>{t('home.howTitle')}</span></h2>
        <ol className="grid-12 mt-4">
          {[t('home.step1'), t('home.step2'), t('home.step3')].map((s, i) => (
            <li key={i} className={`card-lift anim-fade-up stagger-${i + 1} rounded-2xl border border-navy/10 bg-white p-5 card-surface md:col-span-4`}>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-teal font-bold text-white">{i + 1}</span>
              <p className="mt-3">{s}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Timeline (design upgrade 2026-11-25) */}
      <TimelinePanel />

      {/* Before / after as a static image (user testing 2026-11-25: the
          slider was pointless — "你做个图片就行了"). One SVG per locale,
          same copy as before, no programme facts stated. */}
      <section className="section-rule mt-10" aria-labelledby="ba-title">
        <p className="microcopy text-teal-dark">{t('home.beforeAfterTitle')}</p>
        <h2 id="ba-title" className="line-mask mt-1 text-2xl font-bold tracking-tight"><span>{t('home.beforeAfterTitle')}</span></h2>
        <img src={`/before-after-${locale}.svg`} alt={t('home.beforeAfterTitle')} className="mt-5 w-full rounded-3xl border border-navy/10 shadow-lg" />
      </section>

      {/* Programmes — fan-out stack (ref 1) with a verification ring per card.
          Moved below cases + news (user 2026-11-25); the 8 fully verified
          programmes stay here, with the eligibility check covering them.
          Header spans 8 of 12 columns; cards sit on the 12-column grid. */}
      <section className="section-rule mt-10">
        <div className="grid-12">
          <div className="md:col-span-8">
            <h2 className="line-mask text-2xl font-bold"><span>{t('home.programsTitle')}</span></h2>
            <p className="mt-1 text-sm text-navy/70">{t('home.browseSub')}</p>
          </div>
        </div>
        {programsLoading && <p className="mt-2 text-sm text-navy/60">{t('programs.loading')}</p>}
        {!programsLoading && !programsLive && <p className="mt-2 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="status">{t('programs.offlineNote')}</p>}
        <div className="grid-12 mt-4">
          {programs.map((p, i) => {
            // Verification ring: real official-source count, capped at 5 for
            // the ring scale; the number in the middle is the true count.
            const srcCount = p.sources.length;
            const frac = Math.min(srcCount, 5) / 5;
            const dash = 97.4 * (1 - frac);
            return (
            <article key={p.id} className={`card-lift anim-fan stagger-${(i % 4) + 1} rounded-2xl border border-navy/10 bg-white p-5 card-surface md:col-span-6`} style={{ '--fan-rot': `${((i % 4) - 1.5) * 1.2}deg` } as React.CSSProperties}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-teal">{displayProgramInstitutionName(p.institution, locale)} · {p.country}</p>
                  {/* Shared element (research move 4): this title morphs
                      into the programme detail header on navigation. */}
                  <h3 className="mt-1 text-lg font-bold" ref={vtRef(`program-title-${p.id}`)}>{displayProgramName(p, locale)}</h3>
                </div>
                <span className="flex shrink-0 flex-col items-center" aria-label={`${srcCount} ${t('program.sources')}`}>
                  <svg width="40" height="40" viewBox="0 0 36 36" aria-hidden="true">
                    <circle cx="18" cy="18" r="15.5" fill="none" stroke="#0B1F3A" strokeOpacity=".12" strokeWidth="4" />
                    <circle className="anim-ring" cx="18" cy="18" r="15.5" fill="none" stroke="#F2A541" strokeWidth="4" strokeLinecap="round" transform="rotate(-90 18 18)" style={{ '--ring-dash': dash } as React.CSSProperties} />
                    <text x="18" y="22" textAnchor="middle" fontSize="11" fontWeight="800" fill="#0B1F3A">{srcCount}</text>
                  </svg>
                  <span className="microcopy mt-0.5 text-navy/50">{t('program.sources')}</span>
                </span>
              </div>
              <p className="mt-2 text-sm text-navy/75">
                {formatProgramLine(p, t, locale)}
                {p.ucasCode ? ` · UCAS ${p.ucasCode}` : ''}
              </p>
              <div className="mt-4 flex gap-2">
                <ViewTransitionLink href={`/programs/${p.id}`} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('results.viewDetail')}</ViewTransitionLink>
                <button type="button" onClick={() => trySample(p.degreeLevel === 'undergraduate' ? 'ug' : 'pg')} className="btn-press rounded-full border border-navy/30 px-4 py-2 text-sm font-semibold">
                  {t('home.ctaSample')} · <span className="text-xs font-normal">({t('common.synthetic')})</span>
                </button>
              </div>
            </article>
            );
          })}
        </div>
        <p className="mt-3 text-sm text-navy/60">{t('home.sampleNote')}</p>
        <p className="mt-3">
          <Link href="/rankings" className="btn-press inline-block rounded-full border border-navy/30 bg-white px-5 py-2.5 font-semibold">{t('home.browseRankings')}</Link>
        </p>
      </section>
    </div>
    </>
  );
}
