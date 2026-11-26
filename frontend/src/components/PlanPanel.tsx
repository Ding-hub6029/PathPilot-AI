'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';
import {
  createPlan,
  getPlan,
  isRateLimitedError,
  planErrorCode,
  reassessPlan,
  updateTaskStatus,
  type Plan,
  type PlanGap,
  type ReassessResult,
  type TaskStatus,
} from '../lib/plans';

/**
 * Improvement plan panel (Day 3, FR13/FR14; first frontend surface
 * for plans). Mounted on the programme detail page.
 *
 * Reliability boundary (user constraint, visible in every state):
 * - gap current_state text and reassessment changes come from the
 *   engine recompute — shown as verified facts;
 * - tasks are AI suggestions when a model wrote them (ai_status
 *   'available') or deterministic templates otherwise — either way
 *   they may be wrong, say so, and never promise an admission effect;
 * - completing a task alone never changes eligibility; only the
 *   engine recompute on reassess can;
 * - unknown stays unknown: a display-only programme (no evaluable
 *   rule) gets an honest note, never an invented plan.
 * No admission probabilities anywhere. No invented prices or dates:
 * task costs come only from the plan payload.
 */
export function PlanPanel({ programId, matchable }: { programId: string; matchable?: boolean }) {
  const { t, tf, locale, profile } = useApp();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState(false);
  const [waking, setWaking] = useState(false);
  const [busyTask, setBusyTask] = useState<string | null>(null);
  const [reassessing, setReassessing] = useState(false);
  const [lastReassess, setLastReassess] = useState<ReassessResult | null>(null);
  const [reassessError, setReassessError] = useState(false);
  const [reassessRateLimited, setReassessRateLimited] = useState(false);

  const hasProfile = Boolean(profile.track);
  const displayOnly = matchable === false;
  const taskById = new Map((plan?.tasks ?? []).map((task) => [task.task_id, task]));

  const gapLabel = (gap: PlanGap): string =>
    gap.evidence_class === 'hard_requirement'
      ? t('plan.gapHard')
      : gap.evidence_class === 'competitiveness'
        ? t('plan.gapCompetitiveness')
        : t('plan.gapConfirm');

  const statusLabel = (status: TaskStatus): string =>
    status === 'todo'
      ? t('plan.statusTodo')
      : status === 'in_progress'
        ? t('plan.statusInProgress')
        : status === 'done'
          ? t('plan.statusDone')
          : t('plan.statusToVerify');

  async function generate() {
    setPhase('loading');
    setErrorCode(null);
    setRateLimited(false);
    setWaking(false);
    setLastReassess(null);
    try {
      // Round 13: 40s per attempt (same as the round-10 chat fix), 90s
      // overall budget — a slow-but-healthy backend attempt is not
      // aborted mid-flight at the 25s default.
      const created = await createPlan(profile, programId, locale, {
        onRetry: () => setWaking(true),
        attemptTimeoutMs: 40_000,
        budgetMs: 90_000,
      });
      setPlan(created);
      setPhase('ready');
    } catch (err) {
      // Round 13: a 429 (AI budget exceeded) is a wait-a-minute, not a
      // broken plan — show the distinct message. A plan that does
      // arrive renders its template tasks with the template label
      // (see the ready branch below: ai_status 'unavailable' is not
      // an error state), so this branch is only for no response.
      if (isRateLimitedError(err)) {
        setErrorCode('RATE_LIMITED');
        setRateLimited(true);
      } else {
        setErrorCode(planErrorCode(err));
      }
      setPhase('error');
    }
  }

  async function advanceTask(taskId: string, from: TaskStatus) {
    const next: TaskStatus | null = from === 'todo' ? 'in_progress' : from === 'in_progress' ? 'done' : null;
    if (!plan || !next) return;
    setBusyTask(taskId);
    try {
      const updated = await updateTaskStatus(plan.plan_id, taskId, next);
      setPlan({ ...plan, tasks: plan.tasks.map((task) => (task.task_id === taskId ? { ...task, status: updated.status } : task)) });
    } catch {
      setErrorCode('TASK_UPDATE_FAILED');
      setPhase('error');
    } finally {
      setBusyTask(null);
    }
  }

  async function markToVerify(taskId: string) {
    if (!plan) return;
    setBusyTask(taskId);
    try {
      const updated = await updateTaskStatus(plan.plan_id, taskId, 'to_verify');
      setPlan({ ...plan, tasks: plan.tasks.map((task) => (task.task_id === taskId ? { ...task, status: updated.status } : task)) });
    } catch {
      setErrorCode('TASK_UPDATE_FAILED');
      setPhase('error');
    } finally {
      setBusyTask(null);
    }
  }

  async function reassess() {
    if (!plan) return;
    setReassessing(true);
    setReassessError(false);
    setReassessRateLimited(false);
    setWaking(false);
    try {
      const result = await reassessPlan(plan.plan_id, profile, {
        onRetry: () => setWaking(true),
        attemptTimeoutMs: 40_000,
        budgetMs: 90_000,
      });
      setLastReassess(result);
      // The reassessment may have rebuilt the task list (new gaps,
      // preserved statuses); refetch the stored plan to show it.
      setPlan(await getPlan(plan.plan_id));
    } catch (err) {
      if (isRateLimitedError(err)) {
        setReassessRateLimited(true);
      } else {
        setReassessError(true);
      }
    } finally {
      setReassessing(false);
    }
  }

  return (
    <div className="mt-3 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
      {/* Boundary line: visible in every state of this AI panel. */}
      <p className="rounded-lg bg-amber/20 p-3 text-sm font-semibold text-navy" role="note">{t('plan.boundary')}</p>

      {displayOnly && (
        <p className="mt-4 text-sm text-navy/80">{t('plan.notEvaluable')}</p>
      )}

      {!displayOnly && !hasProfile && (
        <div className="mt-4">
          <p className="text-sm text-navy/80">{t('plan.noProfile')}</p>
          <Link href="/wizard" className="btn-press mt-3 inline-block rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('plan.noProfileCta')}</Link>
        </div>
      )}

      {!displayOnly && hasProfile && phase === 'idle' && (
        <button type="button" onClick={generate} className="btn-press mt-4 rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('plan.generate')}</button>
      )}

      {!displayOnly && hasProfile && phase === 'loading' && (
        <p className="mt-4 text-sm font-semibold text-navy/70">{waking ? t('plan.waking') : t('plan.generating')}</p>
      )}

      {phase === 'error' && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">
          <p className="font-semibold">
            {rateLimited ? t('plan.rateLimited') : errorCode === 'PROGRAM_NOT_EVALUABLE' ? t('plan.notEvaluable') : errorCode === 'TASK_UPDATE_FAILED' ? t('plan.error') : t('plan.error')}
          </p>
          {errorCode && errorCode !== 'PROGRAM_NOT_EVALUABLE' && errorCode !== 'TASK_UPDATE_FAILED' && errorCode !== 'RATE_LIMITED' && (
            <p className="mt-1 text-xs">({errorCode})</p>
          )}
          <button type="button" onClick={generate} className="btn-press mt-3 rounded-full bg-amber px-4 py-2 font-semibold text-navy">{t('plan.generate')}</button>
        </div>
      )}

      {plan && phase === 'ready' && (
        <div className="mt-4">
          <section aria-labelledby="plan-gaps-title">
            <h3 id="plan-gaps-title" className="text-base font-bold">{t('plan.gapsTitle')}</h3>
            {plan.gap_assessment.gaps.length === 0 && (
              <p className="mt-2 text-sm text-navy/80">{t('plan.noGaps')}</p>
            )}
            <ul className="mt-2 space-y-3">
              {plan.gap_assessment.gaps.map((gap) => (
                <li key={gap.gap_id} className="rounded-xl border border-navy/10 bg-white p-4 shadow-sm">
                  <p>
                    <span className="rounded-full bg-navy px-2 py-0.5 text-xs font-bold text-white">{gapLabel(gap)}</span>{' '}
                    <span className="text-xs font-semibold text-teal-dark">{t('plan.verifiedLabel')}</span>
                  </p>
                  <p className="mt-2 text-sm text-navy/80">{gap.current_state}</p>
                  <p className="mt-1 text-sm text-navy/70">{gap.what_is_missing}</p>
                </li>
              ))}
            </ul>
          </section>

          <section className="mt-6" aria-labelledby="plan-tasks-title">
            <h3 id="plan-tasks-title" className="text-base font-bold">{t('plan.tasksTitle')}</h3>
            <p className="mt-1 text-sm font-semibold text-navy/70">
              {plan.ai_status === 'available' ? t('plan.aiSuggestionLabel') : t('plan.templateLabel')}
            </p>
            {plan.tasks.length === 0 && (
              <p className="mt-2 text-sm text-navy/80">{t('plan.noTasks')}</p>
            )}
            <ul className="mt-3 space-y-3">
              {plan.tasks.map((task) => (
                <li key={task.task_id} className="rounded-xl border border-navy/10 bg-white p-4 shadow-sm">
                  <p className="font-bold">{task.title}</p>
                  <p className="mt-1 text-xs font-semibold text-navy/60">
                    {statusLabel(task.status)} · {tf('plan.hoursPerWeek', { h: task.weekly_hours })} · {task.duration_weeks} {t('plan.weeksUnit')}
                  </p>
                  <p className="mt-2 text-sm text-navy/80">{task.rationale}</p>
                  <ol className="mt-2 list-decimal space-y-1 ps-5 text-sm text-navy/80">
                    {task.steps.map((step, i) => <li key={i}>{step}</li>)}
                  </ol>
                  {task.resources.length > 0 && (
                    <ul className="mt-2 space-y-1 text-sm">
                      {task.resources.map((res, i) => (
                        <li key={i}>
                          {res.url ? (
                            <a href={res.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{res.label}</a>
                          ) : (
                            <span className="text-navy/70">{res.label} — {t('plan.searchCriteria')}{res.search_criteria}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {task.status === 'done' && (
                    <p className="mt-2 rounded-lg bg-amber/20 p-2 text-sm font-semibold text-navy">{t('plan.taskDoneNote')}</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {task.status === 'todo' && (
                      <button type="button" disabled={busyTask === task.task_id} onClick={() => advanceTask(task.task_id, task.status)} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy disabled:opacity-50">{t('plan.startTask')}</button>
                    )}
                    {task.status === 'in_progress' && (
                      <button type="button" disabled={busyTask === task.task_id} onClick={() => advanceTask(task.task_id, task.status)} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy disabled:opacity-50">{t('plan.completeTask')}</button>
                    )}
                    {task.status !== 'to_verify' && (
                      <button type="button" disabled={busyTask === task.task_id} onClick={() => markToVerify(task.task_id)} className="btn-press rounded-full border border-navy/25 bg-white px-4 py-2 text-sm font-semibold text-navy disabled:opacity-50">{t('plan.markVerify')}</button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          {plan.weekly_schedule.weeks.length > 0 && (
            <section className="mt-6" aria-labelledby="plan-weekly-title">
              <h3 id="plan-weekly-title" className="text-base font-bold">{t('plan.weeklyTitle')}</h3>
              <ul className="mt-2 space-y-2">
                {plan.weekly_schedule.weeks.map((week) => (
                  <li key={week.week} className="rounded-xl border border-navy/10 bg-white p-3 text-sm shadow-sm">
                    <p className="font-semibold">{tf('plan.week', { n: week.week })} · {tf('plan.hoursPerWeek', { h: week.weekly_hours })}</p>
                    <ul className="mt-1 list-disc ps-5 text-navy/80">
                      {week.task_ids.map((id) => (
                        <li key={id}>{taskById.get(id)?.title ?? id}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="mt-6" aria-labelledby="plan-reassess-title">
            <h3 id="plan-reassess-title" className="text-base font-bold">{t('plan.reassessTitle')}</h3>
            <p className="mt-1 text-sm text-navy/70">{t('plan.reassessNote')}</p>
            <button type="button" disabled={reassessing} onClick={reassess} className="btn-press mt-3 rounded-full bg-navy px-5 py-2.5 font-semibold text-white disabled:opacity-50">
              {reassessing ? (waking ? t('plan.waking') : t('plan.reassessing')) : t('plan.reassess')}
            </button>
            {reassessError && <p className="mt-2 text-sm font-semibold text-red-800" role="alert">{t('plan.error')}</p>}
            {reassessRateLimited && <p className="mt-2 text-sm font-semibold text-red-800" role="alert">{t('plan.rateLimited')}</p>}
            {lastReassess && (
              <div className="mt-3 rounded-xl border border-navy/10 bg-white p-4 shadow-sm">
                <p className="font-semibold">
                  {t('plan.changesTitle')} <span className="text-xs font-semibold text-teal-dark">{t('plan.verifiedLabel')}</span>
                </p>
                {lastReassess.changes.length === 0 ? (
                  <p className="mt-1 text-sm text-navy/80">{t('plan.noChanges')}</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-sm text-navy/80">
                    {lastReassess.changes.map((change, i) => (
                      <li key={i}>{change.rule_id}: {change.old_status} → {change.new_status}</li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-sm text-navy/70">{lastReassess.note}</p>
              </div>
            )}
          </section>

          {(plan.assumptions.length > 0 || plan.limitations.length > 0) && (
            <section className="mt-6 text-sm text-navy/70" aria-labelledby="plan-limits-title">
              <h3 id="plan-limits-title" className="text-base font-bold text-navy">{t('plan.limitationsTitle')}</h3>
              <ul className="mt-2 list-disc space-y-1 ps-5">
                {[...plan.assumptions, ...plan.limitations].map((line, i) => <li key={i}>{line}</li>)}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
