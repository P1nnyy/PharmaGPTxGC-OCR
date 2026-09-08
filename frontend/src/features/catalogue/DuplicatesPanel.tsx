import React, { useState } from 'react';
import { CheckCircle2, GitMerge, Info, Loader2, Search } from 'lucide-react';
import type { DuplicateCandidate, DuplicateResponse, Product } from '../../api/types';

/**
 * Merge suggestions the catalogue found on its own.
 *
 * Merging by hand already existed, but it required noticing that two of four
 * hundred rows were the same medicine — which is work nobody does, so the
 * duplicates simply accumulated. What is offered here is only what survived
 * automatic merging at write time: pairs where one invoice stated a strength
 * and another didn't, or where two distributors' spellings diverged far enough
 * to make different identity keys.
 *
 * Every candidate is shown with the reasoning that produced it. A merge that
 * turns out to join two different medicines is expensive and quiet — stock and
 * price history for two products collapse into one — so this asks rather than
 * acts, and says enough for the answer to be informed.
 */
export const DuplicatesPanel: React.FC<{
  data: DuplicateResponse | null;
  busy: boolean;
  products: Product[];
  onScan: () => void;
  onMerge: (sourceIds: string[], targetId: string) => Promise<void>;
}> = ({ data, busy, products, onScan, onMerge }) => {
  const [merging, setMerging] = useState<string | null>(null);
  const byId = new Map(products.map((p) => [p.id, p]));

  const key = (candidate: DuplicateCandidate) => candidate.product_ids.join('+');

  const merge = async (candidate: DuplicateCandidate) => {
    const target = candidate.suggested_target;
    const sources = candidate.product_ids.filter((id) => id !== target);
    setMerging(key(candidate));
    try {
      await onMerge(sources, target);
    } finally {
      setMerging(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 className="text-sm font-bold text-[#0f172a] flex items-center gap-1.5">
            <GitMerge size={14} className="text-gray-400" />
            Possible duplicates
          </h4>
          <p className="text-[11px] text-gray-500 leading-normal mt-0.5">
            Items that look like one medicine recorded twice. Spellings that reduce to the same
            brand, strength and pack were already merged when they were saved — these are the ones
            that got past that, usually because one invoice left something out.
          </p>
        </div>
        <button
          onClick={onScan}
          disabled={busy}
          className="shrink-0 flex items-center gap-1.5 bg-white hover:bg-slate-50 text-[#1b5dfc] font-semibold px-3 py-2 rounded-xl text-xs border border-blue-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
          {busy ? 'Checking…' : data ? 'Check again' : 'Check for duplicates'}
        </button>
      </div>

      {data && data.candidates.length === 0 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-12 text-center">
          <CheckCircle2 size={22} className="text-green-500 inline-block mb-2" />
          <p className="text-gray-600 font-semibold text-sm">No duplicates found.</p>
          <p className="text-gray-400 text-xs mt-1">
            Compared all {data.scanned} {data.scanned === 1 ? 'product' : 'products'} against each other.
          </p>
        </div>
      )}

      {data?.candidates.map((candidate) => {
        const target = candidate.suggested_target;
        const isMerging = merging === key(candidate);

        return (
          <div
            key={key(candidate)}
            className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden"
          >
            <div className="px-5 py-3 bg-[#f8fafc] border-b border-[#e2e8f0] flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                <span
                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                    candidate.verdict === 'likely'
                      ? 'bg-green-50 text-green-700 border-green-200'
                      : 'bg-amber-50 text-amber-700 border-amber-200'
                  }`}
                >
                  {candidate.verdict === 'likely' ? 'Likely the same' : 'Possibly the same'}
                </span>
                <span className="text-[10px] text-gray-400 font-mono">{candidate.score}% match</span>
              </div>
              <button
                onClick={() => merge(candidate)}
                disabled={isMerging}
                className="shrink-0 flex items-center gap-1.5 bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-3 py-1.5 rounded-lg text-[11px] transition-colors cursor-pointer disabled:opacity-50"
              >
                {isMerging ? <Loader2 size={12} className="animate-spin" /> : <GitMerge size={12} />}
                Merge into one
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-[#e2e8f0]">
              {candidate.product_ids.map((id, index) => {
                const product = byId.get(id);
                const isTarget = id === target;
                return (
                  <div key={id} className="p-4">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-bold text-[#0f172a] truncate">
                        {candidate.names[index]}
                      </span>
                      {isTarget && (
                        <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-50 text-[#1b5dfc] border border-blue-200">
                          kept
                        </span>
                      )}
                    </div>
                    {product ? (
                      <dl className="space-y-0.5 text-[10px]">
                        {([
                          ['Strength', product.strength],
                          ['Form', product.form],
                          ['Pack', product.pack_size],
                          ['Units/pack', product.pack_multiplier],
                          ['Manufacturer', product.manufacturer],
                          ['Seen', `${product.times_seen}× on ${product.invoice_count} invoice(s)`]
                        ] as const).map(([label, value]) => (
                          <div key={label} className="flex gap-2">
                            <dt className="text-gray-400 w-20 shrink-0">{label}</dt>
                            <dd className="text-gray-700 truncate">{value || '—'}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <p className="text-[10px] text-gray-400">Details unavailable.</p>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="px-5 py-3 border-t border-[#e2e8f0] space-y-1">
              {candidate.reasons.map((reason, i) => (
                <div key={i} className="flex items-start gap-1.5 text-[10px] text-gray-500">
                  <Info size={10} className="shrink-0 mt-0.5 text-gray-400" />
                  <span>{reason}</span>
                </div>
              ))}
              <p className="text-[10px] text-gray-400 pt-1">
                Merging keeps both purchase histories and all spellings under the record marked
                “kept”. If they turn out to be different medicines, split the spelling back out from
                that product.
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default DuplicatesPanel;
