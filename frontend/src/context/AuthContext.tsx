/**
 * Who is signed in.
 *
 * On load the stored token is verified against the server via /auth/me rather
 * than trusted for its contents. A token can be expired, revoked, or belong
 * to an account an admin has since disabled, and none of that is visible from
 * the token itself - so the app asks.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getToken, installAuthFetch, onSessionExpired, setToken } from '../api/session';

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

interface AuthState {
  user: AuthUser | null;
  /** True until the stored token has been checked, so the app does not flash
   *  the login screen at someone who is already signed in. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  isSuperAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

// Installed at module load, before any component can fire a request.
installAuthFetch();

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => onSessionExpired(() => setUser(null)), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken()) {
        setLoading(false);
        return;
      }
      try {
        const response = await fetch('/auth/me');
        if (cancelled) return;
        if (response.ok) setUser(await response.json());
        else setToken(null);
      } catch {
        // Network failure is not proof the session is invalid, but there is
        // nothing to show without it either; the login screen is the honest
        // fallback.
        if (!cancelled) setToken(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Sign in failed.');
    }
    const data = await response.json();
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, signIn, signOut, isSuperAdmin: user?.role === 'super_admin' }),
    [user, loading, signIn, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthState => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider.');
  return context;
};
