import React from 'react';
import {
  AlertCircle, AlertTriangle, ArrowRight, Ban, Check, CheckCircle2,
  Circle, Clock, ExternalLink, Info, Lock
} from 'lucide-react';
import { Link } from 'react-router-dom';

import type { ScheduleItem, Stage, Urgency } from '../types';

/** Urgency is the only thing carrying colour here, and it always carries a
 *  word and an icon with it — two of these hues sit below 3:1 on white. */
export const URGENCY = {
  TIME_BARRED: { ink: '#6b1d1d', tint: '#f7e4e4', label: 'Cannot be filed', Icon: Ban },
  OVERDUE: { ink: '#8f1d1d', tint: '#fdecec', label: 'Overdue', Icon: AlertCircle },
  URGENT: { ink: '#8f1d1d', tint: '#fdecec', label: 'Due now', Icon: AlertCircle },
  SOON: { ink: '#7a5205', tint: '#fdf3e0', label: 'Due soon', Icon: AlertTriangle },
  SCHEDULED: { ink: '#475569', tint: '#f1f5f9', label: 'Scheduled', Icon: Clock },
  DONE: { ink: '#1c6b41', tint: '#eaf7f0', label: 'Filed', Icon: CheckCircle2 },
  INFORMATIONAL: { ink: '#123c9e', tint: '#eaf0ff', label: 'Arrives on', Icon: Info }
} as const;

export const Card: React.FC<{
  title?: string; subtitle?: string; action?: React.ReactNode;
  children: React.ReactNode; className?: string;
}> = ({ title, subtitle, action, children, className = '' }) => (
  <section className={`bg-white rounded-2xl border border-[#e2e8f0] shadow-sm ${className}`}>
    {(title || action) && (
      <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-gray-100">
        <div>
          {title && <h3 className="text-sm font-bold text-[#0f172a]">{title}</h3>}
          {subtitle && <p className="text-xs text-gray-500 mt-0.5 max-w-3xl">{subtitle}</p>}
        </div>
        {action}
      </header>
    )}
    <div className="p-6">{children}</div>
  </section>
);

export const Note: React.FC<{
  tone?: 'info' | 'warn' | 'bad' | 'good'; children: React.ReactNode;
}> = ({ tone = 'info', children }) => {
  const styles = {
    info: { border: '#cfe0ff', background: '#eaf0ff', color: '#123c9e', Icon: Info },
    warn: { border: '#f5dfae', background: '#fdf3e0', color: '#7a5205', Icon: AlertTriangle },
    bad: { border: '#f3c9c9', background: '#fdecec', color: '#8f1d1d', Icon: AlertCircle },
    good: { border: '#c6e9d4', background: '#eaf7f0', color: '#1c6b41', Icon: CheckCircle2 }
  } as const;
  const { border, background, color, Icon } = styles[tone];
  return (
    <div className="rounded-xl border p-4 text-sm flex gap-2.5 items-start"
         style={{ borderColor: border, background, color }}>
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
};

export const UrgencyChip: React.FC<{ urgency: Urgency; days?: number }> = ({ urgency, days }) => {
  const tone = URGENCY[urgency] ?? URGENCY.SCHEDULED;
  const Icon = tone.Icon;
  const suffix =
    urgency === 'DONE' || urgency === 'TIME_BARRED' || days === undefined ? '' :
    days < 0 ? ` · ${Math.abs(days)}d late` :
    days === 0 ? ' · today' : ` · ${days}d`;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap"
          style={{ background: tone.tint, color: tone.ink }}>
      <Icon size={12} aria-hidden />{tone.label}{suffix}
    </span>
  );
};

/**
 * The next action. One thing, with days remaining.
 *
 * Deliberately a single item rather than a list. A home screen showing five
 * things due is one somebody skims; one showing the next thing is one somebody
 * acts on. When the reason is the three-year bar it is styled hardest, because
 * that is the only deadline here with no way back from it.
 */
export const NextActionBanner: React.FC<{
  action: ScheduleItem | null;
  note?: string | null;
  compact?: boolean;
}> = ({ action, note, compact }) => {
  if (!action) {
    return (
      <div className="rounded-xl border border-[#c6e9d4] bg-[#eaf7f0] p-4 flex gap-2.5 items-start">
        <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-[#1c6b41]" aria-hidden />
        <p className="text-sm text-[#1c6b41] leading-relaxed">
          {note ?? 'Nothing is outstanding.'}
        </p>
      </div>
    );
  }

  const barred = action.reason === 'TIME_BAR';
  const late = action.days_remaining < 0;
  const tone = barred
    ? { border: '#e0aaaa', background: '#f7e4e4', ink: '#6b1d1d' }
    : late
      ? { border: '#f3c9c9', background: '#fdecec', ink: '#8f1d1d' }
      : { border: '#cfe0ff', background: '#eaf0ff', ink: '#123c9e' };

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: tone.border, background: tone.background }}>
      <div className="flex items-start gap-3">
        {barred ? <Ban size={18} className="mt-0.5 shrink-0" style={{ color: tone.ink }} aria-hidden />
                : <Clock size={18} className="mt-0.5 shrink-0" style={{ color: tone.ink }} aria-hidden />}
        <div className="flex-1 min-w-0">
          <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: tone.ink }}>
            Next action
          </span>
          <p className="text-sm font-semibold mt-0.5 leading-snug" style={{ color: tone.ink }}>
            {action.headline}
          </p>
          {!compact && (
            <p className="text-[11px] mt-1.5" style={{ color: tone.ink, opacity: 0.85 }}>
              Due {action.due_date}
              {action.blocking_count > 0 && (
                <> · {action.blocking_count} item
                  {action.blocking_count === 1 ? '' : 's'} blocking it</>
              )}
              {action.barred_on && !barred && <> · can be filed until {action.barred_on}</>}
            </p>
          )}
        </div>
        <Link
          to="/compliance"
          className="shrink-0 inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold bg-white/70 hover:bg-white"
          style={{ color: tone.ink }}
        >
          Open <ArrowRight size={13} aria-hidden />
        </Link>
      </div>
    </div>
  );
};

const STAGE_ICON = {
  DONE: { Icon: Check, ink: '#1c6b41', ring: '#c6e9d4', fill: '#eaf7f0' },
  CURRENT: { Icon: Circle, ink: '#1b5dfc', ring: '#1b5dfc', fill: '#ffffff' },
  BLOCKED: { Icon: AlertCircle, ink: '#8f1d1d', ring: '#f3c9c9', fill: '#fdecec' },
  PENDING: { Icon: Circle, ink: '#94a3b8', ring: '#e2e8f0', fill: '#ffffff' },
  NOT_APPLICABLE: { Icon: Lock, ink: '#94a3b8', ring: '#e2e8f0', fill: '#f8fafc' }
} as const;

/** The eight stages, with each one's blockers attached to it. */
export const StageTimeline: React.FC<{ stages: Stage[] }> = ({ stages }) => (
  <ol className="flex flex-col">
    {stages.map((stage, index) => {
      const look = STAGE_ICON[stage.state] ?? STAGE_ICON.PENDING;
      const Icon = look.Icon;
      const last = index === stages.length - 1;
      return (
        <li key={stage.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              className="w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0"
              style={{ borderColor: look.ring, background: look.fill, color: look.ink }}
            >
              <Icon size={12} aria-hidden />
            </span>
            {!last && <span className="w-px flex-1 my-1" style={{ background: '#e2e8f0' }} />}
          </div>

          <div className={`flex-1 ${last ? 'pb-0' : 'pb-6'}`}>
            <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <strong
                className="text-sm"
                style={{ color: stage.state === 'PENDING' ? '#94a3b8' : '#0f172a' }}
              >
                {stage.label}
              </strong>
              {stage.state === 'CURRENT' && (
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#1b5dfc]">
                  do this next
                </span>
              )}
              {stage.state === 'BLOCKED' && stage.blocking_count > 0 && (
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#8f1d1d]">
                  {stage.blocking_count} blocking
                </span>
              )}
              {stage.completed_at && (
                <span className="text-[11px] text-gray-400">{stage.completed_at.slice(0, 10)}</span>
              )}
            </div>

            <p className="text-xs text-gray-600 mt-1 leading-relaxed max-w-2xl">{stage.detail}</p>

            {stage.blocking.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1.5">
                {stage.blocking.map((item) => (
                  <li key={item.id} className="text-[11px] text-[#8f1d1d] flex gap-1.5 items-start">
                    <AlertCircle size={11} className="mt-0.5 shrink-0" aria-hidden />
                    <span className="leading-snug">{item.message}</span>
                  </li>
                ))}
              </ul>
            )}

            {stage.warnings.length > 0 && (
              <ul className="mt-1.5 flex flex-col gap-1">
                {stage.warnings.slice(0, 3).map((item) => (
                  <li key={item.id} className="text-[11px] text-[#7a5205] flex gap-1.5 items-start">
                    <AlertTriangle size={11} className="mt-0.5 shrink-0" aria-hidden />
                    <span className="leading-snug">{item.message}</span>
                  </li>
                ))}
              </ul>
            )}

            {stage.link && stage.state !== 'PENDING' && stage.state !== 'DONE' && (
              <Link
                to={stage.link}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1b5dfc] hover:underline mt-2"
              >
                Go there <ExternalLink size={10} aria-hidden />
              </Link>
            )}
          </div>
        </li>
      );
    })}
  </ol>
);
