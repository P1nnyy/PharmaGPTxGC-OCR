/**
 * Account management.
 *
 * Roles are recorded and shown here, but only Super Admin currently changes
 * what anyone can do - it gates this panel and the cache flush. The other
 * three are stored so accounts carry the right label from the day they are
 * created, rather than being backfilled later; enforcing them per-endpoint is
 * the next phase. The panel says so rather than implying the toggles do more
 * than they do.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, ShieldCheck, UserPlus, KeyRound, Check, Ban } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { AccountUser } from '../../api/types';
import { useAuth } from '../../context/AuthContext';

const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Super Admin',
  pharmacist: 'Pharmacist',
  inventory_manager: 'Inventory Manager',
  auditor: 'Auditor'
};

const ROLE_NOTES: Record<string, string> = {
  super_admin: 'Manages accounts and can flush the cache.',
  pharmacist: 'Scans and reviews invoices.',
  inventory_manager: 'Stock and catalogue.',
  auditor: 'Read-only oversight.'
};

const MIN_PASSWORD = 12;

const formatDate = (value: string | null): string => {
  if (!value) return 'Never';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleDateString();
};

export const UsersPanel: React.FC = () => {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'pharmacist' });
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiClient.listAccounts();
      setUsers(data.users);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load accounts.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const created = await apiClient.createAccount(form);
      setNotice(`Created ${created.email}. Share the password with them directly — it cannot be shown again.`);
      setForm({ email: '', name: '', password: '', role: 'pharmacist' });
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create the account.');
    } finally {
      setCreating(false);
    }
  };

  const applyChange = async (id: string, change: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await change();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That change was rejected.');
    } finally {
      setBusyId(null);
    }
  };

  const handleResetPassword = (target: AccountUser) => {
    const next = window.prompt(
      `New password for ${target.email} (at least ${MIN_PASSWORD} characters):`
    );
    if (next === null) return;
    if (next.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    void applyChange(target.id, async () => {
      await apiClient.resetAccountPassword(target.id, next);
      setNotice(`Password updated for ${target.email}.`);
    });
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] p-8 shadow-sm flex items-center justify-center text-xs text-gray-400">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading accounts...
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
        <div className="flex items-start justify-between border-b border-gray-100 pb-3">
          <div>
            <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
              <ShieldCheck size={15} className="text-[#1b5dfc]" />
              <span>Accounts</span>
            </h3>
            <p className="text-gray-500 text-[11px] mt-0.5">
              Everyone who can sign in. Accounts are created here — there is no self-serve signup.
            </p>
          </div>
          <button
            onClick={() => { setShowForm((v) => !v); setNotice(null); }}
            className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold rounded-xl px-3.5 py-2 text-[11px] flex items-center space-x-1.5 transition-colors shrink-0"
          >
            <UserPlus size={13} />
            <span>{showForm ? 'Cancel' : 'Add account'}</span>
          </button>
        </div>

        {notice && (
          <div className="bg-blue-50 border border-blue-200 text-blue-800 rounded-xl px-3.5 py-2.5 text-[11px]">
            {notice}
          </div>
        )}
        {error && (
          <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
            {error}
          </div>
        )}

        {showForm && (
          <form onSubmit={handleCreate} className="bg-[#f8fafc] border border-gray-200 rounded-xl p-4 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Email</label>
                <input
                  type="email" required value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Name</label>
                <input
                  type="text" value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                  Temporary password (min {MIN_PASSWORD})
                </label>
                <input
                  type="text" required minLength={MIN_PASSWORD} value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:border-blue-500"
                />
                <p className="text-[9px] text-gray-400">
                  Shown once, here, so you can pass it on. It is stored hashed and cannot be read back.
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Role</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-blue-500"
                >
                  {Object.keys(ROLE_LABELS).map((role) => (
                    <option key={role} value={role}>{ROLE_LABELS[role]}</option>
                  ))}
                </select>
                <p className="text-[9px] text-gray-400">{ROLE_NOTES[form.role]}</p>
              </div>
            </div>
            <button
              type="submit" disabled={creating}
              className="bg-[#0f172a] hover:bg-slate-800 disabled:opacity-60 text-white font-semibold rounded-lg px-4 py-2 text-[11px] flex items-center space-x-1.5"
            >
              {creating ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              <span>{creating ? 'Creating...' : 'Create account'}</span>
            </button>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                <th className="p-3 pl-4">Person</th>
                <th className="p-3">Role</th>
                <th className="p-3">Last sign-in</th>
                <th className="p-3">Status</th>
                <th className="p-3 pr-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] text-xs text-gray-700">
              {users.map((u) => {
                const isSelf = u.id === me?.id;
                const busy = busyId === u.id;
                return (
                  <tr key={u.id} className={`hover:bg-[#f8fafc] transition-colors ${u.is_active ? '' : 'opacity-55'}`}>
                    <td className="p-3 pl-4">
                      <span className="font-semibold text-[#0f172a] block">{u.name || u.email}</span>
                      <span className="text-[10px] text-gray-500">{u.email}{isSelf && ' · you'}</span>
                    </td>
                    <td className="p-3">
                      <select
                        value={u.role}
                        disabled={busy || isSelf}
                        title={isSelf ? 'You cannot change your own role.' : undefined}
                        onChange={(e) => applyChange(u.id, () => apiClient.updateAccount(u.id, { role: e.target.value }))}
                        className="bg-white border border-gray-200 rounded-lg px-2 py-1 text-[11px] disabled:bg-slate-50 disabled:text-gray-400 focus:outline-none focus:border-blue-500"
                      >
                        {Object.keys(ROLE_LABELS).map((role) => (
                          <option key={role} value={role}>{ROLE_LABELS[role]}</option>
                        ))}
                      </select>
                    </td>
                    <td className="p-3 text-gray-500">{formatDate(u.last_login_at)}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        u.is_active
                          ? 'bg-green-50 text-green-700 border border-green-200'
                          : 'bg-gray-100 text-gray-500 border border-gray-200'
                      }`}>
                        {u.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className="p-3 pr-4">
                      <div className="flex items-center justify-end space-x-1.5">
                        <button
                          onClick={() => handleResetPassword(u)}
                          disabled={busy}
                          title="Set a new password"
                          className="p-1.5 text-gray-500 hover:text-[#1b5dfc] hover:bg-blue-50 rounded-lg disabled:opacity-40 transition-colors"
                        >
                          <KeyRound size={13} />
                        </button>
                        <button
                          onClick={() => applyChange(u.id, () => apiClient.updateAccount(u.id, { is_active: !u.is_active }))}
                          disabled={busy || isSelf}
                          title={isSelf ? 'You cannot disable your own account.' : u.is_active ? 'Disable' : 'Re-enable'}
                          className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg disabled:opacity-40 transition-colors"
                        >
                          {busy ? <Loader2 size={13} className="animate-spin" /> : u.is_active ? <Ban size={13} /> : <Check size={13} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[10px] text-gray-400 px-1">
        Roles are recorded on every account, but only Super Admin currently changes what someone can do —
        it gates this panel and the cache flush. Per-role limits on the rest of the app are the next phase.
      </p>
    </div>
  );
};

export default UsersPanel;
