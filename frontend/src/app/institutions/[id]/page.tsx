'use client';
import Link from 'next/link';
import { useApp } from '../../../lib/store';
import { useBackendStatus } from '../../../lib/backendStatus';
import { RANKING_INSTITUTIONS, RANKING_PROVIDERS, displayCountryCode, displayCountryName, displayInstitutionName, displayProgramInstitutionName } from '../../../lib/rankings';
import { RankingCards } from '../../../components/RankingCards';
import { LanguageOfInstructionLine } from '../../../components/RuleRow';
import { PROGRAMS, displayProgramName } from '../../../lib/programs';
import { EXPANSION_PROGRAMS } from '../../../lib/expansion';
import { ExpansionProgram } from '../../../lib/types';
import { crestFor, monogramFor } from '../../../lib/crests';
import { ViewTransitionLink } from '../../../components/ViewTransitionLink';
import { vtRef } from '../../../lib/viewTransition';

/**
 * Institution detail page (Day 3 expansion, FR15/FR16).
 * One institution's ranks across the three providers (via RankingCards),
 * its programmes, and its compiled IELTS reference — the reference is
 * shown ONLY where no verified language requirement exists for the
 * institution. Verified requirements replace it wherever they exist.
 *
 * Programmes come in two groups, never mixed:
 * - the 8 verified v2 programmes (eligibility check available, link to
 *   the full programme detail);
 * - the expansion programmes (886 across 100 institutions, collected from
 *   official pages): each shows its verified requirements verbatim, fee,
 *   deadline and sources. They are display-only — matching stays v2-only.
 * Institutions with neither show "programme admission data not yet
 * verified" with a link to the official site (or a provider profile).
 * Programme requirements are never invented. The IELTS reference is a
 * compiled value from user-supplied ranking-table images — it is not an
 * official programme requirement and the eligibility engine never uses it.
 */

const REQ_CATEGORY_KEYS: Record<string, string> = {
  academic: 'institution.reqAcademic',
  language: 'institution.reqLanguage',
  test: 'institution.reqTest',
  fee: 'institution.reqFee',
  other: 'institution.reqOther',
};

function formatFee(p: ExpansionProgram, locale: string): string | null {
  const f = p.fees;
  if (!f.currency) return null;
  const fmt = (n: number) => {
    try {
      return new Intl.NumberFormat(locale, { style: 'currency', currency: f.currency, maximumFractionDigits: 0 }).format(n);
    } catch {
      return `${f.currency} ${n.toLocaleString('en-US')}`;
    }
  };
  if (f.amount !== null && f.amount !== undefined) return `${fmt(f.amount)} ${f.period === 'per_year' ? 'per year' : f.period || ''}`.trim();
  if (f.amountMin !== null && f.amountMin !== undefined && f.amountMax !== null && f.amountMax !== undefined) {
    return `${fmt(f.amountMin)}–${fmt(f.amountMax)} ${f.period === 'per_year' ? 'per year' : f.period || ''}`.trim();
  }
  return null;
}

function expansionDisplayName(p: ExpansionProgram, locale: string): string {
  return p.nameLocalized?.[locale] ?? p.officialName;
}

const DEGREE_LABEL_KEYS: Record<string, string> = {
  undergraduate: 'cases.filterUg',
  taught_masters: 'cases.filterTm',
  foundation: 'institution.filterFoundation',
  joint_honours: 'institution.filterJointHonours',
};

function ExpansionProgramCard({ p, locale }: { p: ExpansionProgram; locale: string }) {
  const { t } = useApp();
  const fee = formatFee(p, locale);
  const sourceById = new Map(p.sources.map((s) => [s.id, s]));
  const grouped = new Map<string, typeof p.requirements>();
  for (const r of p.requirements) {
    const list = grouped.get(r.category) ?? [];
    list.push(r);
    grouped.set(r.category, list);
  }
  return (
    <li className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
      <p className="font-bold" dir="auto">{expansionDisplayName(p, locale)}</p>
      <p className="mt-1 text-sm text-navy/60">
        {t(DEGREE_LABEL_KEYS[p.degreeLevel] ?? 'cases.filterTm')}
        {p.duration ? ` · ${p.duration}` : ''}
        {p.start ? ` · ${p.start}` : ''}
      </p>
      <p className="mt-1 text-sm text-navy/75">
        {fee ?? t('institution.feeNotPublished')}
        {p.applicationDeadline ? ` · ${t('institution.deadline')}: ${p.applicationDeadline}` : ''}
      </p>
      {/* Round 9 (R5): verified language of instruction, shown on the
          programme card — ETH/EPFL bachelor's are not taught in
          English, and that decides whether an applicant can follow
          the course. */}
      <LanguageOfInstructionLine languageOfInstruction={p.languageOfInstruction} />
      {p.applicationStatus === 'open' && (
        <p className="mt-2"><span className="inline-block rounded-full bg-teal/15 px-3 py-1 text-xs font-semibold text-teal-dark">{t('institution.statusOpen')}</span></p>
      )}
      <div className="mt-3">
        <h4 className="text-sm font-bold">{t('institution.reqTitle')}</h4>
        {[...grouped.entries()].map(([category, reqs]) => (
          <div key={category} className="mt-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-navy/50">{t(REQ_CATEGORY_KEYS[category] ?? 'institution.reqOther')}</p>
            <ul className="mt-1 space-y-2">
              {reqs.map((r) => (
                <li key={r.id} className="text-sm text-navy/80" dir="auto">
                  {r.description}
                  {r.sourceIds.length > 0 && (
                    <span className="ms-1">
                      {r.sourceIds.map((sid) => {
                        const s = sourceById.get(sid);
                        return s ? (
                          <a key={sid} href={s.url} target="_blank" rel="noreferrer" className="me-2 font-semibold text-teal-dark underline">{t('evidence.openSource')}</a>
                        ) : null;
                      })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {p.sources.length > 0 && (
        <p className="mt-3 text-xs text-navy/60">
          {t('program.sources')}:{' '}
          {p.sources.map((s, i) => (
            <span key={s.id}>
              {i > 0 && ' · '}
              <a href={s.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline" lang="en" dir="ltr">{s.title}</a>
            </span>
          ))}
        </p>
      )}
    </li>
  );
}

export default function InstitutionDetail({ params }: { params: { id: string } }) {
  const { t, locale } = useApp();
  // Round 9 (R12): the institution renders from the local mirror
  // synchronously — the old code gated the whole page (including the
  // course section) on fetchInstitutionRankings, a network call with a
  // 20s timeout, so a waking backend left the course section on
  // "正在加载课程…" for 5–8s+. The mirror holds the identical verified
  // data (round 8), so no network call is needed to render this page.
  // Round 9 (R9): the footer status comes from the one shared probe.
  const backendStatus = useBackendStatus();
  const institution = RANKING_INSTITUTIONS.find((i) => i.id === params.id);

  if (!institution) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p>{t('institution.notFound')}</p>
        <Link href="/rankings" className="text-teal-dark underline">{t('institution.backToRankings')}</Link>
      </div>
    );
  }

  const programs = PROGRAMS.filter((p) => p.institutionId === institution.id);
  const expansionPrograms = EXPANSION_PROGRAMS.filter((p) => p.institutionId === institution.id);
  const crest = crestFor(institution.id);
  const profiles = institution.provider_profiles ?? {};
  const profileLink = profiles.qs ?? profiles.the ?? profiles.arwu;
  // A verified language requirement replaces the compiled IELTS reference:
  // an expansion programme with a language-category requirement, or a v2
  // programme whose official sources state an IELTS/TOEFL requirement.
  const hasVerifiedLanguage =
    expansionPrograms.some((p) => p.requirements.some((r) => r.category === 'language')) ||
    programs.some((p) => p.sources.some((s) => /IELTS|TOEFL/i.test(s.excerpt)));

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/rankings" className="btn-press inline-block rounded-full border border-navy/25 bg-white px-4 py-2 text-sm font-semibold">← {t('institution.backToRankings')}</Link>
      {/* Crest in the header (research move 4): the shared element the
          rankings row crest morphs into. Monogram fallback where no
          freely-usable crest exists — same as the rankings list. */}
      <div className="mt-4 flex items-center gap-4">
        {crest && 'src' in crest ? (
          <span ref={vtRef(`crest-${institution.id}`)} className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-navy/10 bg-white" aria-hidden="true">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={crest.src} alt="" className="h-14 w-14 object-contain" />
          </span>
        ) : (
          <span ref={vtRef(`crest-${institution.id}`)} className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-[#0B1F3A] text-xl font-bold text-white" aria-hidden="true">
            {monogramFor(institution.official_name)}
          </span>
        )}
        <h1 className="line-mask text-2xl font-bold"><span>{displayInstitutionName(institution, locale)}</span></h1>
      </div>
      <p className="mt-1 text-navy/70">{displayCountryName(institution, t)}</p>
      <p className="mt-2 text-sm">
        {institution.official_website && (
          <a href={institution.official_website} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('institution.officialSite')}</a>
        )}
        {institution.official_website && profileLink && ' · '}
        {profileLink && (
          <a href={profileLink} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('institution.providerProfile')}</a>
        )}
      </p>

      <section className="mt-8" aria-labelledby="inst-rank-title">
        <h2 id="inst-rank-title" className="text-xl font-bold">{t('institution.rankings')}</h2>
        <div className="mt-3">
          <RankingCards institutionId={institution.id} />
        </div>
      </section>

      {institution.ielts_reference && !hasVerifiedLanguage && (
        <section className="mt-8" aria-labelledby="inst-ielts-title">
          <h2 id="inst-ielts-title" className="text-xl font-bold">{t('institution.ieltsReference')}</h2>
          <div className="mt-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
            <p className="text-2xl font-bold" dir="ltr">{institution.ielts_reference}</p>
            <p className="mt-2 text-sm text-navy/70">{t('institution.ieltsReferenceNote')}</p>
            <p className="mt-1 text-xs text-navy/60">{t('institution.ieltsReferenceSource')}</p>
          </div>
        </section>
      )}

      <section className="mt-8" aria-labelledby="inst-prog-title">
        <h2 id="inst-prog-title" className="text-xl font-bold">{t('institution.programs')}</h2>
        {programs.length > 0 && (
          <>
            <h3 className="mt-4 text-base font-bold">{t('institution.v2Programs')}</h3>
            <ul className="mt-3 space-y-3">
              {programs.map((p) => (
                <li key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
                  <p className="font-bold">
                    <ViewTransitionLink href={`/programs/${p.id}`} className="text-teal-dark underline">
                      <span ref={vtRef(`program-title-${p.id}`)}>{displayProgramName(p, locale)}</span>
                    </ViewTransitionLink>
                  </p>
                  <p className="mt-1 text-sm text-navy/60">{displayProgramInstitutionName(p.institution, locale)} · {displayCountryCode(p.country, p.country, t)}</p>
                  <Link href="/wizard" className="btn-press mt-3 inline-block rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('home.ctaWizard')}</Link>
                </li>
              ))}
            </ul>
          </>
        )}
        {expansionPrograms.length > 0 && (
          <>
            <h3 className="mt-6 text-base font-bold">{t('institution.expansionPrograms')} ({expansionPrograms.length})</h3>
            <ul className="mt-3 space-y-3">
              {expansionPrograms.map((p) => (
                <ExpansionProgramCard key={p.id} p={p} locale={locale} />
              ))}
            </ul>
          </>
        )}
        {programs.length === 0 && expansionPrograms.length === 0 && (
          <div className="mt-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
            <p className="text-sm font-semibold text-navy/70">{t('institution.noPrograms')}</p>
            <p className="mt-2 text-sm">
              {institution.official_website ? (
                <a href={institution.official_website} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('institution.officialSite')}</a>
              ) : profileLink ? (
                <a href={profileLink} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('institution.providerProfile')}</a>
              ) : null}
            </p>
          </div>
        )}
      </section>

      {/* Round 9 (R9): status from the shared probe — "checking" while
          the probe is still waking the backend, offline only once it
          has actually failed. */}
      {backendStatus === 'checking' && <p className="mt-6 text-sm font-semibold text-navy/60" role="status">{t('r9pages.backendChecking')}</p>}
      {backendStatus === 'offline' && <p className="mt-6 text-sm text-navy/60">{t('rankings.offlineNote')}</p>}
      {/* Complete source lines for all three providers (Round 8): QS
          carries its exact attribution notice; THE and ARWU carry their
          not-licensed warnings — the warnings are kept, never dropped. */}
      <section className="mt-6" aria-labelledby="inst-src-title">
        <h2 id="inst-src-title" className="text-base font-bold">{t('rankings.sourcesTitle')}</h2>
        <ul className="mt-3 space-y-2">
          {RANKING_PROVIDERS.map((p) => (
            <li key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 text-sm shadow-sm">
              <p className="font-bold">{p.name} · <span dir="ltr">{p.edition_label}</span></p>
              <p className="mt-1">
                <a href={p.entry_url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('rankings.officialTable')}</a>
                {p.methodology_url && (
                  <>
                    {' · '}
                    <a href={p.methodology_url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('rankings.methodology')}</a>
                  </>
                )}
              </p>
              {p.id === 'qs' && p.attribution && (
                <p className="mt-2 text-xs text-navy/60" lang="en" dir="ltr">{p.attribution}</p>
              )}
              {(p.id === 'the' || p.id === 'arwu') && (
                <p className="mt-2 text-xs font-semibold text-amber-dark">{t(`rankings.rights.${p.id}`)}</p>
              )}
              <p className="mt-1 text-xs text-navy/60">{p.rights_note}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
