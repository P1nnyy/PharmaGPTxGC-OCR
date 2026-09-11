/**
 * Debounced product search over the loaded stock list.
 *
 * The debounce is on the *query*, not on the keystroke: what the operator
 * typed is reflected in the input immediately, and only the filtering waits.
 * A counter search that lags the characters being typed feels broken even when
 * the results are right.
 *
 * Matching is deliberately plain substring, over name, batch and manufacturer.
 * Fuzzy matching sounds better and is worse here - an operator who types three
 * characters of a drug name and gets a near-miss at the top of the list can
 * sell the wrong medicine.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import type { SellableProduct } from './types';

const DEBOUNCE_MS = 120;
/** Enough to see the whole shortlist without scrolling, on either layout. */
export const MAX_RESULTS = 8;

export function useDebounced<T>(value: T, delayMs = DEBOUNCE_MS): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function score(product: SellableProduct, needle: string): number | null {
  const name = product.name.toLowerCase();
  const index = name.indexOf(needle);
  // A name that starts with what was typed ranks above one that merely
  // contains it: typing "PARA" should surface PARACETAMOL, not a product with
  // "para" buried in the middle of its description.
  if (index === 0) return 0;
  if (index > 0) return 1;
  const haystack = [
    product.manufacturer ?? '',
    product.pack ?? '',
    ...product.batches.map((b) => b.batch_number ?? '')
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle) ? 2 : null;
}

export interface SearchState {
  query: string;
  setQuery: (query: string) => void;
  results: SellableProduct[];
  /** Index of the highlighted result, kept inside the result bounds. */
  highlight: number;
  setHighlight: (index: number) => void;
  moveHighlight: (delta: number) => void;
  reset: () => void;
}

export function useProductSearch(catalogue: SellableProduct[]): SearchState {
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const debounced = useDebounced(query);

  const results = useMemo(() => {
    const needle = debounced.trim().toLowerCase();
    if (needle.length < 2) return [];
    const scored: { product: SellableProduct; rank: number }[] = [];
    for (const product of catalogue) {
      const rank = score(product, needle);
      if (rank !== null) scored.push({ product, rank });
    }
    scored.sort((a, b) => a.rank - b.rank || a.product.name.localeCompare(b.product.name));
    return scored.slice(0, MAX_RESULTS).map((entry) => entry.product);
  }, [catalogue, debounced]);

  // A new result set always starts at the top. Leaving the highlight where it
  // was would point at a different medicine than the one it pointed at before
  // the last character was typed.
  const previous = useRef(results);
  useEffect(() => {
    if (previous.current !== results) {
      setHighlight(0);
      previous.current = results;
    }
  }, [results]);

  return {
    query,
    setQuery,
    results,
    highlight: Math.min(highlight, Math.max(0, results.length - 1)),
    setHighlight,
    moveHighlight: (delta: number) =>
      setHighlight((current) => {
        if (results.length === 0) return 0;
        // Wraps, so holding the down arrow cycles rather than sticking.
        return (current + delta + results.length) % results.length;
      }),
    reset: () => {
      setQuery('');
      setHighlight(0);
    }
  };
}
