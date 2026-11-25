// Field -> expansion field-slug map (Day 3, round 6).
//
// The wizard asks the field/direction first (business, computing,
// engineering, science, ...) and recommendations are filtered by it.
// v2 programmes are all 'Computer Science'; expansion programmes carry
// a controlled field slug (see docs/PROGRAMME_EXPANSION.md). Only slugs
// that exist in data/expansions/expansion.json are listed here — a field
// with no slugs yet (medicine, arts) honestly has no programmes, never
// a guessed mapping. 'other' (13 programmes, unclassified) matches no
// field.
import type { FieldId, Program } from './types';

export const FIELD_EXPANSION_FIELDS: Record<FieldId, string[]> = {
  computing: [
    'computer-science', 'data-science', 'artificial-intelligence',
    'software-engineering', 'cybersecurity', 'computer-engineering',
    'information-systems', 'human-computer-interaction',
    'computational-biology', 'other-computing',
  ],
  engineering: [
    'aerospace-engineering', 'biomedical-engineering',
    'chemical-engineering', 'civil-engineering', 'electrical-engineering',
    'mechanical-engineering', 'general-engineering', 'robotics',
  ],
  business: [
    'business-administration', 'finance', 'management', 'marketing',
    'economics', 'accounting',
  ],
  science: ['mathematics', 'physics'],
  medicine: [],
  humanities: ['history', 'political-science', 'international-relations'],
  arts: [],
};

/** Does a programme (v2 or converted expansion) belong to a wizard field?
 * v2 programmes carry subject 'Computer Science' (spaces); expansion
 * programmes carry the field slug. */
export function programMatchesField(p: Program, field: FieldId): boolean {
  const slugs = FIELD_EXPANSION_FIELDS[field];
  const value = (p as unknown as { field?: string }).field
    ?? p.subject ?? '';
  const norm = value.toLowerCase().replace(/ /g, '-');
  if (field === 'computing' && norm === 'computer-science') return true;
  return slugs.includes(norm);
}
