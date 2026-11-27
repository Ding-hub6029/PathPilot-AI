'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApp } from '../../../lib/store';
import { findProgram, matchProfile, resolveProgramId } from '../../../lib/api';
import { MatchResponse } from '../../../lib/types';
import { RuleRow } from '../../../components/RuleRow';
import { PlanPanel } from '../../../components/PlanPanel';
import { AiEntry } from '../../../components/AiEntry';
import { RankingCards } from '../../../components/RankingCards';
import { PROGRAM_RULES, ruleExpected } from '../../../lib/ruleText';
import { formatDuration, formatFeeItems, formatIntake } from '../../../lib/format';
import { institutionIdForProgram, displayCountryCode, displayProgramInstitutionName } from '../../../lib/rankings';
import { displayProgramName } from '../../../lib/programs';
import { suppressNextRouteEnter, vtRef } from '../../../lib/viewTransition';

export default function ProgramDetail({ params }: { params: { id: string } }) {
  const { t, tf, locale, profile } = useApp();
  const router = useRouter();
  const f = { t, tf, locale };
  // Round 6: resolve from the merged local list (v2 + expansion mirror),
  // so expansion programme pages render instead of the error state.
  // Round 13: an alias slug (e.g. eth-zurich-bsc-computer-science)
  // resolves to its canonical programme; the URL is then replaced
  // with the canonical id so the old link ends on the real page.
  const canonicalId = resolveProgramId(params.id);
  const [data, setData] = useState<MatchResponse | null>(null);
  const program = findProgram(params.id);
  // Round 14, locale flash: the store's locale starts as English and
  // only switches to the saved locale once its hydration effect runs
  // (after first paint), so a direct open briefly renders English UI
  // and then switches to Chinese. Same fix as the welcome banner:
  // render nothing locale-dependent until the client has mounted — the
  // server render is the same neutral placeholder, and by the time
  // this effect fires the provider's hydration effect has run in the
  // same commit, so the first localised paint is already in the saved
  // locale. A real browser flash check still needs the parent (no
  // browser in this task).
  const [ready, setReady] = useState(false);
  useEffect(() => { setReady(true); }, []);

  useEffect(() => {
    if (canonicalId !== params.id) {
      // Round 14, alias blank: RouteTransition remounts on every
      // pathname change and its quiet .3s fade starts at opacity 0, so
      // the replace to the canonical URL blanked the (already rendered)
      // page for a beat. Suppress this one entrance — the canonical
      // content is already on screen via findProgram's alias
      // resolution, so the URL is corrected with no fade and no blank.
      // (In dev StrictMode the one-shot flag can be consumed by a
      // discarded render and the entrance may play once; production
      // renders once.)
      suppressNextRouteEnter();
      router.replace(`/programs/${canonicalId}`);
    }
  }, [params.id, canonicalId, router]);

  // Round 13: the match used to depend only on params.id, so on a
  // direct visit / refresh it ran BEFORE the store hydrated the saved
  // profile from localStorage (child effects run before the provider's
  // hydration effect) — profile.track was '' so the effect returned
  // early, and never re-ran. It now depends on the profile too, so
  // the check runs once the saved profile is in.
  useEffect(() => {
    if (!program || !profile.track) return;
    matchProfile({ ...profile, targetProgramIds: [program.id] }).then(setData).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id, profile]);

  if (!ready) {
    // Neutral placeholder: no locale-dependent text, so the server
    // render and the first client paint can never show English copy
    // before the saved locale is applied.
    return (
      <div className="mx-auto max-w-4xl px-4 py-8" aria-hidden="true">
        <div className="h-9 w-40 animate-pulse rounded-full bg-navy/10" />
        <div className="mt-6 h-10 w-3/4 animate-pulse rounded-xl bg-navy/10" />
        <div className="mt-4 h-24 animate-pulse rounded-2xl bg-navy/10" />
      </div>
    );
  }
  if (!program) {
    return <div className="mx-auto max-w-3xl px-4 py-12"><p>{t('common.error')}</p><Link href="/" className="text-teal-dark underline">{t('program.back')}</Link></div>;
  }
  const result = data?.results.find((r) => r.programId === program.id);
  const minimumRuleIds = PROGRAM_RULES[program.id] ?? [];
  const rankingInstitutionId = institutionIdForProgram(program.institution);

  // AI visibility layer (W5): "why does this fit me — or not?"
  // The question carries the explicit programme-id marker (the
  // backend's programme-id intent) plus the saved profile's Gaokao /
  // IELTS / budget when present — each clause omitted when the
  // profile does not hold it, never invented.
  const profileParts: string[] = [];
  if (typeof profile.gaokaoScore === 'number' && typeof profile.gaokaoTotal === 'number') {
    profileParts.push(`Gaokao ${profile.gaokaoScore} out of ${profile.gaokaoTotal}`);
  }
  if (typeof profile.ieltsOverall === 'number') {
    profileParts.push(`IELTS ${profile.ieltsOverall} overall`);
  }
  if (typeof profile.budget === 'number') {
    profileParts.push(`budget ${profile.budgetCurrency || 'GBP'} ${profile.budget.toLocaleString('en-US')} per year`);
  }
  // Round 13: whether a saved profile exists at all (the same
  // localStorage pp-profile the wizard/pet use, hydrated into the
  // store). With one, the section below shows the user's situation
  // against the minimums; the "开始资格检查" call-to-action is only
  // for visitors with no profile at all.
  const hasSavedProfile = !!profile.track
    || typeof profile.gaokaoScore === 'number'
    || typeof profile.ieltsOverall === 'number'
    || typeof profile.budget === 'number'
    || !!profile.degree;
  const situationLines: string[] = [];
  if (typeof profile.gaokaoScore === 'number' && typeof profile.gaokaoTotal === 'number') {
    situationLines.push(`${t('wizard.gaokaoScore')}: ${profile.gaokaoScore} / ${profile.gaokaoTotal}`);
  }
  if (typeof profile.ieltsOverall === 'number') {
    situationLines.push(`${t('wizard.ieltsOverall')}: ${profile.ieltsOverall}`);
  }
  if (typeof profile.budget === 'number') {
    situationLines.push(`${t('wizard.budgetLabel')}: ${profile.budgetCurrency || 'GBP'} ${profile.budget.toLocaleString('en-US')}`);
  }
  const programQuestion = `Programme id ${program.id}. ${profileParts.length ? `I have ${profileParts.join(', ')}.` : ''} What is the fee and IELTS requirement for this programme, and is it a good fit for me?`;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/" className="btn-press inline-block rounded-full border border-navy/25 bg-white px-4 py-2 text-sm font-semibold">← {t('program.back')}</Link>
      {/* Editorial magazine header (design upgrade 2026-11-25, ref 1):
          giant title, microcopy kicker. No facts changed. */}
      <p className="microcopy mt-6 text-teal-dark">{t('program.editorialKicker')}</p>
      {/* Shared element (research move 4): the programme title morphs
          here from the card / institution-list title. */}
      <h1 ref={vtRef(`program-title-${program.id}`)} className="line-mask mt-2 text-4xl font-extrabold leading-[1.05] tracking-tight md:text-5xl"><span>{displayProgramInstitutionName(program.institution, locale)} — {displayProgramName(program, locale)}</span></h1>
      <p className="mt-3 text-navy/70">{displayCountryCode(program.country, program.country, t)} · {formatIntake(program, t)} · {formatDuration(program, t, locale)}</p>
      <div className="mt-4 grid gap-3 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm sm:grid-cols-3">
        <div><p className="text-sm font-semibold text-navy/60">{t('program.fee')}</p><p className="font-bold">{formatFeeItems(program, t, locale)}</p></div>
        <div><p className="text-sm font-semibold text-navy/60">{t('program.duration')}</p><p className="font-bold">{formatDuration(program, t, locale)}</p></div>
        <div><p className="text-sm font-semibold text-navy/60">{t('program.intake')}</p><p className="font-bold">{formatIntake(program, t)}</p></div>
      </div>

      {/* AI visibility layer (W5): the grounded chat explains why
          this programme fits the saved profile — or does not. */}
      <div className="mt-4">
        <AiEntry label={t('aivis.programme')} question={programQuestion} programId={program.id} />
      </div>

      <section className="mt-8" aria-labelledby="req-title">
        <h2 id="req-title" className="text-xl font-bold">{t('program.requirements')}</h2>
        {result?.trackMismatch && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 font-semibold text-red-800">{t('results.trackMismatch')}</p>}
        {result && !result.trackMismatch && (
          <ul className="mt-4 space-y-3">
            {result.ruleResults.map((rule) => (
              <li key={rule.ruleId} className="card-lift rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
                <RuleRow program={program} rule={rule} />
              </li>
            ))}
          </ul>
        )}
        {!result && (
          <div className="mt-4 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
            {hasSavedProfile ? (
              <>
                {/* Your situation from the saved profile, against the
                    minimums below — the live rule check is still
                    loading or unavailable, so this is the saved
                    profile's own numbers, never a verdict. */}
                <p className="text-sm font-bold">{t('results.yourSituation')}</p>
                {situationLines.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-sm">
                    {situationLines.map((line) => (<li key={line}>{line}</li>))}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-navy/70">{t('program.minimumsNote')}</p>
                )}
              </>
            ) : (
              <p className="text-sm font-semibold text-navy/70">{t('program.minimumsNote')}</p>
            )}
            <ul className="mt-3 space-y-2">
              {minimumRuleIds.map((ruleId) => (
                <li key={ruleId} className="border-t border-navy/5 pt-2 text-sm">
                  <span className="font-semibold">{ruleExpected({ ruleId, status: 'UNKNOWN', observed: '', expected: '', evidenceIds: [], reasonCode: '' }, f)}</span>
                </li>
              ))}
            </ul>
            {hasSavedProfile ? (
              <Link href="/results" className="btn-press mt-5 inline-block rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('wizard.finish')}</Link>
            ) : (
              <Link href="/wizard" className="btn-press mt-5 inline-block rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
            )}
          </div>
        )}
      </section>

      {/* Improvement plan (Day 3, FR13/FR14; W3 expansion fix): the
          first frontend surface for plans. Works for v2 and matchable
          expansion programmes; display-only programmes get an honest
          note inside the panel instead of a generated plan. */}
      <section className="mt-8" aria-labelledby="plan-title">
        <h2 id="plan-title" className="text-xl font-bold">{t('plan.title')}</h2>
        <PlanPanel programId={program.id} matchable={program.matchable} />
      </section>

      {rankingInstitutionId && (
        <section className="mt-8" aria-labelledby="rank-title">
          <h2 id="rank-title" className="text-xl font-bold">{t('rankings.viewRankings')}</h2>
          <p className="mt-1 text-sm text-navy/70">{t('rankings.rankingsNote')}</p>
          <div className="mt-3">
            <RankingCards institutionId={rankingInstitutionId} />
          </div>
        </section>
      )}

      <section className="mt-8" aria-labelledby="src-title">
        <h2 id="src-title" className="text-xl font-bold">{t('program.sources')}</h2>
        <ul className="mt-3 space-y-2">
          {program.sources.map((s) => (
            <li key={s.id} className="rounded-lg border border-navy/10 bg-white p-3 text-sm">
              <a href={s.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{s.label}</a>
              <span className="ms-2 text-navy/60">· {t('program.sourceVerified')} {s.verifiedDate} · {t('evidence.intakeApplies')}: {s.appliesTo || formatIntake(program, t)}</span>
              {s.excerpt && <p className="mt-1 italic text-navy/75" lang="en" dir="ltr">“{s.excerpt}” <span className="not-italic text-xs font-semibold text-navy/60">— {t('evidence.englishOnly')}</span></p>}
            </li>
          ))}
        </ul>
      </section>
      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
