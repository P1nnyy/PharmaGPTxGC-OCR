/**
 * "We have not seen this code before — what is it?"
 *
 * The whole learning loop runs through this dialog. An unrecognised pack is
 * unrecognised exactly once: the user points it at a product here, and every
 * later scan of that product resolves without asking.
 *
 * It is also skippable. A queue does not wait while someone decides what a code
 * belongs to, so "just search instead" is always one tap away and binding is
 * never the price of billing.
 */

import React from 'react';
import { Link2, Loader2, Search, X } from 'lucide-react';

import { bindingKeyFor } from './bindingKey';
import type { ParsedDrugCode } from './parseDrugCode';
import { useProductSearch } from '../features/sell/useProductSearch';
import type { SellableProduct } from '../features/sell/types';

export const BindCodeDialog: React.FC<{
  parsed: ParsedDrugCode;
  symbology?: string;
  catalogue: SellableProduct[];
  onBind: (product: SellableProduct) => Promise<void>;
  onSkip: (product?: SellableProduct) => void;
  onClose: () => void;
}> = ({ parsed, symbology, catalogue, onBind, onSkip, onClose }) => {
  const search = useProductSearch(catalogue);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const key = bindingKeyFor(parsed, symbology);

  // A code that carried a product name gives the search a head start.
  React.useEffect(() => {
    const suggestion = parsed.fields.brand || parsed.fields.generic || '';
    if (suggestion) search.setQuery(suggestion);
    inputRef.current?.focus();
    // Runs once for this code; re-running would fight the user's typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed.raw]);

  const bind = async (product: SellableProduct) => {
    setBusy(true);
    setError(null);
    try {
      await onBind(product);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that.');
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-xs">
      <div className="bg-white w-full sm:max-w-md rounded-t-3xl sm:rounded-2xl border border-gray-200 shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-start justify-between px-5 py-3.5 border-b border-gray-100 shrink-0">
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-[#0f172a]">Bind this code to a product?</h3>
            <p className="text-[10px] text-gray-400 font-mono truncate mt-0.5" title={parsed.raw}>
              {key.value}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1 -mr-1 text-gray-400 hover:text-gray-600 cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-3 space-y-3 overflow-y-auto flex-1 min-h-0">
          {/* What the code did say, so the user can match it against the pack
              in their hand rather than trusting the search blindly. */}
          {(parsed.batch || parsed.expiry || parsed.fields.brand) && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 space-y-0.5">
              {parsed.fields.brand && (
                <p className="text-[11px] text-[#0f172a] font-semibold">{parsed.fields.brand}</p>
              )}
              {parsed.batch && (
                <p className="text-[10px] text-gray-500 font-mono">Batch {parsed.batch}</p>
              )}
              {parsed.expiry && (
                <p className="text-[10px] text-gray-500 font-mono">Expires {parsed.expiry}</p>
              )}
            </div>
          )}

          {!key.stable && (
            // Honest rather than encouraging: this payload is per-pack, so
            // binding it cannot help the next box of the same medicine.
            <p className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 leading-snug">
              This code carries a batch, so it is unique to this pack — binding it
              will not speed up the next one. Searching is the quicker path here.
            </p>
          )}

          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={inputRef}
              value={search.query}
              onChange={(event) => search.setQuery(event.target.value)}
              placeholder="Search the medicine…"
              className="w-full bg-white border-2 border-[#e2e8f0] focus:border-[#1b5dfc] rounded-xl pl-9 pr-3 py-2.5 text-sm text-[#0f172a] focus:outline-none"
            />
          </div>

          <div className="space-y-1">
            {search.results.map((product) => (
              <div
                key={product.product_id}
                className="flex items-center gap-2 border border-gray-200 rounded-xl px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-[#0f172a] truncate">{product.name}</p>
                  <p className="text-[10px] text-gray-400 font-mono truncate">
                    {[product.pack, product.manufacturer].filter(Boolean).join(' · ')}
                  </p>
                </div>
                <button
                  onClick={() => onSkip(product)}
                  disabled={busy}
                  className="shrink-0 text-[11px] font-semibold text-gray-500 hover:text-[#0f172a] px-2 py-1.5 cursor-pointer disabled:opacity-40"
                >
                  Just add
                </button>
                <button
                  onClick={() => bind(product)}
                  disabled={busy}
                  className="shrink-0 flex items-center gap-1 bg-[#1b5dfc] hover:bg-blue-700 text-white text-[11px] font-bold px-3 py-1.5 rounded-lg cursor-pointer disabled:opacity-40"
                >
                  {busy ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />}
                  Bind
                </button>
              </div>
            ))}
            {search.query.trim().length >= 2 && search.results.length === 0 && (
              <p className="text-[11px] text-gray-400 px-1 py-2">
                Nothing in stock matches that.
              </p>
            )}
          </div>

          {error && <p className="text-[11px] text-red-600">{error}</p>}
        </div>

        <div className="px-5 py-3 border-t border-gray-100 shrink-0">
          <button
            onClick={onClose}
            className="w-full text-xs font-semibold text-gray-500 hover:text-[#0f172a] py-2 cursor-pointer"
          >
            Skip — I'll search for it
          </button>
        </div>
      </div>
    </div>
  );
};
