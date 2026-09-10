import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight } from 'lucide-react';

import { Amount, money } from './Primitives';
import type { CrossCheck, Drill } from '../types';

/**
 * The reconciliation banner, shown above every report.
 *
 * It sits at the top rather than at the bottom because it changes how the
 * numbers below it should be read: a pack that does not reconcile is a pack
 * whose figures are not yet safe to file, and finding that out after scrolling
 * through six reports is finding it out too late.
 *
 * When everything agrees it collapses to a single line. A green banner that
 * takes up a third of the screen trains people to scroll past the place the
 * red one will eventually appear.
 */
export const CrossCheckBanner: React.FC<{
  checks: CrossCheck[];
  onDrill: (drill: Drill, label: string) => void;
}> = ({ checks, onDrill }) => {
  const failing = checks.filter((c) => !c.agrees);
  const [expanded, setExpanded] = useState(failing.length > 0);

  if (checks.length === 0) return null;

  const tone = failing.length
    ? { border: '#f3c9c9', background: '#fdecec', color: '#8f1d1d' }
    : { border: '#c6e9d4', background: '#eaf7f0', color: '#1c6b41' };

  return (
    <section
      className="rounded-xl border print:border-gray-300"
      style={{ borderColor: tone.border, background: tone.background }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        {failing.length ? (
          <AlertCircle size={16} style={{ color: tone.color }} aria-hidden />
        ) : (
          <CheckCircle2 size={16} style={{ color: tone.color }} aria-hidden />
        )}
        <span className="text-sm font-semibold flex-1" style={{ color: tone.color }}>
          {failing.length === 0
            ? `All ${checks.length} cross-checks reconcile.`
            : `${failing.length} of ${checks.length} cross-checks do not reconcile.`}
        </span>
        <span className="print:hidden" style={{ color: tone.color }}>
          {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3">
          {checks.map((check) => (
            <div
              key={check.code}
              className="rounded-lg bg-white/70 border p-3"
              style={{ borderColor: check.agrees ? '#dcece4' : '#f3c9c9' }}
            >
              <div className="flex items-baseline justify-between gap-3 flex-wrap">
                <strong className="text-xs font-bold text-[#0f172a]">{check.label}</strong>
                <span
                  className="text-xs font-semibold tabular-nums"
                  style={{ color: check.agrees ? '#1c6b41' : '#8f1d1d' }}
                >
                  {check.agrees ? 'reconciles' : `off by ${money(Math.abs(check.difference))}`}
                </span>
              </div>

              <div className="mt-2 grid sm:grid-cols-2 gap-2 text-xs">
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500">{check.left.label}</span>
                  <Amount figure={check.left} onDrill={onDrill} label={check.left.label} />
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500">{check.right.label}</span>
                  <Amount figure={check.right} onDrill={onDrill} label={check.right.label} />
                </div>
              </div>

              <p className="text-[11px] text-gray-600 mt-2 leading-relaxed">{check.explanation}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};
