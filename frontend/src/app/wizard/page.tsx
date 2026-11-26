'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../../lib/store';
import { usePrograms } from '../../lib/usePrograms';
import { evaluateLocal, matchProfile, mergePrograms } from '../../lib/api';
import { programMatchesField } from '../../lib/fields';
import { sortRecsByPreference } from '../../lib/preferences';
import { sampleUndergrad, sampleMasters, Profile, Curriculum, FieldId, MatchResult, Program } from '../../lib/types';
import { GaokaoPanel } from '../../components/GaokaoPanel';
import { PrefChat } from '../../components/PrefChat';
import { RecChat } from '../../components/RecChat';

// Flow (fixes 2026-11-25, user testing): field/direction FIRST, then
// conditions, then preferences, and only then recommendations. Programmes
// are never shown as a blind list: the system recommends from the
// catalogue filtered by the chosen field, ordered by the eligibility
// evaluation. The recommend step is a confirmation page — no selection
// wall: "查看我的结果" always works and the results page lists ALL
// matched programmes (targetProgramIds is synced to the full evaluated
// list, never a user-picked subset).
const STEPS = ['curriculum', 'track', 'field', 'academic', 'language', 'budget', 'preferences', 'recommend'] as const;

function NumField({ label, value, onChange, step = '0.1', min, max }: { label: string; value: number | '' | undefined; onChange: (v: number | '') => void; step?: string; min?: number; max?: number }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold">{label}</span>
      <input type="number" step={step} min={min} max={max} value={value ?? ''} inputMode="decimal"
        onChange={(e) => { const v = e.target.value; onChange(v === '' ? '' : Number(v)); }}
        className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2" />
    </label>
  );
}

export default function WizardPage() {
  const { t, locale, profile, setProfile, updateProfile } = useApp();
  const router = useRouter();
  const [step, setStep] = useState(0);
  // P0 (re-test task 6): the live programme refresh is deferred until
  // the preferences step. Steps 0-5 run no network at all: the local
  // mirror is complete (all 881 expansion programmes), so the
  // wizard's candidates never depended on the live call — but the
  // patient fetch (up to a 90s retry budget against a sleeping
  // backend) used to be in flight through the whole wizard, including
  // the window where the step-4 Next button was observed hanging.
  // Round 6: candidates come from the merged list (live v2 + the full
  // expansion mirror), so recommendations cover the 588 matchable
  // expansion programmes, not just the original 8.
  const { programs: livePrograms } = usePrograms({ enabled: step >= 6 });
  const programs = useMemo(() => mergePrograms(livePrograms), [livePrograms]);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  /**
   * P0 (re-test task 6) — the step advance is URGENT, not a
   * transition. Round 11 wrapped it in useTransition, and the
   * re-test showed the same hang: first click no response (30s),
   * second click no response (60s), third click advances at once.
   * Measured evidence (local node harness + curl, 2026-11-26):
   * allPrograms() 67ms, mergePrograms 2ms, evaluateLocal over the
   * full 369-programme UG set 89ms, backend /match 4ms local /
   * 0.8s live warm, Vercel pages + RSC payloads <1s warm — nothing
   * on this path takes seconds, so a deferred transition buys
   * nothing and is the only mechanism that can swallow clicks for
   * tens of seconds: while a transition is pending the button is
   * disabled, and a click landing on a disabled button is lost.
   * setStep now commits synchronously; `advancing` only guards
   * double-clicks and is cleared the moment the new step commits
   * (plus a 500ms safety timeout, so the button can never stick
   * disabled). Click/commit timings are logged ([p0-wizard]) for
   * the browser re-test to read.
   */
  const [advancing, setAdvancing] = useState(false);
  const advanceStartedRef = useRef(0);
  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (advancing) {
      if (typeof console !== 'undefined' && typeof console.debug === 'function') {
        console.debug(`[p0-wizard] step committed step=${step} in ${Date.now() - advanceStartedRef.current}ms`);
      }
      setAdvancing(false);
      if (advanceTimerRef.current) { clearTimeout(advanceTimerRef.current); advanceTimerRef.current = undefined; }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // Recommendation state (last step): evaluated matches for the chosen
  // field, ordered by eligibility. Read-only — the user never has to
  // pick from them to proceed.
  const [recs, setRecs] = useState<MatchResult[] | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  /** Round 8: the step-7 match is retrying while the backend wakes —
   * RecChat shows the waking line instead of a bare spinner. */
  const [recWaking, setRecWaking] = useState(false);

  const stepLabel = (i: number) =>
    i === 0 ? t('wizard.stepCurriculum') : i === 1 ? t('wizard.trackTitle') : i === 2 ? t('wizard.stepField') : i === 3 ? t('wizard.stepAcademic') : i === 4 ? t('wizard.stepLanguage') : i === 5 ? t('wizard.stepBudget') : i === 6 ? t('wizard.stepPreferences') : t('wizard.stepRecommend');

  // Only the first three steps gate on a choice (curriculum, degree type,
  // field). Academic / language / budget / preferences / recommend never
  // block: empty values are evaluated as UNKNOWN, preferences are all
  // optional, and the recommend step has no selection wall.
  const canNext = () => {
    if (step === 0) return !!profile.curriculum;
    if (step === 1) return profile.track !== '';
    if (step === 2) return !!profile.field;
    return true;
  };

  // A required-field error must vanish the moment the step becomes
  // completable (fix 2026-11-25: the old error stayed until the next
  // button press, so it looked like the filled field was still wrong —
  // that is what made "计划入学年份 2027" sit above a red "必填" box
  // that was really about the old programme-selection gate).
  useEffect(() => {
    if (error && canNext()) setError('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, step, error]);

  const next = () => {
    if (advancing) return;
    if (!canNext()) { setError(t('wizard.required')); return; }
    setError('');
    advanceStartedRef.current = Date.now();
    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug(`[p0-wizard] next click step=${step}`);
    }
    setAdvancing(true);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
    if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
    advanceTimerRef.current = setTimeout(() => setAdvancing(false), 500);
  };

  const back = () => {
    if (advancing) return;
    advanceStartedRef.current = Date.now();
    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug(`[p0-wizard] back click step=${step}`);
    }
    setAdvancing(true);
    setStep((s) => Math.max(0, s - 1));
    if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
    advanceTimerRef.current = setTimeout(() => setAdvancing(false), 500);
  };

  const finish = () => {
    // No selection wall: the results page lists ALL evaluated matches.
    // Sync targetProgramIds to the full evaluated list (or, if the
    // evaluation has not finished yet, to the field-filtered candidates).
    const ids = recs && recs.length > 0
      ? recs.map((r) => r.programId)
      : programs.filter((p) => p.degreeLevel === profile.track && p.matchable !== false && profile.field && programMatchesField(p, profile.field)).map((p) => p.id);
    updateProfile({ targetProgramIds: ids });
    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug(`[p0-nav] wizard finish click -> /results ids=${ids.length}`);
    }
    router.push('/results');
  };

  const loadSample = () => {
    const s = profile.track === 'taught_masters' ? sampleMasters : sampleUndergrad;
    setProfile({ ...s });
    setStep(7);
  };

  const exportProfile = () => {
    const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'pathpilot-profile.json'; a.click();
    URL.revokeObjectURL(url);
  };

  const importProfile = (f: File) => {
    const r = new FileReader();
    r.onload = () => {
      try { const p = JSON.parse(String(r.result)) as Profile; setProfile({ ...profile, ...p }); } catch { setError(t('common.error')); }
    };
    r.readAsText(f);
  };

  /** Picking a curriculum keeps only that branch's fields, so stale
   * values from another branch are never evaluated. */
  const selectCurriculum = (c: Curriculum) => {
    updateProfile({
      curriculum: c,
      alevels: c === 'uk_alevel' || c === 'sg_alevel' ? profile.alevels : '',
      mathsGrade: c === 'uk_alevel' || c === 'sg_alevel' ? profile.mathsGrade : '',
      gcseEnglish: c === 'uk_alevel' ? profile.gcseEnglish : '',
      gcseMaths: c === 'uk_alevel' ? profile.gcseMaths : '',
      ibTotal: c === 'ib' ? profile.ibTotal : '',
      ibHlMaths: c === 'ib' ? profile.ibHlMaths : '',
      ibHlTotal: c === 'ib' ? profile.ibHlTotal : '',
      gaokaoScore: c === 'cn_gaokao' ? profile.gaokaoScore : '',
      gaokaoTotal: c === 'cn_gaokao' ? profile.gaokaoTotal : '',
      gaokaoMaths: c === 'cn_gaokao' ? profile.gaokaoMaths : '',
      satTotal: c === 'usa' ? profile.satTotal : '',
      actComposite: c === 'usa' ? profile.actComposite : '',
      apGrades: c === 'usa' ? profile.apGrades : '',
    });
  };

  // Recommendations: when the user reaches the last step, evaluate the
  // field-filtered catalogue against the conditions already entered and
  // order preference-first (round 9, R1): the user's preferred
  // countries first, then eligibility (MET, then partly unknown, then
  // not met), then the preferred city, with climate conflicts last
  // (round 6: a cool preference must not surface Singapore first).
  // Eligibility-first used to bury the five verified Swiss UG
  // programmes below UCL / Imperial / Peking / Tsinghua / MIT for a
  // user whose stated first choice was Switzerland. No admission
  // probabilities anywhere — only MET / NOT_MET / UNKNOWN.
  // targetProgramIds is synced to the FULL evaluated list so the results
  // page shows every match without the user having to tick anything.
  useEffect(() => {
    if (step !== 7) return;
    const candidates = programs.filter((p) => p.degreeLevel === profile.track && p.matchable !== false && profile.field && programMatchesField(p, profile.field));
    if (candidates.length === 0) { setRecs([]); updateProfile({ targetProgramIds: [] }); return; }
    setRecLoading(true);
    setRecWaking(false);
    const ids = candidates.map((p) => p.id);
    const sortRecs = (rs: MatchResult[]) => sortRecsByPreference(rs, programs, profile);
    matchProfile({ ...profile, targetProgramIds: ids }, { onRetry: () => setRecWaking(true) })
      .then((res) => {
        const sorted = sortRecs(res.results);
        setRecs(sorted);
        updateProfile({ targetProgramIds: sorted.map((r) => r.programId) });
      })
      .catch(() => {
        const local = evaluateLocal(profile, ids);
        const sorted = sortRecs(local.results);
        setRecs(sorted);
        updateProfile({ targetProgramIds: sorted.map((r) => r.programId) });
      })
      .finally(() => { setRecLoading(false); setRecWaking(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const progress = ((step + 1) / STEPS.length) * 100;

  const curricula: { id: Curriculum; title: string; desc: string }[] = [
    { id: 'cn_gaokao', title: t('wizard.curriculumCnGaokao'), desc: t('wizard.curriculumCnGaokaoDesc') },
    { id: 'uk_alevel', title: t('wizard.curriculumUk'), desc: t('wizard.curriculumUkDesc') },
    { id: 'ib', title: t('wizard.curriculumIb'), desc: t('wizard.curriculumIbDesc') },
    { id: 'usa', title: t('wizard.curriculumUsa'), desc: t('wizard.curriculumUsaDesc') },
    { id: 'sg_alevel', title: t('wizard.curriculumSg'), desc: t('wizard.curriculumSgDesc') },
    { id: 'other', title: t('wizard.curriculumOther'), desc: t('wizard.curriculumOtherDesc') },
  ];

  const fields: { id: FieldId; title: string }[] = [
    { id: 'business', title: t('wizard.fieldBusiness') },
    { id: 'computing', title: t('wizard.fieldComputing') },
    { id: 'engineering', title: t('wizard.fieldEngineering') },
    { id: 'science', title: t('wizard.fieldScience') },
    { id: 'medicine', title: t('wizard.fieldMedicine') },
    { id: 'humanities', title: t('wizard.fieldHumanities') },
    { id: 'arts', title: t('wizard.fieldArts') },
  ];

  return (
    // Round 11, F1: the root div used to carry key={step}, so EVERY
    // step change unmounted and rebuilt the whole wizard — including
    // the usePrograms() effect, which re-fired the patient
    // fetchPrograms() (up to a 90s retry budget against a sleeping
    // backend) on every single step, and the Next button itself, so a
    // click landing mid-remount hit a detached node and was lost.
    // The page now stays mounted across steps; only the step content
    // below remounts (key={step} on its wrapper), and the nav buttons
    // never move. P0 (re-test task 6): that fix is live and the hang
    // persisted unchanged, so the remount was NOT the cause. The
    // advance also ran inside useTransition, which defers the update
    // and holds the button disabled while pending — the step advance
    // is now an urgent setStep (see `advancing` above), and the live
    // refresh is deferred until step 6, so no patient fetch runs
    // during steps 0-5 at all.
    <div className="page-enter mx-auto max-w-3xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('wizard.title')}</span></h1>

      {/* Animated progress route line with compass needle */}
      <div className="mt-4" aria-label={`${step + 1} / ${STEPS.length}`}>
        <div className="relative h-2 overflow-hidden rounded-full bg-navy/10">
          <div className="h-full rounded-full bg-teal transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {STEPS.map((_, i) => (
            <li key={i} className={i === step ? 'font-bold text-teal-dark' : i < step ? 'text-navy/70' : 'text-navy/45'}>
              {i + 1}. {stepLabel(i)}
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-6 rounded-2xl border border-navy/10 bg-white p-6 card-surface" aria-live="polite">
        {/* Only the step content remounts per step (entrance animation
            replays); the error line and nav buttons below stay mounted,
            so the Next button is never destroyed by the step change it
            just triggered (round 11, F1). */}
        <div key={step} className="anim-fade-up">
        {step === 0 && (
          <div>
            <h2 className="text-lg font-bold">{t('wizard.curriculumTitle')}</h2>
            <p className="mt-2 text-sm text-navy/70">{t('wizard.curriculumNote')}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {curricula.map((o) => (
                <button key={o.id} type="button" onClick={() => selectCurriculum(o.id)}
                  aria-pressed={profile.curriculum === o.id}
                  className={`btn-press card-lift rounded-2xl border-2 p-5 text-start ${profile.curriculum === o.id ? 'border-teal bg-teal/5' : 'border-navy/15'}`}>
                  <span className="text-lg font-bold">{o.title}</span>
                  <span className="mt-1 block text-sm text-navy/70">{o.desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 1 && (
          <div>
            <h2 className="text-lg font-bold">{t('wizard.trackHeading')}</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {([
                { track: 'undergraduate' as const, title: t('wizard.trackUndergrad'), desc: t('wizard.trackUndergradDesc') },
                { track: 'taught_masters' as const, title: t('wizard.trackMasters'), desc: t('wizard.trackMastersDesc') },
              ]).map((o) => (
                <button key={o.track} type="button" onClick={() => updateProfile({ track: o.track, targetProgramIds: [], budgetCurrency: o.track === 'undergraduate' ? 'GBP' : 'SGD' })}
                  aria-pressed={profile.track === o.track}
                  className={`btn-press card-lift rounded-2xl border-2 p-5 text-start ${profile.track === o.track ? 'border-teal bg-teal/5' : 'border-navy/15'}`}>
                  <span className="text-lg font-bold">{o.title}</span>
                  <span className="mt-1 block text-sm text-navy/70">{o.desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 className="text-lg font-bold">{t('wizard.fieldTitle')}</h2>
            <p className="mt-2 text-sm text-navy/70">{t('wizard.fieldNote')}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {fields.map((o) => (
                <button key={o.id} type="button" onClick={() => updateProfile({ field: o.id })}
                  aria-pressed={profile.field === o.id}
                  className={`btn-press card-lift rounded-2xl border-2 p-5 text-start ${profile.field === o.id ? 'border-teal bg-teal/5' : 'border-navy/15'}`}>
                  <span className="text-lg font-bold">{o.title}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">{t('wizard.stepAcademic')}</h2>
            {/* Round 9, R7: the planned intake year is collected here —
                before preferences and recommendations — so RecChat and
                the results page can show it and judge each programme's
                intake against it. It used to live only as a field
                underneath RecChat on the last step, so the wizard never
                asked for it and the "计划入学年份" line sat empty. */}
            <div className="max-w-xs">
              <NumField label={t('wizard.intakeYear')} value={profile.intakeYear} onChange={(v) => updateProfile({ intakeYear: v })} step="1" min={2026} max={2030} />
            </div>
            {profile.track === 'undergraduate' ? (
              <>
                {(profile.curriculum === 'uk_alevel' || profile.curriculum === 'sg_alevel') && (
                  <>
                    <label className="block"><span className="text-sm font-semibold">{t('wizard.alevelLabel')}</span>
                      <input value={profile.alevels ?? ''} onChange={(e) => updateProfile({ alevels: e.target.value })} placeholder="A*A*A" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                    <label className="block"><span className="text-sm font-semibold">{t('wizard.mathsLabel')}</span>
                      <input value={profile.mathsGrade ?? ''} onChange={(e) => updateProfile({ mathsGrade: e.target.value })} placeholder="A*" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                    {profile.curriculum === 'uk_alevel' && (
                      <>
                        <div className="grid gap-4 sm:grid-cols-2">
                          <label className="block"><span className="text-sm font-semibold">{t('wizard.gcseEnglish')}</span>
                            <input value={profile.gcseEnglish ?? ''} onChange={(e) => updateProfile({ gcseEnglish: e.target.value })} placeholder="C / 4" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                          <label className="block"><span className="text-sm font-semibold">{t('wizard.gcseMaths')}</span>
                            <input value={profile.gcseMaths ?? ''} onChange={(e) => updateProfile({ gcseMaths: e.target.value })} placeholder="C / 4" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                        </div>
                        <p className="text-sm text-navy/60">{t('wizard.gcseHint')}</p>
                      </>
                    )}
                    {profile.curriculum === 'sg_alevel' && <p className="text-sm text-navy/60">{t('wizard.sgNote')}</p>}
                  </>
                )}
                {profile.curriculum === 'ib' && (
                  <>
                    <p className="text-sm text-navy/60">{t('wizard.ibHint')}</p>
                    <div className="grid gap-4 sm:grid-cols-3">
                      <NumField label={t('wizard.ibTotal')} value={profile.ibTotal} onChange={(v) => updateProfile({ ibTotal: v })} step="1" min={0} max={45} />
                      <NumField label={t('wizard.ibHlMaths')} value={profile.ibHlMaths} onChange={(v) => updateProfile({ ibHlMaths: v })} step="1" min={1} max={7} />
                      <NumField label={t('wizard.ibHlTotal')} value={profile.ibHlTotal} onChange={(v) => updateProfile({ ibHlTotal: v })} step="1" min={0} max={21} />
                    </div>
                  </>
                )}
                {profile.curriculum === 'cn_gaokao' && (
                  <>
                    <div className="grid gap-4 sm:grid-cols-3">
                      <NumField label={t('wizard.gaokaoScore')} value={profile.gaokaoScore} onChange={(v) => updateProfile({ gaokaoScore: v })} step="1" min={0} max={750} />
                      <NumField label={t('wizard.gaokaoTotal')} value={profile.gaokaoTotal} onChange={(v) => updateProfile({ gaokaoTotal: v })} step="1" min={1} max={750} />
                      <NumField label={t('wizard.gaokaoMaths')} value={profile.gaokaoMaths} onChange={(v) => updateProfile({ gaokaoMaths: v })} step="1" min={0} max={150} />
                    </div>
                    <GaokaoPanel />
                  </>
                )}
                {profile.curriculum === 'usa' && (
                  <>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <NumField label={t('wizard.satTotal')} value={profile.satTotal} onChange={(v) => updateProfile({ satTotal: v })} step="10" min={400} max={1600} />
                      <NumField label={t('wizard.actComposite')} value={profile.actComposite} onChange={(v) => updateProfile({ actComposite: v })} step="1" min={1} max={36} />
                    </div>
                    <label className="block"><span className="text-sm font-semibold">{t('wizard.apGrades')}</span>
                      <input value={profile.apGrades ?? ''} onChange={(e) => updateProfile({ apGrades: e.target.value })} placeholder="5,5,5,4,4" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" />
                      <span className="text-xs text-navy/60">{t('wizard.apGradesHint')}</span></label>
                    <p className="text-sm text-navy/60">{t('wizard.usaNote')}</p>
                  </>
                )}
                {profile.curriculum === 'other' && <p className="text-sm text-navy/60">{t('wizard.otherNote')}</p>}
                {!profile.curriculum && <p className="text-sm text-navy/60">{t('wizard.curriculumMissing')}</p>}
              </>
            ) : (
              <>
                <label className="block"><span className="text-sm font-semibold">{t('wizard.degreeLabel')}</span>
                  <input value={profile.degree ?? ''} onChange={(e) => updateProfile({ degree: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" />
                  <span className="text-xs text-navy/60">{t('wizard.degreeHint')}</span></label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block"><span className="text-sm font-semibold">{t('wizard.degreeClass')}</span>
                    <select value={profile.degreeClass ?? ''} onChange={(e) => updateProfile({ degreeClass: (e.target.value || undefined) as Profile['degreeClass'] })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2">
                      <option value="">{t('wizard.selectPlaceholder')}</option>
                      <option value="first">{t('wizard.degreeClassFirst')}</option>
                      <option value="upper_second">{t('wizard.degreeClassUpperSecond')}</option>
                      <option value="lower_second">{t('wizard.degreeClassLowerSecond')}</option>
                      <option value="third">{t('wizard.degreeClassThird')}</option>
                      <option value="other">{t('wizard.degreeClassOther')}</option>
                    </select></label>
                  <label className="block"><span className="text-sm font-semibold">{t('wizard.mastersMathsGrade')}</span>
                    <input value={profile.mastersMathsGrade ?? ''} onChange={(e) => updateProfile({ mastersMathsGrade: e.target.value })} placeholder="A" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block"><span className="text-sm font-semibold">{t('wizard.graduationStatus')}</span>
                    <select value={profile.graduationStatus ?? ''} onChange={(e) => updateProfile({ graduationStatus: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2">
                      <option value="">{t('wizard.selectPlaceholder')}</option>
                      <option value="current">{t('wizard.graduationCurrent')}</option>
                      <option value="graduating">{t('wizard.graduationGraduating')}</option>
                      <option value="graduated">{t('wizard.graduationGraduated')}</option>
                    </select></label>
                  <NumField label={t('wizard.itExperienceYears')} value={profile.itExperienceYears} onChange={(v) => updateProfile({ itExperienceYears: v })} step="1" min={0} max={50} />
                </div>
              </>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">{t('wizard.stepLanguage')}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <NumField label={t('wizard.ieltsOverall')} value={profile.ieltsOverall} onChange={(v) => updateProfile({ ieltsOverall: v })} min={0} max={9} />
              <NumField label={t('wizard.ieltsListening')} value={profile.ieltsListening} onChange={(v) => updateProfile({ ieltsListening: v })} min={0} max={9} />
              <NumField label={t('wizard.ieltsReading')} value={profile.ieltsReading} onChange={(v) => updateProfile({ ieltsReading: v })} min={0} max={9} />
              <NumField label={t('wizard.ieltsWriting')} value={profile.ieltsWriting} onChange={(v) => updateProfile({ ieltsWriting: v })} min={0} max={9} />
              <NumField label={t('wizard.ieltsSpeaking')} value={profile.ieltsSpeaking} onChange={(v) => updateProfile({ ieltsSpeaking: v })} min={0} max={9} />
              <NumField label={t('wizard.toeflLabel')} value={profile.toefl} onChange={(v) => updateProfile({ toefl: v })} step="1" min={0} max={120} />
            </div>
            <p className="text-sm text-navy/60">{t('wizard.languageBothHint')}</p>
            <div className="max-w-xs">
              <label className="block"><span className="text-sm font-semibold">{t('wizard.testDate')}</span>
                <input type="date" value={profile.testDate ?? ''} onChange={(e) => updateProfile({ testDate: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2" /></label>
              <p className="mt-1 text-xs text-navy/60">{t('wizard.testDateHint')}</p>
            </div>
            {profile.track === 'taught_masters' && (
              <div className="grid gap-4 sm:grid-cols-3">
                <NumField label={t('wizard.greLabel')} value={profile.greTotal} onChange={(v) => updateProfile({ greTotal: v })} step="1" min={260} max={340} />
                <NumField label={t('wizard.greAwLabel')} value={profile.greAw} onChange={(v) => updateProfile({ greAw: v })} min={0} max={6} />
                <NumField label={t('wizard.gmatLabel')} value={profile.gmat} onChange={(v) => updateProfile({ gmat: v })} step="10" min={200} max={800} />
              </div>
            )}
          </div>
        )}

        {step === 5 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">{t('wizard.stepBudget')}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <NumField label={t('wizard.budgetLabel')} value={profile.budget} onChange={(v) => updateProfile({ budget: v })} step="1" min={0} />
              <label className="block"><span className="text-sm font-semibold">{t('wizard.budgetCurrency')}</span>
                <select value={profile.budgetCurrency ?? 'GBP'} onChange={(e) => updateProfile({ budgetCurrency: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2">
                  <option value="GBP">GBP</option><option value="SGD">SGD</option><option value="USD">USD</option>
                </select></label>
            </div>
            <label className="block max-w-xs"><span className="text-sm font-semibold">{t('wizard.residency')}</span>
              <select value={profile.residency ?? ''} onChange={(e) => updateProfile({ residency: (e.target.value || undefined) as Profile['residency'] })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2">
                <option value="">{t('wizard.residencySelect')}</option>
                <option value="uk">{t('wizard.residencyUk')}</option>
                <option value="overseas">{t('wizard.residencyOverseas')}</option>
                <option value="sg_citizen">{t('wizard.residencySgCitizen')}</option>
                <option value="sg_pr">{t('wizard.residencySgPr')}</option>
                <option value="sg_intl_asean">{t('wizard.residencySgIntlAsean')}</option>
                <option value="sg_intl_other">{t('wizard.residencySgIntlOther')}</option>
                <option value="sg_intl_nogrant">{t('wizard.residencySgIntlNogrant')}</option>
              </select></label>
            <p className="text-sm text-navy/60">{t('wizard.residencyFeeNote')}</p>
            <p className="text-sm text-navy/60">{t('wizard.budgetHint')}</p>
            {profile.sample && <p className="rounded-lg bg-amber/20 p-3 text-sm font-semibold">{t('common.synthetic')}</p>}
          </div>
        )}

        {step === 6 && (
          <PrefChat onDone={next} />
        )}

        {step === 7 && (
          <div>
            <RecChat
              recs={recs}
              recLoading={recLoading}
              recWaking={recWaking}
              programs={programs}
              onViewResults={finish}
              onEditPrefs={() => setStep(6)}
            />
            <div className="mt-4 max-w-xs">
              <NumField label={t('wizard.intakeYear')} value={profile.intakeYear} onChange={(v) => updateProfile({ intakeYear: v })} step="1" min={2026} max={2030} />
            </div>
          </div>
        )}
        </div>

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p>}

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <button type="button" onClick={back} disabled={step === 0 || advancing} className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold disabled:opacity-40">{t('wizard.back')}</button>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={loadSample} className="btn-press rounded-full border border-teal px-4 py-2 text-sm font-semibold text-teal-dark">{t('wizard.sampleProfile')}</button>
            {/* Chat steps (6 preferences, 7 recommend) drive their own
                forward navigation from inside the conversation — no
                duplicate Next / Finish button down here. */}
            {step < 6 && (
              step < STEPS.length - 1
                ? <button type="button" onClick={next} disabled={advancing} className="btn-press inline-flex items-center gap-2 rounded-full bg-navy px-5 py-2 font-semibold text-white disabled:opacity-60">
                    {advancing && (
                      <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity=".25" strokeWidth="4" />
                        <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
                      </svg>
                    )}
                    {t('wizard.next')}
                  </button>
                : <button type="button" onClick={finish} className="btn-press rounded-full bg-amber px-5 py-2 font-semibold text-navy">{t('wizard.finish')}</button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 text-sm">
        <button type="button" onClick={exportProfile} className="btn-press rounded-full border border-navy/25 bg-white px-4 py-2">{t('common.export')}</button>
        <button type="button" onClick={() => fileRef.current?.click()} className="btn-press rounded-full border border-navy/25 bg-white px-4 py-2">{t('common.import')}</button>
        <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) importProfile(f); }} />
      </div>
      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
