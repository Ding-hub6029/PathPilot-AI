'use client';
import { useMemo, type MouseEvent as ReactMouseEvent } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';
import { allPrograms } from '../lib/api';
import { CLIMATE_CITIES } from '../lib/climate';
import { displayCountryCode, displayProgramInstitutionName } from '../lib/rankings';
import type { ClimateClass, Program } from '../lib/types';
import { Reveal } from './Reveal';
import styles from './Destinations.module.css';

/**
 * "Explore destinations" homepage section (design upgrade, Worker B).
 *
 * Every number shown is computed at render time from the verified
 * programme catalogue — allPrograms() (the 8 fully-verified v2
 * programmes + the 886 expansion programmes, 894 total, the same set
 * the /programs browse page lists) — country, city, institution and
 * title come from that catalogue, climate classes from the curated
 * CLIMATE_CITIES map. Nothing is invented: no stars (no rating data),
 * no estimated counts, no hard-coded country list. The top 6 countries
 * are ranked by programme count; ties break on the country code so the
 * order is deterministic across locales.
 *
 * Interaction: hover gives a pointer-driven 3D tilt + lift and reveals
 * a second layer (top cities, climate chips, up to 2 sample programme
 * titles). :focus-visible / :focus-within reveal the same layer, so
 * keyboard users get it too; on touch (hover: none) and under
 * prefers-reduced-motion the layer is always visible and the tilt is
 * off (see Destinations.module.css).
 *
 * Navigation: /programs does NOT read a country query param — its
 * filter is local useState starting at 'all' — so cards link to plain
 * /programs. If the coordinator later adds ?country= support there,
 * change the href below to `/programs?country=${g.code}`.
 *
 * Global-class dependencies (defined by the other design-upgrade
 * worker in globals.css, never redefined here): .glass and
 * .aurora-border on the card, .section-rule / .line-mask / .grid-12
 * from the existing stylesheet.
 */
const CLIMATE_ORDER: ClimateClass[] = ['warm', 'mild', 'four_seasons', 'cool'];
const CLIMATE_KEYS: Record<ClimateClass, string> = {
  warm: 'wizard.prefClimateWarm',
  mild: 'wizard.prefClimateMild',
  four_seasons: 'wizard.prefClimateFourSeasons',
  cool: 'wizard.prefClimateCool',
};

interface CountryGroup {
  code: string;
  count: number;
  cities: { name: string; count: number }[];
  climates: ClimateClass[];
  samples: Program[];
}

function buildGroups(): CountryGroup[] {
  const byCountry = new Map<string, Program[]>();
  for (const p of allPrograms()) {
    const list = byCountry.get(p.country);
    if (list) list.push(p);
    else byCountry.set(p.country, [p]);
  }
  const groups: CountryGroup[] = [...byCountry.entries()].map(([code, list]) => {
    const cityCounts = new Map<string, number>();
    for (const p of list) {
      if (!p.city) continue;
      cityCounts.set(p.city, (cityCounts.get(p.city) ?? 0) + 1);
    }
    const cities = [...cityCounts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
      .slice(0, 3);
    const climateSet = new Set<ClimateClass>();
    for (const p of list) {
      if (!p.city) continue;
      const c = CLIMATE_CITIES[p.city]?.climate;
      if (c) climateSet.add(c);
    }
    const climates = CLIMATE_ORDER.filter((c) => climateSet.has(c));
    const samples = [...list]
      .sort((a, b) => a.institution.localeCompare(b.institution) || a.officialName.localeCompare(b.officialName))
      .slice(0, 2);
    return { code, count: list.length, cities, climates, samples };
  });
  groups.sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
  return groups.slice(0, 6);
}

const MAX_TILT_Y = 10; // degrees, pointer-driven rotateY
const MAX_TILT_X = 8; // degrees, pointer-driven rotateX

export function Destinations() {
  const { t, tf, locale } = useApp();
  const groups = useMemo(buildGroups, []);

  const onMove = (e: ReactMouseEvent<HTMLAnchorElement>) => {
    if (window.matchMedia('(pointer: coarse)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty('--ry', `${(px * MAX_TILT_Y).toFixed(2)}deg`);
    el.style.setProperty('--rx', `${(-py * MAX_TILT_X).toFixed(2)}deg`);
  };
  const onLeave = (e: ReactMouseEvent<HTMLAnchorElement>) => {
    e.currentTarget.style.removeProperty('--rx');
    e.currentTarget.style.removeProperty('--ry');
  };

  if (groups.length === 0) return null;

  return (
    <section className="section-rule mt-10" aria-labelledby="home-dest-title">
      <Reveal>
        <h2 id="home-dest-title" className="line-mask font-display text-2xl font-bold">
          <span>{t('home.destTitle')}</span>
        </h2>
        <p className="mt-1 text-sm text-navy/70">{t('home.destSub')}</p>
        <div className={`grid-12 mt-4 ${styles.grid}`}>
          {groups.map((g) => {
            const countryName = displayCountryCode(g.code, g.code, t);
            return (
              <Link
                key={g.code}
                href="/programs"
                className={`glass aurora-border md:col-span-4 ${styles.card}`}
                onMouseMove={onMove}
                onMouseLeave={onLeave}
                aria-label={`${countryName} — ${tf('home.destPrograms', { count: g.count })}`}
              >
                <span className={styles.topRow}>
                  <span className={styles.code} dir="ltr">{g.code}</span>
                  <span className={styles.arrow} aria-hidden="true">→</span>
                </span>
                <span className={styles.country}>{countryName}</span>
                <span className={styles.count}>{tf('home.destPrograms', { count: g.count })}</span>
                <span className={styles.revealLayer}>
                  <span className={styles.revealInner}>
                    <span className={styles.cities}>{g.cities.map((c) => c.name).join(' · ')}</span>
                    {g.climates.length > 0 && (
                      <span className={styles.chips}>
                        {g.climates.map((c) => (
                          <span key={c} className={styles.chip}>{t(CLIMATE_KEYS[c])}</span>
                        ))}
                      </span>
                    )}
                    <span className={styles.samples}>
                      {g.samples.map((p) => (
                        <span key={p.id} className={styles.sample}>
                          <span className={styles.sampleInst}>
                            {displayProgramInstitutionName(p.institution, locale)}
                          </span>
                          <span className={styles.sampleName}>
                            {p.nameLocalized?.[locale] ?? p.officialName}
                          </span>
                        </span>
                      ))}
                    </span>
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      </Reveal>
    </section>
  );
}
