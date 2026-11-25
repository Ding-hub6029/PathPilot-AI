'use client';
import { useEffect, useState } from 'react';
import { fetchInstitutionRankings } from '../lib/api';
import { RANKING_PROVIDERS } from '../lib/rankings';
import { RankingEntry } from '../lib/types';
import { useApp } from '../lib/store';

/**
 * Three provider ranking cards for one institution (Day 3, FR15).
 * World ranks only; providers are never averaged into one score (BR15).
 * Unavailable entries show the explicit reason, never a guessed value.
 */
export function RankingCards({ institutionId }: { institutionId: string }) {
  const { t, locale } = useApp();
  const [entries, setEntries] = useState<RankingEntry[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    fetchInstitutionRankings(institutionId)
      .then((r) => { setEntries(r.entries); setLive(r.live); })
      .catch(() => undefined);
  }, [institutionId]);

  if (!entries.length) return null;
  const providers = RANKING_PROVIDERS;

  return (
    <div>
      <div className="grid gap-3 sm:grid-cols-2">
        {providers.map((p) => {
          const e = entries.find((x) => x.provider === p.id);
          const available = e && e.verification_status === 'verified';
          return (
            <div key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
              <p className="text-sm font-bold">{p.short_name} · {p.edition_label}</p>
              <p className="mt-1 text-xs text-navy/60">{p.name}</p>
              {available && e ? (
                <>
                  <p className="mt-3 text-3xl font-bold" dir="ltr">{e.rank_display}</p>
                  {e.rank_kind === 'tie' && <p className="mt-1 text-xs text-navy/60">{t('rankings.tieNote')}</p>}
                  {e.score !== null && <p className="mt-1 text-sm text-navy/70">{t('rankings.score')}: <span dir="ltr">{e.score}</span></p>}
                </>
              ) : (
                <p className="mt-3 text-sm font-semibold text-amber-dark">{t('rankings.unavailableShort')}</p>
              )}
              {e?.unavailable_reason && (
                <p className="mt-2 text-xs text-navy/60">{e.unavailable_reason}</p>
              )}
              <p className="mt-3 text-xs">
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
              <p className="mt-1 text-xs text-navy/50">{t('rankings.verifiedOn')} {e?.retrieved_at?.slice(0, 10) ?? p.published_at}</p>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-navy/60">{t('rankings.rankingsNote')}</p>
      {!live && <p className="mt-1 text-xs text-navy/60">{t('rankings.offlineNote')}</p>}
    </div>
  );
}
