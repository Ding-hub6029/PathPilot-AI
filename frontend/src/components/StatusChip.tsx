'use client';
import { useApp } from '../lib/store';
import { statusText } from '../lib/ruleText';

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const { t } = useApp();
  const cls = status === 'MET' ? 'chip-met' : status === 'NOT_MET' ? 'chip-notmet' : 'chip-unknown';
  // A bare chip ("符合") means nothing on its own: callers pass the
  // rule name in `label` so the chip reads e.g. "学术：符合".
  const text = label ?? statusText(status, t);
  return <span className={`chip anim-chip ${cls}`}>{text}</span>;
}
