'use client';
import { useApp } from '../lib/store';

/**
 * Round 31, G2 — confirmation dialog shown before "Try a sample
 * profile" overwrites a filled profile. The sample replaces the
 * whole profile (wizard fields + all 8 preference-chat answers),
 * so the overwrite is gated on hasProfileData at both call sites
 * (homepage trySample, wizard loadSample); when nothing is filled
 * the sample loads with one click and this dialog never opens.
 * Cancel reuses the existing common.close key ("Close" = keep my
 * data); only the title, body and replace button are new keys.
 */
export function SampleConfirmDialog({ open, onConfirm, onCancel }: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useApp();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-navy/60 p-4" onClick={onCancel}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="sample-confirm-title" aria-describedby="sample-confirm-body"
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl ring-1 ring-navy/10" onClick={(e) => e.stopPropagation()}>
        <h2 id="sample-confirm-title" className="text-lg font-bold">{t('sample.confirmTitle')}</h2>
        <p id="sample-confirm-body" className="mt-2 text-sm text-navy/75">{t('sample.confirmBody')}</p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-press rounded-full border border-navy/30 px-4 py-2 text-sm font-semibold">{t('common.close')}</button>
          <button type="button" onClick={onConfirm} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('sample.confirmReplace')}</button>
        </div>
      </div>
    </div>
  );
}
