'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../../lib/store';
import { fetchInstitutionRankings } from '../../../lib/api';
import { RankingCards } from '../../../components/RankingCards';
import { PROGRAMS } from '../../../lib/programs';
import { RankingInstitution } from '../../../lib/types';

/**
 * Institution detail page (Day 3 expansion, FR15/FR16).
 * One institution's ranks across the three providers (via RankingCards),
 * its compiled IELTS reference when one exists, and its programmes: the
 * verified programmes link to their full programme detail; every other
 * institution shows "programme admission data not yet verified" with a
 * link to its official site (or, where no official site is verified, to
 * its provider profile page). Programme requirements are never invented
 * for institutions PathPilot has not verified. The IELTS reference is a
 * compiled value from user-supplied ranking-table images — it is not an
 * official programme requirement and the eligibility engine never uses it.
 */
export default function InstitutionDetail({ params }: { params: { id: string } }) {
  const { t } = useApp();
  const [institution, setInstitution] = useState<RankingInstitution | undefined>(undefined);
  const [loaded, setLoaded] = useState(false);
  const [live, setLive] = useState(false);

  useEffect(() => {
    fetchInstitutionRankings(params.id)
      .then((r) => { setInstitution(r.institution); setLive(r.live); setLoaded(true); })
      .catch(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (!loaded) {
    return <div className="mx-auto max-w-4xl px-4 py-12"><p>{t('programs.loading')}</p></div>;
  }
  if (!institution) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p>{t('institution.notFound')}</p>
        <Link href="/rankings" className="text-teal-dark underline">{t('institution.backToRankings')}</Link>
      </div>
    );
  }

  const programs = PROGRAMS.filter((p) => p.institutionId === institution.id);
  const profiles = institution.provider_profiles ?? {};
  const profileLink = profiles.qs ?? profiles.the ?? profiles.arwu;

  return (
    <div className="page-enter mx-auto max-w-4xl px-4 py-8">
      <Link href="/rankings" className="btn-press inline-block rounded-full border border-navy/25 bg-white px-4 py-2 text-sm font-semibold">← {t('institution.backToRankings')}</Link>
      <h1 className="mt-4 text-2xl font-bold">{institution.official_name}</h1>
      <p className="mt-1 text-navy/70">{institution.country_name}</p>
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

      {institution.ielts_reference && (
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
        {programs.length > 0 ? (
          <ul className="mt-3 space-y-3">
            {programs.map((p) => (
              <li key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
                <p className="font-bold">
                  <Link href={`/programs/${p.id}`} className="text-teal-dark underline">{p.officialName}</Link>
                </p>
                <p className="mt-1 text-sm text-navy/60">{p.institution} · {p.country}</p>
                <Link href="/wizard" className="btn-press mt-3 inline-block rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('home.ctaWizard')}</Link>
              </li>
            ))}
          </ul>
        ) : (
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

      {!live && <p className="mt-6 text-sm text-navy/60">{t('rankings.offlineNote')}</p>}
      <p className="mt-2 text-xs text-navy/60" lang="en" dir="ltr">
        Source: QS Quacquarelli Symonds (www.qs.com). With permission. Copyright © QS Quacquarelli Symonds Ltd.
      </p>
    </div>
  );
}
