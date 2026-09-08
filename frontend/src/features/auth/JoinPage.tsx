/**
 * Accepting an invitation.
 *
 * Standalone, outside the app shell: the person following this link is not a
 * member yet, so wrapping them in navigation for a workspace they cannot see
 * would be a lie. The email is fixed to the one the invitation was issued
 * for, because the server checks it anyway - letting it be edited would only
 * produce a rejection after the form was filled in.
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, Loader2, ShieldCheck } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface Invite {
  email: string;
  role: string;
  status: string;
  valid: boolean;
  pharmacy_name: string | null;
}

const ROLE_LABELS: Record<string, string> = {
  pharmacist: 'Pharmacist',
  inventory_manager: 'Inventory Manager',
  auditor: 'Auditor',
  super_admin: 'Super Admin'
};

export const JoinPage: React.FC = () => {
  const { token = '' } = useParams();
  const navigate = useNavigate();
  const { register, googleAvailable, user } = useAuth();

  const [invite, setInvite] = useState<Invite | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: '', password: '', confirm_password: '' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`/auth/invites/lookup/${encodeURIComponent(token)}`);
        if (cancelled) return;
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || 'That invitation link is not valid.');
        }
        setInvite(await r.json());
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'That link is not valid.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // Already signed in and the invitation lands: the safe thing is to say so
  // rather than silently switching which workspace they are in.
  const signedInAsSomeoneElse = Boolean(user && invite && user.email !== invite.email);

  const accept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !invite) return;
    setBusy(true);
    setError(null);
    try {
      if (form.password !== form.confirm_password) {
        throw new Error('The two passwords do not match.');
      }
      await register({
        email: invite.email,
        name: form.name,
        password: form.password,
        confirm_password: form.confirm_password,
        invite_token: token
      });
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invitation.');
      setForm((f) => ({ ...f, password: '', confirm_password: '' }));
    } finally {
      setBusy(false);
    }
  };

  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-[#f4f5fa] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center space-x-3 mb-8 justify-center">
          <div className="w-11 h-11 bg-[#1b5dfc] rounded-xl flex items-center justify-center">
            <ShieldCheck size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-[#0f172a] leading-tight">PharmaGPT</h1>
            <p className="text-[11px] text-gray-500 leading-tight">Pharmacy Central</p>
          </div>
        </div>
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-7 space-y-5">
          {children}
        </div>
      </div>
    </div>
  );

  if (loading) {
    return shell(
      <div className="flex items-center justify-center text-xs text-gray-400 py-4">
        <Loader2 size={14} className="animate-spin mr-2" /> Checking the invitation...
      </div>
    );
  }

  if (error && !invite) {
    return shell(
      <>
        <h2 className="text-base font-bold text-[#0f172a]">This link does not work</h2>
        <p className="text-gray-500 text-xs">{error}</p>
        <p className="text-[11px] text-gray-400">
          Invitations expire, and each one can only be used once. Ask whoever invited you to send a new link.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          className="w-full bg-[#0f172a] hover:bg-slate-800 text-white font-semibold rounded-xl py-2.5 text-xs transition-colors"
        >
          Go to PharmaGPT
        </button>
      </>
    );
  }

  if (invite && !invite.valid) {
    return shell(
      <>
        <h2 className="text-base font-bold text-[#0f172a]">This invitation is closed</h2>
        <p className="text-gray-500 text-xs">
          It has already been used, expired, or was withdrawn.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          className="w-full bg-[#0f172a] hover:bg-slate-800 text-white font-semibold rounded-xl py-2.5 text-xs transition-colors"
        >
          Go to PharmaGPT
        </button>
      </>
    );
  }

  if (signedInAsSomeoneElse) {
    return shell(
      <>
        <h2 className="text-base font-bold text-[#0f172a]">Signed in as someone else</h2>
        <p className="text-gray-500 text-xs">
          This invitation is for <strong>{invite!.email}</strong>, but you are signed in as{' '}
          <strong>{user!.email}</strong>. Sign out first, then open the link again.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          className="w-full bg-[#0f172a] hover:bg-slate-800 text-white font-semibold rounded-xl py-2.5 text-xs transition-colors"
        >
          Go to PharmaGPT
        </button>
      </>
    );
  }

  return shell(
    <>
      <div>
        <h2 className="text-base font-bold text-[#0f172a]">
          Join {invite!.pharmacy_name || 'this workspace'}
        </h2>
        <p className="text-gray-500 text-xs mt-0.5">
          Invited as <strong>{ROLE_LABELS[invite!.role] || invite!.role}</strong>.
        </p>
      </div>

      <div className="bg-[#f8fafc] border border-gray-200 rounded-xl px-3.5 py-2.5">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Invitation for</span>
        <span className="text-xs font-semibold text-[#0f172a]">{invite!.email}</span>
      </div>

      {googleAvailable && (
        <>
          <a
            href={`/auth/google/start?invite=${encodeURIComponent(token)}&next=${encodeURIComponent('/dashboard')}`}
            className="w-full border border-gray-300 hover:bg-gray-50 text-[#0f172a] font-semibold rounded-xl py-2.5 text-xs transition-colors flex items-center justify-center space-x-2"
          >
            <span>Continue with Google</span>
          </a>
          <div className="flex items-center space-x-3">
            <div className="h-px bg-gray-200 flex-1" />
            <span className="text-[10px] text-gray-400 font-medium">or set a password</span>
            <div className="h-px bg-gray-200 flex-1" />
          </div>
        </>
      )}

      <form onSubmit={accept} className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Your name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs focus:outline-none focus:bg-white focus:border-blue-500"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Password</label>
          <input
            type="password"
            required
            minLength={12}
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs focus:outline-none focus:bg-white focus:border-blue-500"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Confirm password</label>
          <input
            type="password"
            required
            minLength={12}
            autoComplete="new-password"
            value={form.confirm_password}
            onChange={(e) => setForm({ ...form, confirm_password: e.target.value })}
            className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs focus:outline-none focus:bg-white focus:border-blue-500"
          />
        </div>

        {error && (
          <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white font-semibold rounded-xl py-2.5 text-xs transition-colors flex items-center justify-center space-x-2"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={13} />}
          <span>{busy ? 'Joining...' : 'Join workspace'}</span>
        </button>
      </form>
    </>
  );
};

export default JoinPage;
