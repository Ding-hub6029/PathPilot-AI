'use client';
import { useApp } from '../lib/store';

/**
 * Structured Gaokao route panel (user testing 2026-11-25): replaces the
 * bare "unknown" academic chip for Gaokao applicants with the verified
 * routes from backend/ai/gaokao_routes.py (16 facts, official pages
 * only). No Gaokao % -> A-level conversion exists anywhere, so none is
 * invented; Gaokao earns no UCAS Tariff points; Oxford stays unknown.
 * Only facts whose URL was re-captured in the research pass are linked.
 */
const SOURCES: { label: string; url: string }[] = [
  { label: 'UCL', url: 'https://www.ucl.ac.uk/study/international/region/east-asia/china' },
  { label: 'Imperial', url: 'https://www.imperial.ac.uk/study/international-students/information-by-region/east-asia/' },
  { label: 'Birmingham', url: 'https://www.birmingham.ac.uk/international/students/country/china/gaokao' },
  { label: 'LSE', url: 'https://www.lse.ac.uk/study-at-lse/international-students/china' },
  { label: 'Cambridge', url: 'https://www.trin.cam.ac.uk/undergraduate/applying/overseas-qualifications/' },
  { label: 'Oxford', url: 'https://www.ox.ac.uk/admissions/undergraduate/courses/admissions-requirements/international-qualifications' },
  { label: 'TMUA', url: 'https://www.imperial.ac.uk/study/apply/undergraduate/process/admissions-tests/tmua/' },
  { label: 'UCAS', url: 'https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications' },
];

export function GaokaoPanel() {
  const { t } = useApp();
  const blocks = [
    t('wizard.gaokaoUcl'),
    t('wizard.gaokaoImperial'),
    t('wizard.gaokaoOthers'),
    t('wizard.gaokaoAst'),
    t('wizard.gaokaoTmua'),
    t('wizard.gaokaoUcas'),
    t('wizard.gaokaoOxford'),
  ];
  return (
    <div className="mt-4 rounded-2xl border border-teal/30 bg-teal/5 p-4" role="note" aria-label={t('wizard.gaokaoPanelTitle')}>
      <p className="font-bold">{t('wizard.gaokaoPanelTitle')}</p>
      <p className="mt-2 text-sm text-navy/80">{t('wizard.gaokaoPanelIntro')}</p>
      <ul className="mt-3 space-y-3">
        {blocks.map((s, i) => (
          <li key={i} className="border-s-2 border-amber ps-3 text-sm text-navy/80">{s}</li>
        ))}
      </ul>
      <p className="mt-4 text-sm">
        <span className="font-semibold">{t('wizard.gaokaoSources')}: </span>
        {SOURCES.map((s, i) => (
          <span key={s.label}>
            {i > 0 && ' · '}
            <a href={s.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{s.label}</a>
          </span>
        ))}
      </p>
    </div>
  );
}
