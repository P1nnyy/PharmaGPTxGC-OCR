/**
 * The activity log.
 *
 * Read-only by construction - there is no edit or delete here because an
 * audit trail that can be tidied answers a weaker question than the one it
 * exists for. Paging is by timestamp rather than offset, so a new event
 * arriving mid-scroll cannot shift the page under the reader.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { History, Loader2 } from 'lucide-react';
import { apiClient } from '../../api/client';

interface Event {
  id: string;
  at: string | null;
  actor_email: string | null;
  actor_name: string | null;
  action: string;
  summary: string | null;
  details: string[];
}

// Sign-in failures are the ones worth spotting in a wall of text.
const TONE: Record<string, string> = {
  'auth.sign_in_failed': 'bg-red-50 text-red-700 border-red-200',
  'invoice.deleted': 'bg-red-50 text-red-700 border-red-200',
  'cache.cleared': 'bg-amber-50 text-amber-700 border-amber-200',
  'user.deactivated': 'bg-amber-50 text-amber-700 border-amber-200',
  'user.role_changed': 'bg-amber-50 text-amber-700 border-amber-200'
};

const when = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

export const ActivityPanel: React.FC = () => {
  const [events, setEvents] = useState<Event[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (action: string) => {
    setLoading(true);
    try {
      const d = await apiClient.getAudit({ limit: 50, action: action || undefined });
      setEvents(d.events || []);
      setActions(d.actions || []);
      setNextBefore(d.next_before || null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load the activity log.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(filter); }, [filter, load]);

  const loadMore = async () => {
    if (!nextBefore) return;
    setMore(true);
    try {
      const d = await apiClient.getAudit({
        limit: 50, action: filter || undefined, before: nextBefore
      });
      setEvents((prev) => [...prev, ...(d.events || [])]);
      setNextBefore(d.next_before || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load more.');
    } finally {
      setMore(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 pb-3">
        <div>
          <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
            <History size={15} className="text-[#1b5dfc]" />
            <span>Activity</span>
          </h3>
          <p className="text-gray-500 text-[11px] mt-0.5">
            Who did what, and when. Written once and never edited.
          </p>
        </div>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 text-[11px] focus:outline-none focus:border-blue-500 shrink-0"
        >
          <option value="">All activity</option>
          {actions.map((a) => (
            <option key={a} value={a}>{a.replace(/[._]/g, ' ')}</option>
          ))}
        </select>
      </div>

      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center text-xs text-gray-400 py-8">
          <Loader2 size={14} className="animate-spin mr-2" /> Loading activity...
        </div>
      ) : events.length === 0 ? (
        <p className="text-center py-10 text-gray-400 text-xs font-medium">
          Nothing recorded yet.
        </p>
      ) : (
        <ul className="divide-y divide-[#e2e8f0]">
          {events.map((e) => (
            <li key={e.id} className="py-2.5 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs text-[#0f172a]">
                  {e.summary || e.action.replace(/[._]/g, ' ')}
                </p>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  {e.actor_email || 'unknown'} · {when(e.at)}
                  {e.details?.length > 0 && ` · ${e.details.join(' · ')}`}
                </p>
              </div>
              <span className={`px-2 py-0.5 rounded text-[9px] font-bold border whitespace-nowrap shrink-0 ${
                TONE[e.action] || 'bg-slate-50 text-slate-600 border-slate-200'
              }`}>
                {e.action.replace(/[._]/g, ' ')}
              </span>
            </li>
          ))}
        </ul>
      )}

      {nextBefore && (
        <button
          onClick={loadMore}
          disabled={more}
          className="w-full border border-gray-200 hover:bg-gray-50 disabled:opacity-60 text-[#0f172a] font-semibold rounded-lg py-2 text-[11px] transition-colors"
        >
          {more ? 'Loading...' : 'Load older activity'}
        </button>
      )}
    </div>
  );
};

export default ActivityPanel;
