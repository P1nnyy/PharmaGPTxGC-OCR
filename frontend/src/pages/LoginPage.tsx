/**
 * Sign-in screen.
 *
 * There is no "create an account" link on purpose: accounts are created by a
 * Super Admin, because a pharmacy's staff list is not something a stranger
 * should be able to add themselves to.
 */

import React, { useState } from 'react';
import { Loader2, Lock, ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const LoginPage: React.FC = () => {
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed.');
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
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

        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-7 space-y-5"
        >
          <div>
            <h2 className="text-base font-bold text-[#0f172a]">Sign in</h2>
            <p className="text-gray-500 text-xs mt-0.5">Use the account your administrator created for you.</p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all"
            />
          </div>

          {error && (
            <div
              role="alert"
              className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full bg-[#1b5dfc] hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl py-2.5 text-xs transition-colors flex items-center justify-center space-x-2"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Lock size={13} />}
            <span>{busy ? 'Signing in...' : 'Sign in'}</span>
          </button>
        </form>

        <p className="text-center text-[10px] text-gray-400 mt-5">
          Forgot your password? Ask a Super Admin to reset it.
        </p>
      </div>
    </div>
  );
};

export default LoginPage;
