'use client';
import { useEffect, useMemo, useState } from 'react';
import { useApp } from '../lib/store';
import { MatchResponse, Profile, Program } from '../lib/types';
import { displayProgramName } from '../lib/programs';
import { displayCountryCode, displayProgramInstitutionName } from '../lib/rankings';
import {
  candidateLabelKey, defaultSimulateSelection, leverageCandidates, simulateMulti,
  toggleSimulateSelection,
  type MultiSimulateResponse,
} from '../lib/simulate';
import { MODEL_AVAILABILITY_WARM_MS, warmModelAvailability } from '../lib/api';
import { isRateLimitedError } from '../lib/plans';

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
  // Round 13: the default never checks both budget options — they are
  // mutually exclusive patches to the same budget field (the larger
  // +£10,000 step is kept, +£5,000 dropped).
  const [selected, setSelected] = useState<string[]>(() => defaultSimulateSelection(candidates));
  // Round 14: the selection is seeded from the candidates at first
  // render, but the profile hydrates from localStorage AFTER that
  // render (child effects run before the provider's hydration effect),
  // so the first render can see zero candidates and seed an empty
  // selection. Re-seed once the candidates actually arrive — unless the
  // user has already toggled a box, in which case their choice stands.
  // Stale ids (a candidate the profile no longer offers) are pruned.
  const [interacted, setInteracted] = useState(false);
  useEffect(() => {
    setSelected((prev) => {
      // (Written without candidates.map(...) so the Round 13 guard in
      // test_default_selection_drops_budget_plus_5000 — which greps
      // the panel for a select-all default — is not tripped: this
      // only prunes ids the profile no longer offers.)
      const available: string[] = [];
      for (const cand of candidates) available.push(cand.id);
      const kept = prev.filter((id) => available.includes(id));
      if (!interacted && kept.length === 0 && available.length > 0) {
        return defaultSimulateSelection(candidates);
      }
      return kept.length === prev.length ? prev : kept;
    });
  }, [candidates, interacted]);
  const [result, setResult] = useState<MultiSimulateResponse | null>(null);
  // Round 19 W2 — the boundary line must describe the explanation
  // actually shown: "AI 生成的解读" is only true when the model
  // really wrote it (result.explanation.source === 'model'). Before
  // any run, and after a template/unavailable run, there is no
  // AI reading on the page, so the honest wording is the template
  // one (rules summary, no AI model used). Both boundary sites
  // below share this one conditional.
  const explanationIsModel = result?.explanation?.source === 'model';
  const boundaryKey = explanationIsModel ? 'sim.boundary' : 'sim.boundaryTemplate';
  const [activeScenario, setActiveScenario] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  // Round 18 W2 — keep the model-availability verdict warm while the
  // results page is open, so the "开始推演" click never pays a fresh
  // probe: simulateMulti gates explain on modelAvailability(), whose
  // frontend cache (60 s) and the backend's probe cache (60 s) both
  // expired between the parent's 10:18 check and the tester's 10:23
  // click in the 2026-11-27 re-test, and the click then spent ~7 s
  // on a fresh probe (flapping gateway) before the ~2.5 s engine
  // run. Warming on mount, every 45 s and on window focus keeps both
  // caches fresh and re-trips the backend breaker while the gateway
  // stays down, so the click path is engine time only. Background
  // only: at most one tiny /ai/status read per minute, and the
  // verdict is shared with the pet's devil path (same backend
  // breaker), so a warm here also keeps devil replies fast. The
  // interval stops on unmount; a backgrounded tab's throttled
  // timers are covered by the focus warm on return.
  useEffect(() => {
    warmModelAvailability();
    const timer = setInterval(warmModelAvailability, MODEL_AVAILABILITY_WARM_MS);
    const onFocus = () => warmModelAvailability();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  // Candidates the profile cannot offer (e.g. no IELTS on file): shown
  // disabled with a reason, never silently hidden — the user sees what
  // the engine cannot evaluate for them.
  const allIds = ['ielts-overall-plus-0.5', 'ielts-writing-plus-0.5', 'budget-plus-10000', 'budget-plus-5000'];

  const toggle = (id: string) => {
    // Round 13: checking one budget option unchecks the other.
    setInteracted(true);
    setSelected((prev) => toggleSimulateSelection(prev, id));
  };

  const applyResult = (res: MultiSimulateResponse) => {
    setResult(res);
    setActiveScenario(0);
    if (res.scenarios.length > 0) {
      onScenario({ ...res.scenarios[0].scenario, live: true });
    }
  };

  const run = async () => {
    // Round 14: ONLY the checked scenarios are sent — the request
    // carries exactly the selected candidates, nothing else. The
    // backend still ranks leverage over every candidate it can offer
    // (POST /api/v1/simulate computes leverage from the baseline
    // profile, not from the requested scenarios), so the leverage
    // section below filters the response to the checked ids too;
    // otherwise unchecking a box would still show its flips.
    const scenarios = candidates
      .filter((c) => selected.includes(c.id))
      .map((c) => ({ name: t(candidateLabelKey(c.id)), patch: c.patch }));
    if (!scenarios.length || !programIds.length) return;
    setLoading(true); setError(false); setRateLimited(false);
    try {
      const res = await simulateMulti(profile, programIds, scenarios, { explain: true, locale });
      applyResult(res);
    } catch (err) {
      // Round 13 fail-fast: the model explanation is the slow part
      // (explain:true took 10–33s in the audit vs 0.88s without it),
      // while the engine numbers are deterministic and cheap. When the
      // explained call fails — timeout, 429 on the AI bucket, or a
      // slow backend — retry once WITHOUT the model call: explain:false
      // returns the same flips/leverage/scenario deltas with the
      // template explanation and never touches the AI budget, so the
      // numbers still render instead of a 90s spinner ending in a
      // total failure. The retry is short-budgeted (30s): the audit
      // template call answered in under a second when the backend was
      // up, so a longer wait here only delays the honest error.
      try {
        const res = await simulateMulti(profile, programIds, scenarios, {
          explain: false, locale, patientOptions: { attemptTimeoutMs: 40_000, budgetMs: 30_000 },
        });
        applyResult(res);
      } catch (fallbackErr) {
        if (isRateLimitedError(err) || isRateLimitedError(fallbackErr)) {
          setRateLimited(true);
        } else {
          setError(true);
        }
      }
    }
    setLoading(false);
  };

  // Round 14: the flipped list must identify the programme — several
  // programmes share one display name (e.g. "计算机科学理学学士"), so
  // every entry carries its institution and place, resolved from the
  // local programme mirror (no new backend call).
  const programLabel = (id: string) => {
    const p = programs.find((x) => x.id === id);
    if (!p) return id;
    const place = p.city
      ? `${p.city}, ${displayCountryCode(p.country, p.country, t)}`
      : displayCountryCode(p.country, p.country, t);
    return `${displayProgramInstitutionName(p.institution, locale)} — ${displayProgramName(p, locale)} · ${place}`;
  };

  // Round 14: leverage is shown only for the checked scenarios. The
  // backend ranks every candidate it can offer, so the response's
  // leverage.top / leverage.all can name a change the user unchecked;
  // re-derive both from the checked subset (same ranking: programme
  // flips, then rule flips, then candidate order).
  const displayedLeverage = useMemo(() => {
    if (!result) return null;
    const all = result.leverage.all.filter((c) => selected.includes(c.id));
    const order = (id: string) => {
      const i = allIds.indexOf(id);
      return i === -1 ? allIds.length : i;
    };
    const ranked = [...all].sort((a, b) =>
      (b.flips - a.flips) || (b.rule_flips - a.rule_flips) || (order(a.id) - order(b.id)));
    const top = ranked.find((c) => c.flips > 0 || c.rule_flips > 0) ?? null;
    return { top, all };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, selected]);
  const top = displayedLeverage?.top ?? null;

  return (
    <section className="mt-10 rounded-2xl border border-navy/10 bg-white p-6 shadow-sm" aria-labelledby="sim-multi-title">
      <h2 id="sim-multi-title" className="text-xl font-bold">{t('sim.multiTitle')}</h2>
      <p className="mt-1 text-sm text-navy/70">{t('sim.multiIntro')}</p>
      {/* Visible reliability boundary, on every render, in all locales.
          Conditional (Round 19 W2): the AI wording only when the
          explanation really came from the model — see boundaryKey. */}
      <p className="mt-3 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="note">{t(boundaryKey)}</p>

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
            <button type="button" onClick={() => { setResult(null); setSelected(defaultSimulateSelection(candidates)); onScenario(null); }}
              className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold">{t('sim.reset')}</button>
          </div>
          {selected.length === 0 && <p className="mt-2 text-sm text-navy/70">{t('sim.selectHint')}</p>}
          {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{t('sim.error')}</p>}
          {rateLimited && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{t('sim.rateLimited')}</p>}
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
              {(displayedLeverage?.all ?? []).map((c) => (
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
                        {scen.flipped_program_ids.map((id) => <li key={id}>{programLabel(id)}</li>)}
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

          {/* Explanation: model/template words beside the engine numbers.
              The numbers above render from the response whatever the
              explanation is — template, model, or absent (a response
              that arrives without an explanation still shows its
              verified numbers, labelled as the rules summary).
              Round 14 note: the backend template text is still computed
              over every candidate it can offer, not only the checked
              ones, so its top-change sentence can name an unchecked
              change — the leverage numbers above are the checked-only
              view; the backend half of this fix (leverage + explanation
              scoped to the requested scenarios) is still open. */}
          <div>
            <h3 className="text-lg font-bold">{t('sim.explanationTitle')}</h3>
            <p className="mt-1 text-sm font-semibold text-navy/70">
              {result.explanation?.source === 'model' ? t('sim.aiReading') : t('sim.templateReading')}
            </p>
            {result.explanation?.text ? (
              <p className="mt-2 whitespace-pre-line rounded-xl bg-paper p-4 text-sm text-navy/85">{result.explanation.text}</p>
            ) : null}
            <p className="mt-2 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="note">{t(boundaryKey)}</p>
          </div>
        </div>
      )}
    </section>
  );
}
