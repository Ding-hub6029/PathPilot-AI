/**
 * GoldObject — Restyle 2 (aureon), Worker A.
 *
 * One gold object per programme card (aureon: one object per feature
 * card), cycling compass / cap / globe / key. Inline SVG only, no new
 * binary assets; amber #F2A541 on white with a navy outline so the
 * object reads on the paper cards. Decorative (aria-hidden in the
 * caller); the card's real content is unchanged.
 */
export type GoldObjectKind = 'compass' | 'cap' | 'globe' | 'key';

export const GOLD_OBJECT_KINDS: GoldObjectKind[] = ['compass', 'cap', 'globe', 'key'];

export function GoldObject({ kind }: { kind: GoldObjectKind }) {
  const common = {
    width: 40, height: 40, viewBox: '0 0 40 40', 'aria-hidden': true as const,
  };
  if (kind === 'cap') {
    return (
      <svg {...common}>
        <path d="M20 6 L38 14 L20 22 L2 14 Z" fill="#F2A541" stroke="#0B1F3A" strokeWidth="1.2" />
        <path d="M11 18 v8 c0 3 18 3 18 0 v-8 l-9 4 z" fill="#F7C873" stroke="#0B1F3A" strokeWidth="1.2" />
        <path d="M34 16 v9" stroke="#0B1F3A" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="34" cy="28" r="2" fill="#F2A541" stroke="#0B1F3A" strokeWidth="1" />
      </svg>
    );
  }
  if (kind === 'globe') {
    return (
      <svg {...common}>
        <circle cx="20" cy="20" r="14" fill="#F7C873" stroke="#0B1F3A" strokeWidth="1.2" />
        <ellipse cx="20" cy="20" rx="6" ry="14" fill="none" stroke="#0B1F3A" strokeWidth="1" />
        <path d="M6 20 h28 M8 12 h24 M8 28 h24" fill="none" stroke="#0B1F3A" strokeWidth="1" />
        <path d="M20 6 a14 14 0 0 1 0 28" fill="none" stroke="#F2A541" strokeWidth="1.6" />
      </svg>
    );
  }
  if (kind === 'key') {
    return (
      <svg {...common}>
        <circle cx="13" cy="13" r="7" fill="none" stroke="#F2A541" strokeWidth="3" />
        <circle cx="13" cy="13" r="2.5" fill="#0B1F3A" />
        <path d="M18 18 L33 33 M28 28 l4 -1 M31 31 l4 -1" stroke="#F2A541" strokeWidth="3" strokeLinecap="round" fill="none" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="20" cy="20" r="15" fill="#F7C873" stroke="#0B1F3A" strokeWidth="1.2" />
      <circle cx="20" cy="20" r="11" fill="none" stroke="#0B1F3A" strokeWidth=".8" />
      <path d="M20 9 L23 20 L20 31 L17 20 Z" fill="#F2A541" stroke="#0B1F3A" strokeWidth=".8" />
      <path d="M9 20 L17 17 L31 20 L23 23 Z" fill="#F7F5F0" stroke="#0B1F3A" strokeWidth=".8" />
      <circle cx="20" cy="20" r="2" fill="#0B1F3A" />
    </svg>
  );
}
