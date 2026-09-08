/**
 * Invitations.
 *
 * No email is sent - the link is handed back here and shared over whatever
 * channel the admin already trusts. The token appears exactly once, at
 * creation, so the link is shown prominently and cannot be recovered later:
 * withdrawing and re-inviting is the way to get another.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Copy, Loader2, Mail, Trash2 } from 'lucide-react';
import { apiClient } from '../../api/client';

const ROLES = [
  { id: 'pharmacist', label: 'Pharmacist' },
  { id: 'inventory_manager', label: 'Inventory Manager' },
  { id: 'auditor', label: 'Auditor' }
];

export const InvitesPanel: React.FC = () => {
  const [invites, setInvites] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ email: '', role: 'pharmacist' });
  const [busy, setBusy] = useState(false);
  const [freshLink, setFreshLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      setInvites((await apiClient.listInvites()).invites);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load invitations.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError(null); setFreshLink(null); setCopied(false);
    try {
      const created = await apiClient.createInvite(form);
      setFreshLink(created.invite_url);
      setForm({ email: '', role: 'pharmacist' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to invite.');
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!freshLink) return;
    try {
      await navigator.clipboard.writeText(freshLink);
      setCopied(true);
    } catch {
      // Clipboard access can be refused; the link is on screen to select.
      setCopied(false);
    }
  };

  const withdraw = async (id: string) => {
    try {
      await apiClient.revokeInvite(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to withdraw.');
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] p-8 shadow-sm flex items-center justify-center text-xs text-gray-400">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading invitations...
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
      <div className="border-b border-gray-100 pb-3">
        <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
          <Mail size={15} className="text-[#1b5dfc]" />
          <span>Invite someone</span>
        </h3>
        <p className="text-gray-500 text-[11px] mt-0.5">
          They get access to everything except Settings. Super Admins are promoted from the
          Accounts list, never invited.
        </p>
      </div>

      <form onSubmit={invite} className="flex flex-col sm:flex-row gap-2">
        <input
          type="email"
          required
          placeholder="their@gmail.com"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          className="flex-1 bg-[#f8fafc] border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:bg-white focus:border-blue-500"
        />
        <select
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
          className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-blue-500"
        >
          {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <button
          type="submit"
          disabled={busy}
          className="bg-[#1b5dfc] hover:bg-blue-700 disabled:opacity-60 text-white font-semibold rounded-lg px-4 py-2 text-[11px] whitespace-nowrap"
        >
          {busy ? 'Creating...' : 'Create link'}
        </button>
      </form>

      {freshLink && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-3.5 py-3 space-y-2">
          <p className="text-[11px] text-blue-900 font-semibold">
            Send them this link — it is shown only once.
          </p>
          <div className="flex gap-2">
            <input
              readOnly
              value={freshLink}
              onFocus={(e) => e.currentTarget.select()}
              className="flex-1 bg-white border border-blue-200 rounded-lg px-2.5 py-1.5 text-[10px] font-mono"
            />
            <button
              onClick={copy}
              className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-2.5 py-1.5 text-[10px] font-semibold flex items-center space-x-1"
            >
              <Copy size={11} />
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
          {error}
        </div>
      )}

      {invites.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                <th className="p-3 pl-4">Email</th>
                <th className="p-3">Role</th>
                <th className="p-3">Status</th>
                <th className="p-3 pr-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] text-xs text-gray-700">
              {invites.map((i) => (
                <tr key={i.id} className={i.status === 'pending' ? '' : 'opacity-55'}>
                  <td className="p-3 pl-4 font-medium text-[#0f172a]">{i.email}</td>
                  <td className="p-3">{(i.role || '').replace(/_/g, ' ')}</td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      i.status === 'pending' ? 'bg-amber-50 text-amber-700 border border-amber-200'
                      : i.status === 'accepted' ? 'bg-green-50 text-green-700 border border-green-200'
                      : 'bg-gray-100 text-gray-500 border border-gray-200'
                    }`}>{i.status}</span>
                  </td>
                  <td className="p-3 pr-4 text-right">
                    {i.status === 'pending' && (
                      <button
                        onClick={() => withdraw(i.id)}
                        title="Withdraw"
                        className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default InvitesPanel;
