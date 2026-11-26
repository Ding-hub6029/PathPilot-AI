'use client';
import { useMemo, useState } from 'react';
import { useApp } from '../lib/store';
import { MatchResponse, Profile, Program } from '../lib/types';
import { displayProgramName } from '../lib/programs';
import {
  candidateLabelKey, leverageCandidates, simulateMulti,
  type MultiSimulateResponse,
} from '../lib/simulate';

/**
 * Multi-change what-if simulation panel (Day 3).
 *
 * Toggles for the candidate changes the engine actually evaluates
 * (IELTS overall +0.5, IELTS Writing +0.5, budget +£10,000, budget
 * +£5,000 — no Gaokao toggle: no university publishes a Gaokao
 * equivalence). Apply runs one multi-simulate call and shows, per
 * scenario, the flip counts and the flipped programme names, the
 * top-lever answer, and the AI explanation.
 *
 * Reliability boundary (user constraint, all 6 locales): engine
 * numbers are shown in their own "verified numbers" box as verified
 * facts; the model/template narration sits beside them labelled as
 * the AI's reading, which may be wrong; suggestions are labelled as
 * suggestions. Unknown stays unknown.
 */
export function SimulatePanel({
  profile, programIds, programs, onScenario,
}: {
  profile: Profile;
  programIds: string[];
  programs: Program[];
  onScenario: (scenario: MatchResponse | null) => void;
}) {
  const { t, tf, locale } = useApp();
  const candidates = useMemo(() => leverageCandidates(profile), [profile]);
  const [selected, setSelected] = useState<string[]>(() => candidates.map((c) => c.id));
  const [result, setResult] = useState<MultiSimulateResponse | null>(null);
  const [activeScenario, setActiveScenario] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  // Candidates the profile cannot offer (e.g. no IELTS on file): shown
  // disabled with a reason, never silently hidden — the user sees what
  // the engine cannot evaluate for them.
  const allIds = ['ielts-overall-plus-0.5', 'ielts-writing-plus-0.5', 'budget-plus-10000', 'budget-plus-5000'];

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const run = async () => {
    const scenarios = candidates
      .filter((c) => selected.includes(c.id))
      .map((c) => ({ name: t(candidateLabelKey(c.id)), patch: c.patch }));
    if (!scenarios.length || !programIds.length) return;
    setLoading(true); setError(false);
    try {
      const res = await simulateMulti(profile, programIds, scenarios, { explain: true, locale });
      setResult(res);
      setActiveScenario(0);
      onScenario({ ...res.scenarios[0].scenario, live: true });
    } catch {
      setError(true);
    }
    setLoading(false);
  };

  const programName = (id: string) => {
    const p = programs.find((x) => x.id === id);
    return p ? displayProgramName(p, locale) : id;
  };

  const top = result?.leverage.top ?? null;

  return (
    <section className="mt-10 rounded-2xl border border-navy/10 bg-white p-6 shadow-sm" aria-labelledby="sim-multi-title">
      <h2 id="sim-multi-title" className="text-xl font-bold">{t('sim.multiTitle')}</h2>
      <p className="mt-1 text-sm text-navy/70">{t('sim.multiIntro')}</p>
      {/* Visible reliability boundary, on every render, in all locales. */}
      <p className="mt-3 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="note">{t('sim.boundary')}</p>

      {programIds.length === 0 ? (
        <p className="mt-4 text-sm text-navy/70">{t('sim.noProgrammes')}</p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2" role="group" aria-label={t('sim.multiTitle')}>
            {allIds.map((id) => {
              const cand = candidates.find((c) => c.id === id);
              const checked = selected.includes(id);
              return (
                <label key={id} className={`flex items-start gap-2 rounded-xl border p-3 text-sm ${cand ? 'border-navy/20 bg-white' : 'border-navy/10 bg-paper opacity-70'}`}>
                  <input type="checkbox" className="mt-0.5" checked={checked} disabled={!cand} onChange={() => toggle(id)} />
                  <span>
                    <span className="font-semibold">{t(candidateLabelKey(id))}</span>
                    {cand && (
                      <span className="block text-navy/60">
                        {cand.change.field === 'budget'
                          ? tf('sim.candidateChangeBudget', { from: cand.change.from, to: cand.change.to })
                          : tf('sim.candidateChangeScore', { from: cand.change.from, to: cand.change.to })}
                      </span>
                    )}
                    {!cand && <span className="block text-navy/60">{t('sim.candidateUnavailable')}</span>}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" onClick={run} disabled={loading || selected.length === 0}
              className="btn-press rounded-full bg-teal px-5 py-2 font-semibold text-white disabled:opacity-50">
              {loading ? t('sim.loading') : t('sim.applyMulti')}
            </button>
            <button type="button" onClick={() => { setResult(null); setSelected(candidates.map((c) => c.id)); onScenario(null); }}
              className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold">{t('sim.reset')}</button>
          </div>
          {selected.length === 0 && <p className="mt-2 text-sm text-navy/70">{t('sim.selectHint')}</p>}
          {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{t('sim.error')}</p>}
        </>
      )}

      {result && (
        <div className="mt-6 space-y-6">
          {/* Leverage: which single change helps most (engine numbers). */}
          <div>
            <h3 className="text-lg font-bold">{t('sim.leverageTitle')}</h3>
            {top ? (
              <p className="mt-1 text-sm">
                <strong>{t('sim.topLever')}: {t(candidateLabelKey(top.id))}</strong>
                {' — '}{tf('sim.flipsProgrammes', { count: top.flips })}
                {', '}{tf('sim.flipsRules', { count: top.rule_flips })}
                {top.flips_to_met === 0 && top.flips > 0 ? ` (${t('sim.notFullyMet')})` : ''}
              </p>
            ) : (
              <p className="mt-1 text-sm">{t('sim.noLever')}</p>
            )}
            <ul className="mt-2 space-y-1 text-sm text-navy/80">
              {result.leverage.all.map((c) => (
                <li key={c.id}>
                  {t(candidateLabelKey(c.id))}: {tf('sim.flipsProgrammes', { count: c.flips })}
                  {', '}{tf('sim.flipsRules', { count: c.rule_flips })}
                </li>
              ))}
            </ul>
          </div>

          {/* Per-scenario flips (verified engine numbers). */}
          <div>
            <h3 className="text-lg font-bold">{t('sim.verifiedNumbers')}</h3>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              {result.scenarios.map((scen, i) => (
                <article key={scen.name ?? i} className={`rounded-xl border p-4 ${i === activeScenario ? 'border-teal bg-teal/5' : 'border-navy/10 bg-paper'}`}>
                  <p className="font-bold">{scen.name}</p>
                  <p className="mt-1 text-sm">
                    {tf('sim.flipsProgrammes', { count: scen.flipped_program_ids.length })}
                    {', '}{tf('sim.flipsRules', { count: scen.rule_flip_count })}
                  </p>
                  {scen.flipped_program_ids.length > 0 ? (
                    <>
                      <p className="mt-2 text-sm font-semibold">{t('sim.flippedProgrammes')}:</p>
                      <ul className="list-disc ps-5 text-sm text-navy/80">
                        {scen.flipped_program_ids.map((id) => <li key={id}>{programName(id)}</li>)}
                      </ul>
                    </>
                  ) : (
                    <p className="mt-2 text-sm text-navy/70">{t('sim.noFlips')}</p>
                  )}
                  <button type="button" onClick={() => { setActiveScenario(i); onScenario({ ...scen.scenario, live: true }); }}
                    className="btn-press mt-3 rounded-full border border-navy/30 bg-white px-4 py-1.5 text-sm font-semibold">
                    {t('sim.viewInResults')}
                  </button>
                </article>
              ))}
            </div>
          </div>

          {/* Explanation: model/template words beside the engine numbers. */}
          <div>
            <h3 className="text-lg font-bold">{t('sim.explanationTitle')}</h3>
            <p className="mt-1 text-sm font-semibold text-navy/70">
              {result.explanation.source === 'model' ? t('sim.aiReading') : t('sim.templateReading')}
            </p>
            <p className="mt-2 whitespace-pre-line rounded-xl bg-paper p-4 text-sm text-navy/85">{result.explanation.text}</p>
            <p className="mt-2 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="note">{t('sim.boundary')}</p>
          </div>
        </div>
      )}
    </section>
  );
}
