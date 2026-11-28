'use client';
import { useEffect, useRef } from 'react';

/**
 * ParticleRing — Restyle 2 (aureon + RAN particle KV), Worker A.
 *
 * A RECREATED canvas-2D orbital ring: restrained blue-white stardust
 * plus amber #F2A541 highlights, particle tracks drawn as study-route
 * arcs around a gold compass at the centre. The RAN video's own fine
 * print forbids commercial reuse / secondary distribution of its
 * footage, so nothing is lifted — every pixel is drawn here in code.
 *
 * One slow ~12 s silent loop (particles complete one orbit per loop),
 * hero only. Lightweight: a single 2D canvas, devicePixelRatio capped
 * at 2, ~120 particles, transform-free drawing. Pauses when offscreen
 * (IntersectionObserver cancels the rAF loop; resuming continues the
 * same 12 s cycle from wall-clock time, so there is no jump). Under
 * prefers-reduced-motion it draws exactly one static frame and never
 * starts the loop. No props, no data, no copy — purely decorative
 * (aria-hidden; the compass SVG beside it is decorative too).
 */
const LOOP_MS = 12000;
const RING_COUNT = 34;
const DUST_COUNT = 90;

/** Deterministic PRNG so the static frame and the loop agree. */
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Particle = {
  angle: number; radius: number; size: number; amber: boolean;
  twinkle: number; speed: number;
};

function buildParticles(): Particle[] {
  const rand = mulberry32(20261128);
  const out: Particle[] = [];
  for (let i = 0; i < RING_COUNT; i++) {
    out.push({
      angle: (i / RING_COUNT) * Math.PI * 2,
      radius: 0.86 + rand() * 0.1,
      size: 1.4 + rand() * 1.6,
      amber: rand() < 0.3,
      twinkle: rand() * Math.PI * 2,
      speed: 1,
    });
  }
  for (let i = 0; i < DUST_COUNT; i++) {
    out.push({
      angle: rand() * Math.PI * 2,
      radius: 0.25 + rand() * 1.05,
      size: 0.6 + rand() * 1.1,
      amber: rand() < 0.12,
      twinkle: rand() * Math.PI * 2,
      speed: 0.35 + rand() * 0.5,
    });
  }
  return out;
}

export function ParticleRing() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const particles = buildParticles();
    let raf = 0;
    let running = false;
    let visible = true;

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const rect = wrap.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const draw = (t: number) => {
      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) * 0.42;
      ctx.clearRect(0, 0, w, h);
      // Faint orbital ring the particles travel on.
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(247,245,240,0.22)';
      ctx.lineWidth = Math.max(1, w * 0.002);
      ctx.stroke();
      // Study-route arcs: dashed tracks that drift along the ring,
      // one full dash cycle per 12 s loop.
      const dash = R * 0.9;
      for (const [color, offset] of [
        ['rgba(242,165,65,0.55)', 0],
        ['rgba(247,245,240,0.4)', Math.PI * 0.7],
        ['rgba(14,124,123,0.5)', Math.PI * 1.35],
      ] as const) {
        ctx.beginPath();
        ctx.setLineDash([dash * 0.45, dash * 1.55]);
        ctx.lineDashOffset = -t * dash * 2 - offset * R;
        ctx.arc(cx, cy, R, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.stroke();
      }
      ctx.setLineDash([]);
      // Particles: ring travellers orbit once per loop; stardust
      // twinkles in place (slow drift only, via its own phase).
      for (const p of particles) {
        const a = p.angle + t * Math.PI * 2 * p.speed;
        const tw = 0.45 + 0.55 * Math.abs(Math.sin(t * Math.PI * 4 + p.twinkle));
        const x = cx + Math.cos(a) * R * p.radius;
        const y = cy + Math.sin(a) * R * p.radius * 0.92;
        ctx.beginPath();
        ctx.arc(x, y, p.size * (canvas.width / 400 + 0.5), 0, Math.PI * 2);
        ctx.fillStyle = p.amber
          ? `rgba(242,165,65,${(0.55 + 0.45 * tw).toFixed(3)})`
          : `rgba(214,228,245,${(0.35 + 0.6 * tw).toFixed(3)})`;
        ctx.fill();
      }
    };

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      // Static frame only: the ring at a quarter of its loop, no rAF.
      draw(0.25);
      return () => { ro.disconnect(); };
    }

    const tick = () => {
      if (!running) return;
      draw(((performance.now() % LOOP_MS) / LOOP_MS));
      raf = requestAnimationFrame(tick);
    };
    const start = () => {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };
    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible) start(); else stop();
      },
      { threshold: 0.05 },
    );
    io.observe(wrap);
    // Draw one frame immediately so the hero never shows an empty box
    // while the observer settles.
    draw(0.25);
    start();
    return () => { stop(); io.disconnect(); ro.disconnect(); };
  }, []);

  return (
    <div ref={wrapRef} className="particle-ring relative aspect-[4/3] w-full" aria-hidden="true">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      {/* Gold compass at the centre of the ring (the pet is 小罗盘);
          static SVG, needle sways via the existing .anim-needle. */}
      <svg viewBox="0 0 32 32" className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 sm:h-24 sm:w-24">
        <circle cx="16" cy="16" r="14" fill="#0B1F3A" fillOpacity=".55" stroke="#F2A541" strokeWidth="1.5" />
        <circle cx="16" cy="16" r="10.5" fill="none" stroke="#F7F5F0" strokeOpacity=".5" strokeWidth=".75" />
        <g className="anim-needle">
          <path d="M16 6 L19 16 L16 26 L13 16 Z" fill="#F2A541" />
          <path d="M6 16 L16 13 L26 16 L16 19 Z" fill="#F7F5F0" opacity=".9" />
        </g>
        <circle cx="16" cy="16" r="2" fill="#F7F5F0" />
      </svg>
    </div>
  );
}
