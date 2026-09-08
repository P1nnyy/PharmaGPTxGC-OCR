/**
 * Sign in / register, as an overlay over whatever page you were on.
 *
 * One dialog with two modes rather than two routes: the button says
 * "Register/Sign in" because most people do not know which they need, and
 * making them choose before they can type is friction with nothing behind it.
 */

import React, { useEffect, useState } from 'react';
import { Loader2, Lock, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

const MIN_PASSWORD = 12;

export const AuthModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { signIn, register, googleAvailable } = useAuth();
  const [mode, setMode] = useState<'signin' | 'register'>('signin');
  const [form, setForm] = useState({
    email: '', name: '', password: '', confirm_password: '', pharmacy_name: ''
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // A failed Google round trip comes back on the URL and is dispatched here,
  // so the reason lands in this dialog rather than vanishing.
  useEffect(() => {
    const handler = (e: Event) => setError((e as CustomEvent).detail as string);
    window.addEventListener('pharmagpt:auth-error', handler);
    return () => window.removeEventListener('pharmagpt:auth-error', handler);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'signin') {
        await signIn(form.email, form.password);
      } else {
        if (form.password !== form.confirm_password) {
          throw new Error('The two passwords do not match.');
        }
        await register(form);
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.');
      setForm((f) => ({ ...f, password: '', confirm_password: '' }));
    } finally {
      setBusy(false);
    }
  };

  const field = (
    key: keyof typeof form, label: string, type = 'text',
    autoComplete?: string, required = true
  ) => (
    <div className="space-y-1.5">
      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">{label}</label>
      <input
        type={type}
        required={required}
        autoComplete={autoComplete}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        minLength={type === 'password' ? MIN_PASSWORD : undefined}
        className="w-full bg-[#f8fafc] border border-gray-200 rounded-xl px-4 py-2.5 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all"
      />
    </div>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-sm bg-white rounded-2xl border border-[#e2e8f0] shadow-xl p-7 space-y-5 relative max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <X size={15} />
        </button>

        <div>
          <h2 className="text-base font-bold text-[#0f172a]">
            {mode === 'signin' ? 'Sign in' : 'Create your workspace'}
          </h2>
          <p className="text-gray-500 text-xs mt-0.5">
            {mode === 'signin'
              ? 'Welcome back.'
              : 'You get an empty workspace of your own — nobody else can see it.'}
          </p>
        </div>

        {googleAvailable && (
          <>
            <a
              href={`/auth/google/start?next=${encodeURIComponent(window.location.pathname)}`}
              className="w-full border border-gray-300 hover:bg-gray-50 text-[#0f172a] font-semibold rounded-xl py-2.5 text-xs transition-colors flex items-center justify-center space-x-2"
            >
              <svg width="15" height="15" viewBox="0 0 48 48" aria-hidden="true">
                <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-2.8-.4-4H24v7.5h12.7c-.3 2.1-1.6 5.3-4.7 7.4l7.6 5.9c4.5-4.2 6.5-10.3 6.5-16.8z"/>
                <path fill="#FBBC05" d="M10.4 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6.1C1 16.5 0 20.1 0 24s1 7.5 2.6 10.8l7.8-6.1z"/>
                <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2 1.4-4.8 2.4-8.3 2.4-6.4 0-11.7-3.7-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z"/>
              </svg>
              <span>Continue with Google</span>
            </a>
            <div className="flex items-center space-x-3">
              <div className="h-px bg-gray-200 flex-1" />
              <span className="text-[10px] text-gray-400 font-medium">or</span>
              <div className="h-px bg-gray-200 flex-1" />
            </div>
          </>
        )}

        <form onSubmit={submit} className="space-y-4">
          {field('email', 'Email', 'email', 'username')}
          {mode === 'register' && field('name', 'Your name', 'text', 'name', false)}
          {field('password', 'Password', 'password',
                 mode === 'signin' ? 'current-password' : 'new-password')}
          {mode === 'register' && (
            <>
              {field('confirm_password', 'Confirm password', 'password', 'new-password')}
              <p className="text-[10px] text-gray-400 -mt-2">
                At least {MIN_PASSWORD} characters. A short phrase beats a short password.
              </p>
            </>
          )}

          {error && (
            <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full bg-[#1b5dfc] hover:bg-blue-700 disabled:opacity-60 text-white font-semibold rounded-xl py-2.5 text-xs transition-colors flex items-center justify-center space-x-2"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Lock size={13} />}
            <span>{busy ? 'Please wait...' : mode === 'signin' ? 'Sign in' : 'Create workspace'}</span>
          </button>
        </form>

        <button
          onClick={() => { setMode(mode === 'signin' ? 'register' : 'signin'); setError(null); }}
          className="w-full text-[11px] text-gray-500 hover:text-[#1b5dfc] transition-colors"
        >
          {mode === 'signin'
            ? "New here? Create a workspace"
            : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  );
};

export default AuthModal;
