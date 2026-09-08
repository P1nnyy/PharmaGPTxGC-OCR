import React, { useMemo, useState } from 'react';
import { AlertTriangle, BookOpen, CheckCircle2, Info, Loader2, ShieldAlert, Sparkles } from 'lucide-react';
import type { ReferenceProposal, ReferenceStatus, ReferenceSuggestResponse } from '../../api/types';

const FIELD_LABELS: Record<string, string> = {
  brand: 'Brand',
  strength: 'Strength',
  form: 'Dosage form',
  pack_size: 'Pack size',
  pack_multiplier: 'Units per pack',
  base_unit: 'Dispensing unit',
  manufacturer: 'Manufacturer',
  composition: 'Salt composition'
};

const label = (field: string) => FIELD_LABELS[field] || field;

const summarise = (fields: Record<string, any>) =>
  Object.entries(fields)
    .map(([k, v]) => `${label(k)} ${v}`)
    .join(' · ');

/**
 * Autofill from the local reference catalogue.
 *
 * The panel exists to make one thing obvious before anything is written: what
 * the reference will and will not answer. It fills a field only when every
 * listing that survived matching agrees on it, and it says plainly where they
 * disagreed — a brand sold in three strengths cannot have its strength
 * settled by its name, and the honest output there is the disagreement rather
 * than the most popular guess.
 *
 * What is applied is never marked as confirmed. The filled products return to
 * the review queue with their blanks gone, which is where a person approves
 * them. Autofill shortens the review; it is not a substitute for it.
 */
export const ReferenceFillPanel: React.FC<{
  status: ReferenceStatus | null;
  data: ReferenceSuggestResponse | null;
  busy: boolean;
  applying: boolean;
  onScan: () => void;
  onApply: (items: Array<{ product_id: string; fields: Record<string, any> }>) => Promise<void>;
}> = ({ status, data, busy, applying, onScan, onApply }) => {
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  // Only proposals that would actually change something. A product the
  // reference matched but had nothing new to say about is not work.
  const actionable = useMemo(
    () =>
      (data?.results || []).filter(
        (r) => Object.keys(r.new_fields || {}).length > 0 || Object.keys(r.expansions || {}).length > 0
      ),
    [data]
  );

  const conflicted = useMemo(
    () => (data?.results || []).filter((r) => Object.keys(r.conflicts || {}).length > 0),
    [data]
  );

  const selected = actionable.filter((r) => !excluded.has(r.product_id));

  const toggle = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const apply = async () => {
    const items = selected.map((r) => ({
      product_id: r.product_id,
      // Expansions carry the fuller spelling of something already recorded;
      // new_fields fill a blank. Both are the reference agreeing with us.
      fields: {
        ...r.new_fields,
        ...Object.fromEntries(Object.entries(r.expansions || {}).map(([k, v]) => [k, v.suggested]))
      }
    }));
    if (items.length === 0) return;
    await onApply(items);
    setExcluded(new Set());
  };

  if (status && !status.available) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <h4 className="text-sm font-bold text-[#0f172a] flex items-center gap-1.5">
          <BookOpen size={14} className="text-gray-400" />
          Reference data is not installed
        </h4>
        <p className="text-[11px] text-gray-500 leading-normal mt-1 max-w-2xl">
          The catalogue can fill in dosage form, strength, pack size and manufacturer by matching
          each item against a local index of Indian pharmaceutical products. Build it once from the
          source CSV:
        </p>
        <pre className="mt-3 bg-[#f8fafc] border border-[#e2e8f0] rounded-xl p-3 text-[10px] text-gray-700 overflow-x-auto">
python scripts/build_product_reference.py path/to/indian_pharmaceutical_products_clean.csv
        </pre>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 className="text-sm font-bold text-[#0f172a] flex items-center gap-1.5">
            <BookOpen size={14} className="text-gray-400" />
            Fill in from reference data
          </h4>
          <p className="text-[11px] text-gray-500 leading-normal mt-0.5 max-w-3xl">
            Matches each item against {status?.rows ? Number(status.rows).toLocaleString() : 'a local index of'}{' '}
            Indian products and fills only what every matching listing agrees on. Where listings
            disagree — the same brand sold in several strengths — nothing is filled and the
            disagreement is shown instead.
          </p>
        </div>
        <button
          onClick={onScan}
          disabled={busy}
          className="shrink-0 flex items-center gap-1.5 bg-white hover:bg-slate-50 text-[#1b5dfc] font-semibold px-3 py-2 rounded-xl text-xs border border-blue-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <BookOpen size={13} />}
          {busy ? 'Matching…' : data ? 'Match again' : 'Match catalogue'}
        </button>
      </div>

      {data && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm px-5 py-3 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-gray-500">
          <span><strong className="text-[#0f172a]">{data.scanned}</strong> products checked</span>
          <span><strong className="text-[#0f172a]">{data.matched}</strong> matched a listing</span>
          <span><strong className="text-[#0f172a]">{actionable.length}</strong> have details to add</span>
          {conflicted.length > 0 && (
            <span className="text-amber-600">
              <strong>{conflicted.length}</strong> disagree with what is recorded
            </span>
          )}
        </div>
      )}

      {data && actionable.length === 0 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-12 text-center">
          <CheckCircle2 size={22} className="text-green-500 inline-block mb-2" />
          <p className="text-gray-600 font-semibold text-sm">Nothing to add.</p>
          <p className="text-gray-400 text-xs mt-1">
            The reference had no details these products were missing.
          </p>
        </div>
      )}

      {actionable.length > 0 && (
        <section className="bg-white rounded-2xl border border-green-200 shadow-sm overflow-hidden">
          <div className="divide-y divide-[#f1f5f9] max-h-[30rem] overflow-y-auto">
            {actionable.map((proposal) => {
              const checked = !excluded.has(proposal.product_id);
              const additions = { ...proposal.new_fields };
              const expansions = proposal.expansions || {};
              return (
                <div key={proposal.product_id} className="flex items-start gap-3 px-5 py-3">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(proposal.product_id)}
                    aria-label={`Apply reference details to ${proposal.query}`}
                    className="mt-0.5 rounded border-gray-300 text-[#1b5dfc] focus:ring-blue-500 cursor-pointer shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-[#0f172a] truncate">{proposal.query}</span>
                      {proposal.match_count && proposal.match_count > 1 && (
                        <span className="text-[9px] text-gray-400">
                          {proposal.match_count} listings agreed
                        </span>
                      )}
                    </div>
                    {Object.keys(additions).length > 0 && (
                      <span className="text-[10px] text-green-700 block truncate">
                        + {summarise(additions)}
                      </span>
                    )}
                    {Object.entries(expansions).map(([field, value]) => (
                      <span key={field} className="text-[10px] text-blue-600 block truncate">
                        {label(field)}: {String(value.current)} → {String(value.suggested)}
                      </span>
                    ))}
                    {/* What the reference would not settle, and why. This is
                        the part that stops the panel reading as though it
                        knows more than it does. */}
                    {(proposal.contested || []).map((c) => (
                      <span key={c.field} className="text-[10px] text-gray-400 block">
                        {label(c.field)} left alone — {c.reason}
                      </span>
                    ))}
                    {proposal.composition && (
                      <span className="text-[10px] text-gray-400 block truncate">
                        Composition: {proposal.composition}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="px-5 py-4 bg-[#f8fafc] border-t border-[#e2e8f0] flex items-center justify-between gap-3">
            <span className="text-[10px] text-gray-500 max-w-xl">
              Applied details are not marked as confirmed — the products return to the review queue
              with their blanks filled, for you to approve there.
            </span>
            <button
              onClick={apply}
              disabled={applying || selected.length === 0}
              className="shrink-0 flex items-center gap-1.5 bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-blue-500/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {applying ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              {applying ? 'Applying…' : `Fill in ${selected.length}`}
            </button>
          </div>
        </section>
      )}

      {conflicted.length > 0 && (
        <section className="bg-white rounded-2xl border border-amber-200 shadow-sm overflow-hidden">
          <div className="p-5 pb-3 flex items-start gap-3">
            <div className="p-2.5 rounded-xl bg-amber-50 text-amber-600 shrink-0">
              <ShieldAlert size={18} />
            </div>
            <div>
              <h4 className="text-sm font-bold text-[#0f172a]">
                {conflicted.length} disagree with what is recorded
              </h4>
              <p className="text-[11px] text-gray-500 leading-normal mt-0.5">
                Never applied automatically — one side is wrong and only you can say which. A
                manufacturer mismatch usually means the invoice's abbreviation belongs to a
                different company than the reference expects.
              </p>
            </div>
          </div>
          <div className="divide-y divide-[#f1f5f9] max-h-72 overflow-y-auto">
            {conflicted.map((proposal) => (
              <div key={proposal.product_id} className="px-5 py-2.5">
                <span className="text-xs font-semibold text-[#0f172a] block truncate">
                  {proposal.query}
                </span>
                {Object.entries(proposal.conflicts).map(([field, value]) => (
                  <span key={field} className="text-[10px] text-gray-500 block">
                    {label(field)}: recorded <strong className="text-[#0f172a]">{String(value.current)}</strong>,
                    reference says <strong className="text-[#0f172a]">{String(value.suggested)}</strong>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

/** The same proposal, for one product, inside the review drawer. */
export const ReferenceInline: React.FC<{
  proposal: ReferenceProposal | null;
  busy: boolean;
  // Fields already filled from the reference. Needed because a product can
  // carry a suggestion without its NAME having matched anything - the
  // manufacturer code is resolved separately - and saying "no match" beside a
  // field tagged "PharmaGPT suggestion" reads as a contradiction.
  suggestedFields?: string[];
  onApply: (fields: Record<string, any>) => void;
}> = ({ proposal, busy, suggestedFields = [], onApply }) => {
  // Applying only writes into the form, so without this the click had no
  // visible effect at all: the button looked untouched, and the fields it
  // changed are further down the drawer, often out of view. The state also
  // carries the more important half of the message - that nothing is saved
  // yet.
  //
  // Held as "which product was applied" rather than a boolean reset by an
  // effect: the flag then follows the proposal on its own, with no second
  // render to clear it when the drawer moves to the next product.
  const [appliedFor, setAppliedFor] = useState<string | null>(null);
  const applied = !!proposal && appliedFor === proposal.product_id;

  if (busy) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-gray-400">
        <Loader2 size={12} className="animate-spin" /> Checking reference data…
      </div>
    );
  }
  if (!proposal) return null;

  if (proposal.status !== 'ok') {
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-xs text-slate-600">
          <Info size={14} className="shrink-0 mt-0.5" />
          <span>{proposal.message || 'No reference listing matches this name closely enough.'}</span>
        </div>
        {suggestedFields.length > 0 && (
          <div className="flex items-start gap-2 px-4 py-2.5 rounded-xl border border-[#e9dbff] bg-[#f8f4ff] text-xs text-[#5b21b6]">
            <Sparkles size={14} className="shrink-0 mt-0.5" />
            <span>
              {suggestedFields.map(label).join(' and ')}{' '}
              {suggestedFields.length === 1 ? 'was' : 'were'} still filled in — not from this
              product's name, but from the manufacturer code on the invoice, which other products
              in your catalogue resolve to a full company name.
            </span>
          </div>
        )}
      </div>
    );
  }

  const additions = {
    ...proposal.new_fields,
    ...Object.fromEntries(Object.entries(proposal.expansions || {}).map(([k, v]) => [k, v.suggested]))
  };

  return (
    <div className="border border-[#e2e8f0] rounded-xl overflow-hidden">
      <div className="bg-[#f8fafc] px-4 py-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="text-xs font-bold text-[#0f172a]">
            {proposal.candidates[0]?.brand_name || 'Reference match'}
          </span>
          <span className="text-[10px] text-gray-400 block">
            {proposal.match_count} listing{proposal.match_count === 1 ? '' : 's'} matched
            {proposal.therapeutic_class ? ` · ${proposal.therapeutic_class}` : ''}
          </span>
        </div>
        {Object.keys(additions).length > 0 && (
          <button
            onClick={() => {
              onApply(additions);
              setAppliedFor(proposal.product_id);
            }}
            disabled={applied}
            className={`shrink-0 font-semibold px-3 py-1.5 rounded-lg text-[11px] transition-colors flex items-center gap-1.5 ${
              applied
                ? 'bg-green-50 text-green-700 border border-green-200 cursor-default'
                : 'bg-[#1b5dfc] hover:bg-blue-700 text-white cursor-pointer'
            }`}
          >
            {applied ? <CheckCircle2 size={12} /> : null}
            {applied ? 'Filled in below' : 'Use these details'}
          </button>
        )}
      </div>
      <div className="px-4 py-3 space-y-1.5">
        {applied && (
          <p className="text-[10px] text-green-700 font-semibold pb-1">
            Copied into the form below — press Save or Save &amp; confirm to keep them.
          </p>
        )}
        {Object.entries(additions).map(([field, value]) => (
          <div key={field} className="flex gap-2 text-[11px]">
            <span className="text-gray-500 w-32 shrink-0">{label(field)}</span>
            <span className="font-semibold text-[#0f172a]">{String(value)}</span>
          </div>
        ))}
        {(proposal.contested || []).map((c) => (
          <div key={c.field} className="flex items-start gap-1.5 text-[10px] text-amber-700">
            <AlertTriangle size={10} className="shrink-0 mt-0.5" />
            <span>{label(c.field)} not filled — {c.reason}</span>
          </div>
        ))}
        {proposal.composition && (
          <p className="text-[10px] text-gray-500 pt-1 border-t border-[#f1f5f9] mt-1">
            <span className="text-gray-400">Composition:</span> {proposal.composition}
          </p>
        )}
        {proposal.candidates.length > 1 && (
          <details className="pt-1">
            <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">
              Show all {proposal.candidates.length} matching listings
            </summary>
            <ul className="mt-1 space-y-0.5">
              {proposal.candidates.map((c, i) => (
                <li key={i} className="text-[10px] text-gray-500">
                  {c.brand_name} — {c.primary_strength || 'no strength'} ·{' '}
                  {c.pack_size ? `pack of ${c.pack_size}` : 'pack unknown'}
                  {c.discontinued ? ' · discontinued' : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
};

export default ReferenceFillPanel;
