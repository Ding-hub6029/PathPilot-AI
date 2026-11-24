'use client';
import { useApp } from '../lib/store';

export function StatusChip({ status }: { status: string }) {
  const { t } = useApp();
  const cls = status === 'MET' ? 'chip-met' : status === 'NOT_MET' ? 'chip-notmet' : 'chip-unknown';
  const label = status === 'MET' ? t('results.met') : status === 'NOT_MET' ? t('results.notMet') : t('results.unknown');
  return <span className={`chip anim-chip ${cls}`}>{label}</span>;
}
