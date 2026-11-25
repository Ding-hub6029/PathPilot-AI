'use client';
import { useEffect, useRef, useState } from 'react';
import { RTL_LOCALES, useApp } from '../lib/store';

/**
 * FanCarousel — reusable 3D fan carousel (2026-11-25, from the user's
 * Xiaohongshu "AI设计实验室" Animated Testimonials reference).
 *
 * Layout and motion only — NOT the video's purple-pink palette. This
 * is the PathPilot compass theme: deep navy block (#0B1F3A), amber
 * gradient title, dark-grey cards with a 1px translucent border.
 *
 * - One card is centre and biggest; the neighbours sit at 0.82×, 40%
 *   opacity, tilted away in 3D perspective (rotateY), fanning out.
 * - Switching slides the track (translateX) while scale / opacity /
 *   tilt transition together (~0.55s, the one easing family).
 * - Cards flip-fade in on mount (staggered).
 * - Round prev/next arrows sit below the cards; side cards brighten
 *   to 100% opacity on hover and are clickable to centre them.
 * - Mobile: arrows + swipe; the track is clipped by overflow-hidden
 *   so cards never spill off the page.
 * - No stars anywhere: this carousel never invents a rating.
 */

export function FanCarousel<T>({
  titleId, title, subtitle, note, items, renderCard, prevLabel, nextLabel,
}: {
  titleId: string;
  title: string;
  subtitle?: string;
  note?: string;
  items: T[];
  renderCard: (item: T) => React.ReactNode;
  prevLabel: string;
  nextLabel: string;
}) {
  const { locale } = useApp();
  const isRtl = RTL_LOCALES.includes(locale);
  const [index, setIndex] = useState(0);
  const [cardW, setCardW] = useState(340);
  const [containerW, setContainerW] = useState(800);
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const touchXRef = useRef<number | null>(null);

  const GAP = 16;

  useEffect(() => {
    const measure = () => {
      if (containerRef.current) setContainerW(containerRef.current.clientWidth);
      if (cardRef.current) setCardW(cardRef.current.getBoundingClientRect().width);
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (containerRef.current) ro.observe(containerRef.current);
    window.addEventListener('resize', measure);
    return () => { ro.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  const count = items.length;
  // No wrap-around: wrapping would teleport the track (the card at the
  // far end is positioned far away, not next to the centre), so the
  // slide would jump instead of gliding. The arrows simply stop at the
  // ends — the motion stays smooth everywhere.
  const go = (next: number) => {
    if (count === 0) return;
    setIndex(Math.max(0, Math.min(count - 1, next)));
  };
  const prev = () => go(index - 1);
  const next = () => go(index + 1);

  // Track offset that centres the current card. In RTL the flex row
  // runs right-to-left, so the sign flips.
  const offset = (containerW - cardW) / 2 - index * (cardW + GAP);
  const trackX = isRtl ? -offset : offset;

  const onTouchStart = (e: React.TouchEvent) => { touchXRef.current = e.touches[0].clientX; };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchXRef.current === null) return;
    const dx = e.changedTouches[0].clientX - touchXRef.current;
    touchXRef.current = null;
    if (dx < -40) next();
    else if (dx > 40) prev();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); isRtl ? next() : prev(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); isRtl ? prev() : next(); }
  };

  if (count === 0) return null;

  return (
    <section aria-labelledby={titleId} className="mt-10 overflow-hidden rounded-3xl bg-navy px-4 py-10 text-white sm:px-8">
      <p className="microcopy text-amber">{subtitle ?? ''}</p>
      <h2 id={titleId} className="hero-display line-mask mt-2 text-3xl sm:text-4xl">
        <span className="grad-amber-text">{title}</span>
      </h2>
      {note && <p className="mt-2 max-w-xl text-sm text-white/70">{note}</p>}

      <div ref={containerRef}
        className="perspective-1200 mt-8 overflow-hidden"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        onKeyDown={onKeyDown}
        tabIndex={0}
        role="region"
        aria-roledescription="carousel"
        aria-label={title}
      >
        <div
          className="flex gap-4 transition-transform duration-500"
          style={{ transform: `translateX(${trackX}px)`, transitionTimingFunction: 'cubic-bezier(.22,1,.36,1)' }}
        >
          {items.map((item, i) => {
            const dist = i - index;
            const abs = Math.abs(dist);
            const isCenter = dist === 0;
            const isSide = abs === 1;
            const scale = isCenter ? 1 : isSide ? 0.82 : 0.7;
            const opacity = isCenter ? 1 : isSide ? 0.4 : 0;
            // Tilt away from the centre; mirrored in RTL.
            const tilt = isCenter ? 0 : (dist < 0 ? 1 : -1) * (isRtl ? -22 : 22);
            return (
              <div
                key={i}
                ref={i === 0 ? cardRef : undefined}
                role="group"
                aria-roledescription="slide"
                aria-label={`${i + 1} / ${count}`}
                className={`fan-card w-[min(78vw,340px)] shrink-0 ${isSide ? 'fan-side cursor-pointer' : ''}`}
                style={{
                  transform: `scale(${scale}) rotateY(${tilt}deg)`,
                  opacity,
                  zIndex: isCenter ? 20 : 10,
                  pointerEvents: abs > 1 ? 'none' : 'auto',
                }}
                onClick={() => { if (isSide) go(i); }}
              >
                <div className="anim-fan-flip h-full" style={{ animationDelay: `${0.08 * Math.min(i, 3)}s` }}>
                  {renderCard(item)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-center gap-4">
        <button type="button" onClick={prev} aria-label={prevLabel} disabled={index === 0}
          className="btn-press flex h-11 w-11 items-center justify-center rounded-full border border-white/40 text-xl font-bold text-white hover:bg-white/10 disabled:opacity-30">
          {isRtl ? '→' : '←'}
        </button>
        <span className="text-sm font-semibold text-white/70" aria-live="polite">
          {index + 1} / {count}
        </span>
        <button type="button" onClick={next} aria-label={nextLabel} disabled={index === count - 1}
          className="btn-press flex h-11 w-11 items-center justify-center rounded-full border border-white/40 text-xl font-bold text-white hover:bg-white/10 disabled:opacity-30">
          {isRtl ? '←' : '→'}
        </button>
      </div>
    </section>
  );
}
