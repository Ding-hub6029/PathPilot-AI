'use client';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../../lib/store';
import { PROGRAMS } from '../../lib/programs';
import { sampleUndergrad, sampleMasters, Profile } from '../../lib/types';

const STEPS = ['track', 'target', 'academic', 'language', 'budget'] as const;

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
  const { t, profile, setProfile, updateProfile } = useApp();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const stepLabel = (i: number) =>
    i === 0 ? t('wizard.trackTitle') : i === 1 ? t('wizard.stepTarget') : i === 2 ? t('wizard.stepAcademic') : i === 3 ? t('wizard.stepLanguage') : t('wizard.stepBudget');

  const canNext = () => {
    if (step === 0) return profile.track !== '';
    if (step === 1) return profile.targetProgramIds.length > 0;
    return true;
  };

  const next = () => {
    if (!canNext()) { setError(t('wizard.required')); return; }
    setError('');
    if (step === 1 && profile.targetProgramIds.length === 0) {
      const ids = PROGRAMS.filter((p) => p.degreeLevel === profile.track).map((p) => p.id);
      updateProfile({ targetProgramIds: ids });
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const finish = () => router.push('/results');

  const loadSample = () => {
    const s = profile.track === 'taught_masters' ? sampleMasters : sampleUndergrad;
    setProfile({ ...s });
    setStep(4);
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

  const trackPrograms = PROGRAMS.filter((p) => p.degreeLevel === profile.track);
  const progress = ((step + 1) / STEPS.length) * 100;

  return (
    <div className="page-enter mx-auto max-w-3xl px-4 py-8" key={step}>
      <h1 className="text-2xl font-bold">{t('wizard.title')}</h1>

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

      <div className="anim-fade-up mt-6 rounded-2xl border border-navy/10 bg-white p-6 shadow-sm" aria-live="polite">
        {step === 0 && (
          <div>
            <h2 className="text-lg font-bold">{t('wizard.trackTitle')}</h2>
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

        {step === 1 && (
          <div>
            <h2 className="text-lg font-bold">{t('wizard.targetLabel')}</h2>
            <div className="mt-4 space-y-3">
              {trackPrograms.map((p) => {
                const on = profile.targetProgramIds.includes(p.id);
                return (
                  <button key={p.id} type="button" aria-pressed={on} onClick={() => updateProfile({ targetProgramIds: on ? profile.targetProgramIds.filter((x) => x !== p.id) : [...profile.targetProgramIds, p.id] })}
                    className={`btn-press block w-full rounded-2xl border-2 p-4 text-start ${on ? 'border-teal bg-teal/5' : 'border-navy/15'}`}>
                    <span className="font-bold">{p.institution} — {p.officialName}</span>
                    <span className="block text-sm text-navy/70">{p.intakeLabel} · {p.feeItems.map((f) => `${f.currency} ${f.amount.toLocaleString()} ${f.period}`).join(', ')}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">{t('wizard.stepAcademic')}</h2>
            {profile.track === 'undergraduate' ? (
              <>
                <label className="block"><span className="text-sm font-semibold">{t('wizard.alevelLabel')}</span>
                  <input value={profile.alevels ?? ''} onChange={(e) => updateProfile({ alevels: e.target.value })} placeholder="A*A*A" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
                <label className="block"><span className="text-sm font-semibold">{t('wizard.mathsLabel')}</span>
                  <input value={profile.mathsGrade ?? ''} onChange={(e) => updateProfile({ mathsGrade: e.target.value })} placeholder="A*" className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
              </>
            ) : (
              <label className="block"><span className="text-sm font-semibold">{t('wizard.degreeLabel')}</span>
                <input value={profile.degree ?? ''} onChange={(e) => updateProfile({ degree: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" />
                <span className="text-xs text-navy/60">{t('wizard.degreeHint')}</span></label>
            )}
          </div>
        )}

        {step === 3 && (
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
            {profile.track === 'taught_masters' && (
              <div className="grid gap-4 sm:grid-cols-3">
                <NumField label={t('wizard.greLabel')} value={profile.greTotal} onChange={(v) => updateProfile({ greTotal: v })} step="1" min={260} max={340} />
                <NumField label={t('wizard.greAwLabel')} value={profile.greAw} onChange={(v) => updateProfile({ greAw: v })} min={0} max={6} />
                <NumField label={t('wizard.gmatLabel')} value={profile.gmat} onChange={(v) => updateProfile({ gmat: v })} step="10" min={200} max={800} />
              </div>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold">{t('wizard.stepBudget')}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <NumField label={t('wizard.budgetLabel')} value={profile.budget} onChange={(v) => updateProfile({ budget: v })} step="1" min={0} />
              <label className="block"><span className="text-sm font-semibold">{t('wizard.budgetCurrency')}</span>
                <select value={profile.budgetCurrency ?? 'GBP'} onChange={(e) => updateProfile({ budgetCurrency: e.target.value })} className="mt-1 w-full rounded-lg border border-navy/25 bg-white px-3 py-2">
                  <option value="GBP">GBP</option><option value="SGD">SGD</option><option value="USD">USD</option>
                </select></label>
            </div>
            <p className="text-sm text-navy/60">{t('wizard.budgetHint')}</p>
            {profile.sample && <p className="rounded-lg bg-amber/20 p-3 text-sm font-semibold">{t('common.synthetic')}</p>}
          </div>
        )}

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p>}

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <button type="button" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0} className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold disabled:opacity-40">{t('wizard.back')}</button>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={loadSample} className="btn-press rounded-full border border-teal px-4 py-2 text-sm font-semibold text-teal-dark">{t('wizard.sampleProfile')}</button>
            {step < STEPS.length - 1
              ? <button type="button" onClick={next} className="btn-press rounded-full bg-navy px-5 py-2 font-semibold text-white">{t('wizard.next')}</button>
              : <button type="button" onClick={finish} className="btn-press rounded-full bg-amber px-5 py-2 font-semibold text-navy">{t('wizard.finish')}</button>}
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
