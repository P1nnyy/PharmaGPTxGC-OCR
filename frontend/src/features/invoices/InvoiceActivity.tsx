/**
 * One invoice's history: who uploaded it, who changed what, who approved it.
 *
 * The question this answers is asked after the fact - "who set the tax to
 * that, and what was it before?" - so every entry names a person, a time, and
 * where a value moved from. An entry that only said "the invoice was updated"
 * would be a record of nothing.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Check, FileUp, Loader2, PencilLine, Trash2 } from 'lucide-react';

interface ActivityEvent {
  id: string;
  at: string | null;
  actor_name: string | null;
  actor_email: string | null;
  action: string;
  summary: string | null;
  details: string[];
}

const ICONS: Record<string, React.ElementType> = {
  'invoice.created': FileUp,
  'invoice.updated': PencilLine,
  'invoice.verified': Check,
  'invoice.deleted': Trash2
};

const TONE: Record<string, string> = {
  'invoice.created': 'bg-blue-50 text-[#1b5dfc] border-blue-100',
  'invoice.updated': 'bg-amber-50 text-amber-600 border-amber-100',
  'invoice.verified': 'bg-green-50 text-green-600 border-green-100',
  'invoice.deleted': 'bg-red-50 text-red-600 border-red-100'
};

const LABELS: Record<string, string> = {
  'invoice.created': 'Uploaded',
  'invoice.updated': 'Edited',
  'invoice.verified': 'Approved',
  'invoice.deleted': 'Deleted'
};

const when = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
};

/** "CGST: 178.16 -> 89.08" as three aligned parts. */
const parseChange = (detail: string): { field: string; from: string; to: string } | null => {
  const m = /^(.+?):\s*(.*?)\s*->\s*(.*)$/.exec(detail);
  return m ? { field: m[1], from: m[2], to: m[3] } : null;
};

export const InvoiceActivity: React.FC<{ invoiceId: string }> = ({ invoiceId }) => {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/invoices/${encodeURIComponent(invoiceId)}/activity`);
      if (!r.ok) throw new Error('Could not load this invoice’s activity.');
      const d = await r.json();
      setEvents(d.events || []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load activity.');
    } finally {
      setLoading(false);
    }
  }, [invoiceId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6 text-xs text-gray-400">
        <Loader2 size={13} className="animate-spin mr-2" /> Loading activity...
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
        {error}
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <p className="text-[11px] text-gray-400 py-4 text-center">
        No recorded activity. Invoices uploaded before activity tracking have none.
      </p>
    );
  }

  return (
    <ol className="relative space-y-0">
      {events.map((event, index) => {
        const Icon = ICONS[event.action] || PencilLine;
        const changes = (event.details || [])
          .map(parseChange)
          .filter((c): c is { field: string; from: string; to: string } => c !== null);
        const isLast = index === events.length - 1;

        return (
          <li key={event.id} className="relative flex gap-3 pb-4">
            {/* The spine, stopping at the last entry so it does not trail
                into empty space. */}
            {!isLast && (
              <span className="absolute left-[13px] top-7 bottom-0 w-px bg-slate-200" aria-hidden="true" />
            )}

            <span className={`relative z-10 shrink-0 w-[27px] h-[27px] rounded-full border flex items-center justify-center ${
              TONE[event.action] || 'bg-slate-50 text-slate-500 border-slate-200'
            }`}>
              <Icon size={13} />
            </span>

            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-xs font-semibold text-[#0f172a]">
                  {event.actor_name || event.actor_email || 'Unknown user'}
                </span>
                <span className="text-[10px] font-bold uppercase tracking-wide text-gray-400">
                  {LABELS[event.action] || event.action.replace(/[._]/g, ' ')}
                </span>
                <span className="text-[10px] text-gray-400 ml-auto whitespace-nowrap">
                  {when(event.at)}
                </span>
              </div>

              {event.summary && (
                <p className="text-[11px] text-gray-500 mt-0.5">{event.summary}</p>
              )}

              {changes.length > 0 && (
                <div className="mt-2 rounded-lg border border-slate-200 overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <tbody className="divide-y divide-slate-100">
                      {changes.map((c, i) => (
                        <tr key={i} className="bg-[#f8fafc]">
                          <td className="px-2.5 py-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-wide w-[38%]">
                            {c.field}
                          </td>
                          <td className="px-2 py-1.5 text-[11px] text-right font-mono text-red-600 line-through w-[27%]">
                            {c.from}
                          </td>
                          <td className="px-2 py-1.5 text-[11px] text-right font-mono text-green-700 font-semibold w-[27%]">
                            {c.to}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
};

export default InvoiceActivity;
