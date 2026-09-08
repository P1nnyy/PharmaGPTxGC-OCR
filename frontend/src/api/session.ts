/**
 * Session token storage and transport.
 *
 * The token is attached by wrapping `window.fetch` once at startup rather
 * than by editing each of the API call sites. Two reasons: a missed call site
 * is a silently broken page, and any call added later would have to remember
 * to opt in. Wrapping makes authenticated the default and needs no
 * cooperation from the modules doing the fetching.
 *
 * It also gives one place to notice a 401. A token can expire mid-session or
 * be invalidated by an admin deactivating the account, and without central
 * handling that surfaces as an unexplained failure on whichever page the user
 * happened to be on.
 */

const TOKEN_KEY = 'pharmagpt_token';

// Only paths the backend serves. Anything else - a CDN font, an external
// image - must not receive an Authorization header, which would leak the
// token to a third party.
const API_PREFIXES = [
  '/auth/', '/health', '/upload-invoice', '/clear-cache',
  '/invoices', '/products', '/item-types', '/reports/', '/inventory/'
];

type Listener = () => void;
const expiryListeners = new Set<Listener>();

export const getToken = (): string | null => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private mode and blocked site data both throw here. A session that
    // cannot be stored is not fatal - it just does not survive a reload.
    return memoryToken;
  }
};

// Fallback for browsers refusing localStorage, so sign-in still works for the
// life of the tab.
let memoryToken: string | null = null;

export const setToken = (token: string | null): void => {
  memoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* memoryToken already holds it */
  }
};

export const onSessionExpired = (fn: Listener): (() => void) => {
  expiryListeners.add(fn);
  return () => expiryListeners.delete(fn);
};

const isApiPath = (url: string): boolean => {
  // Relative URLs are ours; absolute ones only if they point back at this origin.
  let path = url;
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url);
      if (parsed.origin !== window.location.origin) return false;
      path = parsed.pathname;
    } catch {
      return false;
    }
  }
  return API_PREFIXES.some((prefix) => path === prefix.replace(/\/$/, '') || path.startsWith(prefix));
};

let installed = false;

export const installAuthFetch = (): void => {
  if (installed) return;
  installed = true;

  const original = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const token = getToken();

    let next = init;
    if (token && isApiPath(url)) {
      const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
      // Never overwrite an Authorization the caller set deliberately.
      if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
      next = { ...init, headers };
    }

    const response = await original(input as RequestInfo, next);

    // A 401 on an API call means the session is gone - expired, or the
    // account was disabled while the tab was open. Drop the dead token and
    // let the app redirect, rather than leaving the page half-broken.
    // The login endpoint is exempt: a 401 there is a wrong password, not an
    // expired session.
    if (response.status === 401 && isApiPath(url) && !url.includes('/auth/login')) {
      setToken(null);
      expiryListeners.forEach((fn) => fn());
    }

    return response;
  };
};
