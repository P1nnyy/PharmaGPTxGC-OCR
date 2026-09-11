/**
 * The product search — the field the whole desktop flow revolves around.
 *
 * One component serves both layouts because the behaviour is identical and
 * only the anchoring differs: on desktop it sits at the top of the bill with
 * results dropping down, on mobile it is pinned above the keyboard with
 * results rising up. Two components would be two chances for the selection
 * logic to diverge.
 */

import React from 'react';
import { Package, Search } from 'lucide-react';

import { defaultBatch, expiryStanding } from '../batches';
import { formatPaise } from '../money';
import { Kbd } from './Primitives';
import type { SellableProduct } from '../types';

export interface ProductSearchProps {
  inputRef: React.RefObject<HTMLInputElement | null>;
  query: string;
  onQueryChange: (query: string) => void;
  results: SellableProduct[];
  highlight: number;
  onHighlight: (index: number) => void;
  onSelect: (product: SellableProduct) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  today: string;
  variant: 'desktop' | 'mobile';
  disabled?: boolean;
}

export const ProductSearch: React.FC<ProductSearchProps> = ({
  inputRef,
  query,
  onQueryChange,
  results,
  highlight,
  onHighlight,
  onSelect,
  onKeyDown,
  today,
  variant,
  disabled = false
}) => {
  const mobile = variant === 'mobile';

  const list = results.length > 0 && (
    <ul
      role="listbox"
      aria-label="Search results"
      className={`absolute left-0 right-0 z-30 bg-white border border-[#e2e8f0] rounded-2xl shadow-xl overflow-hidden ${
        mobile ? 'bottom-full mb-2' : 'top-full mt-2'
      }`}
    >
      {results.map((product, index) => {
        // Previewed through the same rule that will actually choose the
        // batch. Sorting by expiry here instead would put an expired batch's
        // price in the list and then bill a different one - the operator would
        // read out one figure and charge another.
        const front = defaultBatch(product.batches, today);
        const standing = front ? expiryStanding(front.expiry, today) : 'unknown';
        const active = index === highlight;
        return (
          <li key={product.product_id} role="option" aria-selected={active}>
            <button
              onMouseEnter={() => onHighlight(index)}
              onClick={() => onSelect(product)}
              className={`w-full text-left flex items-center gap-3 px-3 py-2.5 transition-colors cursor-pointer ${
                active ? 'bg-[#1b5dfc] text-white' : 'hover:bg-slate-50'
              }`}
            >
              <div className="min-w-0 flex-1">
                <p className={`text-xs font-semibold truncate ${active ? 'text-white' : 'text-[#0f172a]'}`}>
                  {product.name}
                </p>
                <p className={`text-[10px] font-mono truncate ${active ? 'text-blue-100' : 'text-gray-400'}`}>
                  {[product.pack, product.manufacturer, product.hsn ? `HSN ${product.hsn}` : 'no HSN']
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
              <div className="text-right shrink-0">
                <p className={`text-xs font-mono tabular-nums ${active ? 'text-white' : 'text-[#0f172a]'}`}>
                  {formatPaise(front?.mrp_paise ?? null)}
                </p>
                <p
                  className={`text-[10px] font-mono ${
                    active
                      ? 'text-blue-100'
                      : standing === 'expired'
                        ? 'text-red-600 font-bold'
                        : standing === 'near'
                          ? 'text-amber-700 font-bold'
                          : 'text-gray-400'
                  }`}
                >
                  {front
                    ? `${front.quantity_available} · ${front.expiry ?? 'no expiry'}`
                    : 'no sellable batch'}
                </p>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="relative">
      {list}
      <div className="relative">
        <Search
          size={mobile ? 18 : 16}
          className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
        />
        <input
          ref={inputRef}
          value={query}
          disabled={disabled}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls="sell-search-results"
          aria-autocomplete="list"
          placeholder={disabled ? 'Loading stock…' : 'Search a medicine…'}
          className={`w-full bg-white border-2 rounded-2xl text-[#0f172a] placeholder-gray-400 focus:outline-none focus:border-[#1b5dfc] transition-colors border-[#e2e8f0] disabled:bg-slate-50 ${
            mobile ? 'pl-11 pr-4 py-3.5 text-base' : 'pl-10 pr-32 py-3 text-sm'
          }`}
        />
        {!mobile && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5 text-[10px] text-gray-400 pointer-events-none">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd>
            <Kbd>↵</Kbd>
          </span>
        )}
      </div>
      {!mobile && query.trim().length === 1 && (
        <p className="absolute left-3 top-full mt-1 text-[10px] text-gray-400 flex items-center gap-1">
          <Package size={10} /> Keep typing — search starts at two characters.
        </p>
      )}
    </div>
  );
};
