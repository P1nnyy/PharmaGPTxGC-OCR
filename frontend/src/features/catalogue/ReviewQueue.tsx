import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  HelpCircle,
  Loader2,
  Sparkles
} from 'lucide-react';
import type { ReviewAssessment, ReviewBand, ReviewQueueResponse } from '../../api/types';

// The three bands, in the order a reviewer should meet them. Ready comes
// first on purpose: it is usually most of the list, it is answered in one
// click, and clearing it is what makes the remainder look finite.
const BANDS: Array<{
  band: ReviewBand;
  title: string;
  blurb: string;
  icon: React.ElementType;
  tone: string;
  chip: string;
}> = [
  {
    band: 'ready',
    title: 'Nothing left to ask',
    blurb:
      'Every catalogue field is filled, and each was either read from the invoice with high confidence or already approved by someone. Check the list and approve them together.',
    icon: Sparkles,
    tone: 'text-green-600 bg-green-50',
    chip: 'bg-green-50 text-green-700 border-green-200'
  },
  {
    band: 'review',
    title: 'Worth a glance',
    blurb:
      'Complete, but at least one value was inferred from the item name or filled in from the reference catalogue rather than read off this invoice. Quick to check, and worth checking — nobody has stood behind these yet.',
    icon: HelpCircle,
    tone: 'text-amber-600 bg-amber-50',
    chip: 'bg-amber-50 text-amber-700 border-amber-200'
  },
  {
    band: 'blocked',
    title: 'Needs a decision',
    blurb:
      'Something is missing that no invoice stated, or the evidence contradicts itself. These need you to supply a fact or make a call.',
    icon: AlertTriangle,
    tone: 'text-red-600 bg-red-50',
    chip: 'bg-red-50 text-red-700 border-red-200'
  }
];

// Rows beyond this get their own scroller; at or below it the section simply
// grows, so the page scrolls as one thing.
const SCROLL_AFTER = 8;

const describe = (item: ReviewAssessment): string => {
  const p = item.product;
  const bits = [p.strength, p.form, p.pack_size].filter(Boolean);
  return bits.length ? bits.join(' · ') : 'no details recorded';
};

const BandHeader: React.FC<{
  spec: (typeof BANDS)[number];
  count: number;
}> = ({ spec, count }) => {
  const Icon = spec.icon;
  return (
    <div className="flex items-start gap-3">
      <div className={`p-2.5 rounded-xl shrink-0 ${spec.tone}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <h4 className="text-sm font-bold text-[#0f172a]">
          {count} {count === 1 ? 'item' : 'items'} — {spec.title.toLowerCase()}
        </h4>
        <p className="text-[11px] text-gray-500 leading-normal mt-0.5">{spec.blurb}</p>
      </div>
    </div>
  );
};

/**
 * The work list, split by what each item actually needs.
 *
 * The catalogue used to present one undifferentiated table where every row
 * cost the same drawer visit, so the handful of products that needed thought
 * were priced identically to the two hundred that needed a signature — and in
 * practice neither got done. Splitting the list by what it needs is the whole
 * change: the ready band is approved as a batch, and what remains is small
 * enough to be worth opening one at a time.
 */
export const ReviewQueue: React.FC<{
  data: ReviewQueueResponse;
  busy: boolean;
  onOpen: (productId: string) => void;
  onReviewBand: (band: ReviewBand) => void;
  onApprove: (productIds: string[]) => Promise<void>;
}> = ({ data, busy, onOpen, onReviewBand, onApprove }) => {
  const grouped = useMemo(() => {
    const map: Record<ReviewBand, ReviewAssessment[]> = { ready: [], review: [], blocked: [] };
    data.items.forEach((item) => map[item.band]?.push(item));
    return map;
  }, [data.items]);

  // Everything ready is selected by default — the batch is the point. Anything
  // the reviewer unticks is simply left in the queue for next time.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);

  const readyIds = grouped.ready.map((i) => i.product_id);
  const selected = readyIds.filter((id) => !excluded.has(id));

  const toggle = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const approve = async () => {
    if (selected.length === 0) return;
    setApproving(true);
    try {
      await onApprove(selected);
      setExcluded(new Set());
    } finally {
      setApproving(false);
    }
  };

  if (busy) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-16 text-center text-gray-400">
        <Loader2 size={20} className="animate-spin inline-block mr-2" />
        Working out what still needs you...
      </div>
    );
  }

  if (data.total_outstanding === 0) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-16 text-center">
        <CheckCircle2 size={24} className="text-green-500 inline-block mb-2" />
        <p className="text-gray-600 font-semibold text-sm">The catalogue is fully reviewed.</p>
        <p className="text-gray-400 text-xs mt-1">
          {data.catalogue_total} {data.catalogue_total === 1 ? 'product' : 'products'}, all confirmed.
          New items appear here when you verify an invoice.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Ready — the batch */}
      {grouped.ready.length > 0 && (
        <section className="bg-white rounded-2xl border border-green-200 shadow-sm overflow-hidden">
          <div className="p-5 pb-4 border-b border-[#e2e8f0]">
            <BandHeader spec={BANDS[0]} count={grouped.ready.length} />
          </div>

          {/* Only a list long enough to need it gets its own scroller. Capping
              a six-row list swallows the page scroll the moment the pointer
              crosses it, which strands the reader halfway down the queue. */}
          <div
            className={`divide-y divide-[#f1f5f9] ${
              grouped.ready.length > SCROLL_AFTER ? 'max-h-96 overflow-y-auto' : ''
            }`}
          >
            {grouped.ready.map((item) => {
              const checked = !excluded.has(item.product_id);
              const name = item.product.brand || item.product.canonical_name || 'Unnamed item';
              return (
                <div
                  key={item.product_id}
                  className="flex items-start gap-3 px-5 py-3 hover:bg-[#f8fafc] transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(item.product_id)}
                    aria-label={`Include ${name} in the batch`}
                    className="mt-0.5 rounded border-gray-300 text-[#1b5dfc] focus:ring-blue-500 cursor-pointer shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    {/* The name is the link. It underlines on hover so it
                        reads as one before it is clicked, which is what the
                        separate "Open" button was standing in for. */}
                    <button
                      type="button"
                      onClick={() => onOpen(item.product_id)}
                      className="text-xs font-semibold text-[#0f172a] block truncate max-w-full text-left hover:text-[#1b5dfc] hover:underline underline-offset-2 cursor-pointer"
                    >
                      {name}
                    </button>
                    <span className="text-[10px] text-gray-400 block truncate">{describe(item)}</span>
                    {/* Not blocking, but the reviewer should not learn about it
                        afterwards either. */}
                    {item.caveats.length > 0 && (
                      <span className="text-[10px] text-amber-600 block truncate mt-0.5">
                        {item.caveats[0]}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="px-5 py-4 bg-[#f8fafc] border-t border-[#e2e8f0] flex items-center justify-between gap-3">
            <span className="text-[10px] text-gray-500">
              {selected.length === readyIds.length
                ? 'Approving records these values as confirmed against every invoice that mentions them.'
                : `${readyIds.length - selected.length} left out — they stay in the queue.`}
            </span>
            <button
              onClick={approve}
              disabled={approving || selected.length === 0}
              className="shrink-0 flex items-center gap-1.5 bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-blue-500/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {approving ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              {approving ? 'Approving…' : `Approve ${selected.length}`}
            </button>
          </div>
        </section>
      )}

      {/* Review and blocked — opened one at a time */}
      {BANDS.slice(1).map((spec) => {
        const items = grouped[spec.band];
        if (items.length === 0) return null;

        return (
          <section
            key={spec.band}
            className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden"
          >
            <div className="p-5 pb-4 border-b border-[#e2e8f0] flex items-start justify-between gap-4">
              <BandHeader spec={spec} count={items.length} />
              <button
                onClick={() => onReviewBand(spec.band)}
                className="shrink-0 flex items-center gap-1 bg-white hover:bg-slate-50 text-[#1b5dfc] font-semibold px-3 py-2 rounded-xl text-xs border border-blue-200 shadow-sm transition-colors cursor-pointer"
              >
                Work through {items.length}
                <ChevronRight size={13} />
              </button>
            </div>

            <div
              className={`divide-y divide-[#f1f5f9] ${
                items.length > SCROLL_AFTER ? 'max-h-96 overflow-y-auto' : ''
              }`}
            >
              {items.map((item) => (
                <button
                  key={item.product_id}
                  onClick={() => onOpen(item.product_id)}
                  className="group w-full text-left flex items-start gap-3 px-5 py-3 hover:bg-[#f8fafc] transition-colors cursor-pointer"
                >
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-semibold text-[#0f172a] block truncate group-hover:text-[#1b5dfc] group-hover:underline underline-offset-2">
                      {item.product.brand || item.product.canonical_name || 'Unnamed item'}
                    </span>
                    <span className="text-[10px] text-gray-400 block truncate">{describe(item)}</span>
                    {/* The reason, in the reviewer's language rather than a
                        flag code — this is what tells them whether the item is
                        worth opening now or later. */}
                    <ul className="mt-1 space-y-0.5">
                      {item.reasons.slice(0, 2).map((reason, i) => (
                        <li key={i} className="text-[10px] text-gray-500 leading-snug">
                          {reason}
                        </li>
                      ))}
                      {item.reasons.length > 2 && (
                        <li className="text-[10px] text-gray-400">
                          +{item.reasons.length - 2} more
                        </li>
                      )}
                    </ul>
                  </div>
                  <ChevronRight size={14} className="text-gray-300 shrink-0 mt-0.5" />
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
};

export default ReviewQueue;
