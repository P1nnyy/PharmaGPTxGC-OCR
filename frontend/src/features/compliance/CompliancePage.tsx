import React, { useCallback, useEffect, useState } from 'react';
import { Ban, FileJson, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';

import { complianceApi } from './api';
import { Card, NextActionBanner, Note, StageTimeline, UrgencyChip } from './components/Pieces';
import type {
  CalendarReport, FilingRow, RemindersReport, TimeBarReport, TimelineReport
} from './types';

type TabId = 'calendar' | 'timeline' | 'time-bar' | 'evidence' | 'reminders';

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'calendar', label: 'Calendar' },
  { id: 'timeline', label: 'This period' },
  { id: 'time-bar', label: 'Time bar' },
  { id: 'evidence', label: 'Filing evidence' },
  { id: 'reminders', label: 'Reminders' }
];

const prettyPeriod = (period: string) => `${period.slice(0, 2)}/${period.slice(2)}`;

export const CompliancePage: React.FC = () => {
  const [tab, setTab] = useState<TabId>('calendar');
  const [calendar, setCalendar] = useState<CalendarReport | null>(null);
  const [timeline, setTimeline] = useState<TimelineReport | null>(null);
  const [timeBar, setTimeBar] = useState<TimeBarReport | null>(null);
  const [filings, setFilings] = useState<FilingRow[]>([]);
  const [reminders, setReminders] = useState<RemindersReport | null>(null);
  const [payload, setPayload] = useState<{ arn: string; body: unknown } | null>(null);

  const [period, setPeriod] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ return_type: 'GSTR1', arn: '', filed_at: '', note: '' });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cal = await complianceApi.calendar();
      setCalendar(cal);
      const target = period || cal.next_action?.period ||
        cal.items.find((i) => !i.is_done && i.is_filing)?.period || cal.items[0]?.period;
      if (target) {
        if (!period) setPeriod(target);
        setTimeline(await complianceApi.timeline(target));
      }
      setTimeBar(await complianceApi.timeBar());
      setFilings((await complianceApi.filings()).rows);
      setReminders(await complianceApi.reminders(true));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the calendar.');
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { void load(); }, [load]);

  const recordFiling = async () => {
    if (!period) return;
    setError(null);
    try {
      await complianceApi.recordFiling({
        period,
        return_type: form.return_type,
        arn: form.arn,
        filed_at: form.filed_at || new Date().toISOString(),
        covers_months: timeline?.covers_months,
        note: form.note || undefined
      });
      setForm({ return_type: 'GSTR1', arn: '', filed_at: '', note: '' });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not record that filing.');
    }
  };

  const toggleReminders = async (enabled: boolean) => {
    try {
      await complianceApi.setReminders({
        enabled,
        days_before: reminders?.settings.days_before
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save that setting.');
    }
  };

  const showPayload = async (filingId: string) => {
    try {
      const found = await complianceApi.filingPayload(filingId);
      setPayload({ arn: found.arn, body: found.payload });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not open that payload.');
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#0f172a]">Compliance calendar</h1>
          <p className="text-sm text-gray-500 mt-1">
            {calendar
              ? `${calendar.label} · ${calendar.effective_filing_frequency === 'QUARTERLY'
                  ? 'quarterly filer (QRMP)' : 'monthly filer'}`
              : 'What is due, and when.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm bg-white hover:bg-gray-50"
        >
          <RefreshCw size={14} aria-hidden /> Refresh
        </button>
      </header>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" aria-hidden /> Working out what is due…
        </p>
      )}
      {error && <Note tone="bad">{error}</Note>}

      {calendar && !loading && (
        <>
          <NextActionBanner action={calendar.next_action} />

          {!calendar.frequency_is_set && (
            <Note tone="warn">
              Nobody has said whether this shop files monthly or quarterly, so this
              calendar assumes monthly. A QRMP shop's dates are completely
              different — set the filing frequency in settings before relying on
              any of this.
            </Note>
          )}

          <Note tone="info">
            <strong>This app prepares and tracks. It does not file.</strong> File on
            the GST portal, then record the ARN here so the return can be explained
            later.
          </Note>

          <nav className="flex flex-wrap gap-1 border-b border-gray-200">
            {TABS.map((entry) => (
              <button
                key={entry.id} type="button" onClick={() => setTab(entry.id)}
                className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
                  tab === entry.id
                    ? 'border-[#1b5dfc] text-[#1b5dfc]'
                    : 'border-transparent text-gray-500 hover:text-[#0f172a]'
                }`}
              >
                {entry.label}
                {entry.id === 'time-bar' && timeBar?.has_anything && (
                  <span className="ml-1.5 text-[10px] font-bold text-[#8f1d1d]">
                    {timeBar.already_barred_count + timeBar.closing_soon_count}
                  </span>
                )}
              </button>
            ))}
          </nav>

          {tab === 'calendar' && (
            <Card
              title={`${calendar.label} schedule`}
              subtitle={
                calendar.effective_filing_frequency === 'QUARTERLY'
                  ? 'A QRMP shop pays monthly through PMT-06 and files its returns once a quarter.'
                  : 'Monthly GSTR-1 and GSTR-3B, with 2B arriving in between.'
              }
            >
              <div className="overflow-x-auto -mx-2 px-2">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="text-[11px] uppercase tracking-wide text-gray-400 text-left">
                      <th className="font-semibold py-2 pr-4">Due</th>
                      <th className="font-semibold py-2 pr-4">Return</th>
                      <th className="font-semibold py-2 pr-4">Period</th>
                      <th className="font-semibold py-2 pr-4">Status</th>
                      <th className="font-semibold py-2 pr-4">ARN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calendar.items.map((item) => (
                      <tr key={`${item.period}-${item.kind}`}
                          className={item.is_done ? 'opacity-60' : ''}>
                        <td className="py-2 pr-4 border-t border-gray-100 whitespace-nowrap">
                          {item.due_date}
                        </td>
                        <td className="py-2 pr-4 border-t border-gray-100">
                          {item.label}
                          {item.is_optional && (
                            <span className="ml-1.5 text-[10px] text-gray-400">optional</span>
                          )}
                        </td>
                        <td className="py-2 pr-4 border-t border-gray-100 whitespace-nowrap">
                          {item.covers_months.length > 1
                            ? `${prettyPeriod(item.covers_months[0])}–${prettyPeriod(item.covers_months[item.covers_months.length - 1])}`
                            : prettyPeriod(item.period)}
                        </td>
                        <td className="py-2 pr-4 border-t border-gray-100">
                          <UrgencyChip urgency={item.urgency} days={item.days_remaining} />
                        </td>
                        <td className="py-2 pr-4 border-t border-gray-100 font-mono text-[11px] text-gray-500">
                          {item.arn ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'timeline' && timeline && (
            <Card
              title={`${timeline.period_label} — where it stands`}
              subtitle="Each stage shows what is holding it up, and links to where that is fixed."
              action={
                <select
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  className="rounded-lg border border-[#e2e8f0] px-2 py-1.5 text-sm bg-white"
                  aria-label="Period"
                >
                  {[...new Set(calendar.items.map((i) => i.period))].map((p) => (
                    <option key={p} value={p}>{prettyPeriod(p)}</option>
                  ))}
                </select>
              }
            >
              {timeline.is_nil_return && (
                <div className="mb-5">
                  <Note tone="info">
                    Nothing was supplied in this period. A nil return is still due —
                    the late fee accrues whether or not there was anything to report.
                  </Note>
                </div>
              )}
              <StageTimeline stages={timeline.stages} />
            </Card>
          )}

          {tab === 'time-bar' && timeBar && (
            <div className="flex flex-col gap-6">
              <Note tone={timeBar.has_anything ? 'bad' : 'good'}>
                <strong>The three-year bar.</strong> {timeBar.rule}
              </Note>

              {!timeBar.has_anything && (
                <Card title="Nothing at risk">
                  <p className="text-sm text-gray-600">
                    No unfiled return is approaching the three-year limit.
                  </p>
                </Card>
              )}

              {timeBar.already_barred_count > 0 && (
                <Card
                  title="Can no longer be filed"
                  subtitle="These are past the limit. There is no route back — the credit and liability in them are frozen where they stand."
                >
                  <ul className="flex flex-col gap-2">
                    {timeBar.already_barred.map((item) => (
                      <li key={`${item.period}-${item.kind}`}
                          className="flex items-center gap-2.5 text-sm">
                        <Ban size={14} className="text-[#6b1d1d] shrink-0" aria-hidden />
                        <span className="font-medium">{item.label.split(' — ')[0]}</span>
                        <span className="text-gray-500">{prettyPeriod(item.period)}</span>
                        <span className="text-[11px] text-gray-400">
                          due {item.due_date} · barred since {item.barred_on}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {timeBar.closing_soon_count > 0 && (
                <Card
                  title="Closing soon"
                  subtitle="Still fileable, but not for much longer. Soonest first."
                >
                  <ul className="flex flex-col gap-2">
                    {timeBar.closing_soon.map((item) => (
                      <li key={`${item.period}-${item.kind}`}
                          className="flex flex-wrap items-center gap-2.5 text-sm">
                        <span className="font-semibold text-[#8f1d1d] tabular-nums w-16">
                          {item.days_until_barred}d left
                        </span>
                        <span className="font-medium">{item.label.split(' — ')[0]}</span>
                        <span className="text-gray-500">{prettyPeriod(item.period)}</span>
                        <span className="text-[11px] text-gray-400">
                          can be filed until {item.barred_on}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          )}

          {tab === 'evidence' && (
            <div className="flex flex-col gap-6">
              <Card
                title="Record a filing"
                subtitle="After filing on the portal, paste the ARN here. The payload stored when the period was closed is kept with it."
              >
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <label className="flex flex-col gap-1 text-xs text-gray-600">
                    Return
                    <select
                      value={form.return_type}
                      onChange={(e) => setForm({ ...form, return_type: e.target.value })}
                      className="rounded-lg border border-[#e2e8f0] px-2 py-2 text-sm bg-white"
                    >
                      <option value="GSTR1">GSTR-1</option>
                      <option value="GSTR3B">GSTR-3B</option>
                      <option value="PMT06">PMT-06</option>
                      <option value="IFF">IFF</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-gray-600">
                    ARN
                    <input
                      value={form.arn}
                      onChange={(e) => setForm({ ...form, arn: e.target.value })}
                      placeholder="AA270926000001X"
                      className="rounded-lg border border-[#e2e8f0] px-2 py-2 text-sm font-mono"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-gray-600">
                    Filed at
                    <input
                      type="datetime-local"
                      value={form.filed_at}
                      onChange={(e) => setForm({ ...form, filed_at: e.target.value })}
                      className="rounded-lg border border-[#e2e8f0] px-2 py-2 text-sm"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-gray-600">
                    Note
                    <input
                      value={form.note}
                      onChange={(e) => setForm({ ...form, note: e.target.value })}
                      className="rounded-lg border border-[#e2e8f0] px-2 py-2 text-sm"
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => void recordFiling()}
                  disabled={!form.arn.trim()}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white bg-[#1b5dfc] hover:bg-[#1749c8] disabled:bg-gray-300"
                >
                  <ShieldCheck size={14} aria-hidden />
                  Record for {period ? prettyPeriod(period) : '—'}
                </button>
              </Card>

              <Card
                title="Filing evidence"
                subtitle="The ARN, the moment it was filed, and the exact JSON submitted. Any two without the third is an assertion rather than a record."
              >
                {filings.length === 0 ? (
                  <p className="text-sm text-gray-500">Nothing recorded yet.</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {filings.map((row) => (
                      <li key={row.id}
                          className="flex flex-wrap items-center gap-3 text-sm py-2 border-t border-gray-100 first:border-0">
                        <span className="font-medium w-20">{row.return_type}</span>
                        <span className="text-gray-500 w-16">{prettyPeriod(row.period)}</span>
                        <span className="font-mono text-xs">{row.arn}</span>
                        <span className="text-[11px] text-gray-400">
                          {row.filed_at?.slice(0, 16).replace('T', ' ')}
                        </span>
                        {row.has_payload && (
                          <button
                            type="button"
                            onClick={() => void showPayload(row.id)}
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1b5dfc] hover:underline"
                          >
                            <FileJson size={11} aria-hidden /> what was sent
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              {payload && (
                <Card
                  title={`What was sent under ${payload.arn}`}
                  action={
                    <button type="button" onClick={() => setPayload(null)}
                            className="text-xs text-gray-500 hover:text-[#0f172a]">
                      Close
                    </button>
                  }
                >
                  <pre className="text-[11px] bg-gray-50 rounded-lg p-4 overflow-auto max-h-96">
                    {JSON.stringify(payload.body, null, 2)}
                  </pre>
                </Card>
              )}
            </div>
          )}

          {tab === 'reminders' && reminders && (
            <div className="flex flex-col gap-6">
              <Card
                title="Reminders"
                subtitle="Off by default. A calendar that sends something every day is one people learn to dismiss without reading."
                action={
                  <button
                    type="button"
                    onClick={() => void toggleReminders(!reminders.settings.enabled)}
                    className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                      reminders.settings.enabled
                        ? 'border border-[#e2e8f0] bg-white hover:bg-gray-50'
                        : 'text-white bg-[#1b5dfc] hover:bg-[#1749c8]'
                    }`}
                  >
                    {reminders.settings.enabled ? 'Turn off' : 'Turn on'}
                  </button>
                }
              >
                {reminders.note && <Note tone="info">{reminders.note}</Note>}
                <p className="text-sm text-gray-600 mt-4">
                  Reminders start{' '}
                  <strong>{reminders.settings.days_before.join(', ')}</strong> days before
                  each due date and get more insistent as it approaches. A return
                  approaching the three-year bar overrides these and always warns.
                </p>
              </Card>

              {reminders.due.length > 0 && (
                <Card title="Would fire today">
                  <ul className="flex flex-col gap-2">
                    {reminders.due.map((r) => (
                      <li key={r.key} className="text-sm flex gap-2.5 items-start">
                        <span className="text-[10px] font-bold uppercase tracking-wider w-16 shrink-0 mt-0.5"
                              style={{ color: r.tone === 'FINAL' || r.tone === 'OVERDUE' ? '#8f1d1d' : '#7a5205' }}>
                          {r.tone}
                        </span>
                        <span className="leading-snug">{r.message}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {!reminders.settings.enabled && reminders.preview && (
                <Card
                  title="What you would receive"
                  subtitle="The real volume over the next six weeks, so you can decide before turning it on rather than after."
                >
                  {reminders.preview.length === 0 ? (
                    <p className="text-sm text-gray-500">Nothing in the next six weeks.</p>
                  ) : (
                    <>
                      <p className="text-sm text-gray-600 mb-3">
                        <strong>{reminders.preview.length}</strong> reminders over 45 days.
                      </p>
                      <ul className="flex flex-col gap-1 max-h-64 overflow-auto">
                        {reminders.preview.slice(0, 40).map((r, i) => (
                          <li key={`${r.key}-${i}`} className="text-[11px] text-gray-600 flex gap-2">
                            <span className="text-gray-400 w-20 shrink-0">{r.would_fire_on}</span>
                            <span>{r.message}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
