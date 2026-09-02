import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Package,
  Search,
  AlertTriangle,
  CheckCircle2,
  X,
  GitMerge,
  Scissors,
  Layers,
  Info,
  Loader2,
  FileText,
  Tag,
  ListChecks,
  Table2,
  ArrowRight,
  BookOpen,
  Sparkles
} from 'lucide-react';
import { apiClient } from '../api/client';
import { ReviewQueue } from '../features/catalogue/ReviewQueue';
import { DuplicatesPanel } from '../features/catalogue/DuplicatesPanel';
import { ReferenceFillPanel, ReferenceInline } from '../features/catalogue/ReferenceFillPanel';
import type {
  Product,
  ProductSummary,
  ProductFlag,
  ProductAlias,
  ItemType,
  ReviewBand,
  ReviewQueueResponse,
  DuplicateResponse,
  ReferenceStatus,
  ReferenceSuggestResponse,
  ReferenceProposal,
} from '../api/types';

// The item-type vocabulary is NOT hardcoded here any more. It lives in the
// catalogue (Settings -> Catalogue), because a pharmacy stocks things this
// list never anticipated, and because the same names were previously repeated
// in five places that had to be edited together and had already drifted.
// The drawer loads it and derives the pickers from it below.

const SCHEDULES = ['Schedule H', 'Schedule H1', 'Schedule X', 'Schedule G', 'Narcotic', 'OTC', 'General'];

const SEVERITY_STYLES: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-50 text-slate-600 border-slate-200'
};

const currency = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `₹${Number(value).toFixed(2)}`;

const StatTile: React.FC<{
  label: string;
  value: number | string;
  icon: React.ElementType;
  tone: 'blue' | 'amber' | 'red' | 'green';
  hint?: string;
}> = ({ label, value, icon: Icon, tone, hint }) => {
  const tones = {
    blue: 'bg-blue-50 text-[#1b5dfc]',
    amber: 'bg-amber-50 text-amber-600',
    red: 'bg-red-50 text-red-600',
    green: 'bg-green-50 text-green-600'
  };
  return (
    <div className="bg-white p-6 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-center space-x-4">
      <div className={`p-3 rounded-xl shrink-0 ${tones[tone]}`}>
        <Icon size={24} />
      </div>
      <div className="min-w-0">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">{label}</span>
        <strong className="text-2xl font-bold text-[#0f172a]">{value}</strong>
        {hint && <span className="block text-[10px] text-gray-400 truncate">{hint}</span>}
      </div>
    </div>
  );
};

// A field the parser filled in is visually distinct from one a human approved.
// Without that distinction the form would present every guess as established
// fact, which is exactly the failure this section exists to prevent.
const FieldLabel: React.FC<{
  label: string;
  acknowledged?: boolean;
  suggested?: boolean;
  hasValue: boolean;
}> = ({ label, acknowledged, suggested, hasValue }) => (
  <div className="flex items-center justify-between mb-1.5">
    <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{label}</label>
    {/* One tag, and it means one thing: PharmaGPT put this value here.
        Everything else the form knows about a field — that the parser read it
        confidently, that a person approved it — used to get its own chip, and
        ten fields produced ten chips saying four different things. That is
        noise, and it buried the only chip a reviewer has to act on: the value
        nobody has stood behind yet.

        Where a value came from otherwise is not the reviewer's question. The
        product header already says whether the record is confirmed, and the
        review queue explains in words what it is still unsure about. */}
    {suggested && hasValue ? (
      <span
        className="text-[9px] font-bold text-[#7c3aed] flex items-center gap-0.5"
        title="Filled in from the reference catalogue, not read from this invoice. Confirm it to make it yours."
      >
        <Sparkles size={10} /> PharmaGPT suggestion
      </span>
    ) : acknowledged && !hasValue ? (
      /* Not a tag on data — it labels an absence, and it is the only thing
         that explains why an empty required field is not holding the product
         up. Without it a deliberate blank looks identical to an unanswered
         one, and gets researched again next visit. */
      <span
        className="text-[9px] font-medium text-gray-400"
        title="Recorded as genuinely absent — no invoice states it."
      >
        none on invoice
      </span>
    ) : null}
  </div>
);

const inputClass =
  'w-full bg-[#f8fafc] border border-[#e2e8f0] rounded-xl px-3 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all duration-200';

export const ProductsPage: React.FC = () => {
  const [products, setProducts] = useState<Product[]>([]);
  const [summary, setSummary] = useState<ProductSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<'needs_review' | 'confirmed' | 'all'>('needs_review');
  const [searchTerm, setSearchTerm] = useState('');

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [detail, setDetail] = useState<Product | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // The catalogue answers two different questions and used to answer only the
  // second: "what still needs me?" and "what do we stock?". The queue is the
  // default because on any catalogue with outstanding work it is the one the
  // user came to act on.
  const [view, setView] = useState<'queue' | 'catalogue' | 'duplicates' | 'reference'>('queue');
  const [queue, setQueue] = useState<ReviewQueueResponse | null>(null);
  const [queueBusy, setQueueBusy] = useState(true);
  const [duplicates, setDuplicates] = useState<DuplicateResponse | null>(null);
  const [duplicatesBusy, setDuplicatesBusy] = useState(false);
  const [refStatus, setRefStatus] = useState<ReferenceStatus | null>(null);
  const [reference, setReference] = useState<ReferenceSuggestResponse | null>(null);
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [referenceApplying, setReferenceApplying] = useState(false);

  // Ids being stepped through one at a time. Working a band is the whole
  // point of a queue: saving one item should present the next, not drop the
  // reviewer back to a list to find their place again.
  const [walk, setWalk] = useState<string[]>([]);

  const showToast = (text: string) => {
    setToast(text);
    setTimeout(() => setToast(null), 2600);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getProducts({ status: statusFilter, search: searchTerm });
      setProducts(data.products);
      setSummary(data.summary);
    } catch (e: any) {
      setError(e?.message || 'Could not reach the catalogue service.');
      setProducts([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, searchTerm]);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, searchTerm ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, searchTerm]);

  // Does not raise the busy flag itself. queueBusy starts true, so the first
  // load is already covered, and a reload triggered by an effect must not
  // call setState synchronously from inside it. Callers that reload in
  // response to a user action raise the flag themselves, below.
  const loadQueue = useCallback(async () => {
    try {
      setQueue(await apiClient.getReviewQueue());
    } catch (e: any) {
      setError(e?.message || 'Could not reach the catalogue service.');
      setQueue(null);
    } finally {
      setQueueBusy(false);
    }
  }, []);

  // Deferred rather than called straight from the effect body, matching how
  // the catalogue list above loads. A fetch kicked off synchronously inside an
  // effect settles its state during the same commit, which React flags as a
  // cascading render.
  useEffect(() => {
    const timer = setTimeout(loadQueue, 0);
    return () => clearTimeout(timer);
  }, [loadQueue]);

  useEffect(() => {
    const timer = setTimeout(
      () => apiClient.getReferenceStatus().then(setRefStatus).catch(() => setRefStatus({ available: false })),
      0
    );
    return () => clearTimeout(timer);
  }, []);

  const scanReference = useCallback(async () => {
    setReferenceBusy(true);
    try {
      setReference(await apiClient.getReferenceSuggestions([]));
    } catch (e: any) {
      showToast(e?.message || 'Reference lookup failed.');
    } finally {
      setReferenceBusy(false);
    }
  }, []);

  const scanDuplicates = useCallback(async () => {
    setDuplicatesBusy(true);
    try {
      setDuplicates(await apiClient.getProductDuplicates());
    } catch (e: any) {
      showToast(e?.message || 'Could not check for duplicates.');
    } finally {
      setDuplicatesBusy(false);
    }
  }, []);

  // Anything that changes the catalogue invalidates all three views, so they
  // are refreshed together rather than leaving a stale count on a tab the user
  // is about to switch to.
  const refreshAll = useCallback(async () => {
    setQueueBusy(true);
    await Promise.all([load(), loadQueue()]);
    // Only re-run the duplicate scan if the user had asked for one; it is the
    // most expensive of the three and nobody asked for it in the background.
    if (duplicates) await scanDuplicates();
  }, [load, loadQueue, scanDuplicates, duplicates]);

  const applyReference = async (
    items: Array<{ product_id: string; fields: Record<string, any> }>
  ) => {
    setReferenceApplying(true);
    try {
      const result = await apiClient.applyReferenceSuggestions(items);
      showToast(
        result.skipped.length === 0
          ? `Filled in ${result.applied.length} product${result.applied.length === 1 ? '' : 's'}.`
          : `Filled in ${result.applied.length}; ${result.skipped.length} need a closer look.`
      );
      await refreshAll();
      await scanReference();
    } catch (e: any) {
      showToast(e?.message || 'Could not apply reference details.');
    } finally {
      setReferenceApplying(false);
    }
  };

  const handleApprove = async (productIds: string[]) => {
    try {
      const result = await apiClient.bulkConfirmProducts(productIds);
      const skipped = result.skipped.length;
      showToast(
        skipped === 0
          ? `Approved ${result.confirmed.length} ${result.confirmed.length === 1 ? 'product' : 'products'}.`
          : `Approved ${result.confirmed.length}; ${skipped} need a closer look.`
      );
      await refreshAll();
    } catch (e: any) {
      showToast(e?.message || 'Could not approve those products.');
    }
  };

  // Opens the first item of a band and remembers the rest, so "Save" moves to
  // the next one instead of closing.
  const workThroughBand = async (band: ReviewBand) => {
    const ids = (queue?.items || []).filter((i) => i.band === band).map((i) => i.product_id);
    if (ids.length === 0) return;
    setWalk(ids);
    await openDetail(ids[0]);
  };

  // Advances the walk. Returns false when there is nothing after this one,
  // which is what tells the drawer to close instead of advancing.
  const advanceWalk = async (currentId: string): Promise<boolean> => {
    const index = walk.indexOf(currentId);
    const nextId = index >= 0 ? walk[index + 1] : undefined;
    if (!nextId) {
      setWalk([]);
      return false;
    }
    await openDetail(nextId);
    return true;
  };

  const openDetail = async (productId: string) => {
    try {
      setDetail(await apiClient.getProduct(productId));
    } catch (e: any) {
      showToast(e?.message || 'Could not open that product.');
    }
  };

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  };

  const handleMerge = async () => {
    if (selectedIds.length < 2) return;
    const [target, ...sources] = selectedIds;
    try {
      await apiClient.mergeProducts(sources, target);
      showToast(`Merged ${sources.length + 1} items into one product.`);
      setSelectedIds([]);
      await load();
    } catch (e: any) {
      showToast(e?.message || 'Merge failed.');
    }
  };

  const selectedProducts = useMemo(
    () => products.filter((p) => selectedIds.includes(p.id)),
    [products, selectedIds]
  );

  return (
    <div className="space-y-6 animate-fade-in">
      {toast && (
        <div className="fixed top-20 right-6 bg-[#0f172a] text-white px-4 py-3 rounded-xl text-xs font-semibold z-50 shadow-xl flex items-center space-x-2">
          <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />
          <span>{toast}</span>
        </div>
      )}

      <div>
        <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Product Catalogue</h2>
        <p className="text-gray-500 text-sm">
          Every medicine on a <span className="font-semibold text-gray-600">verified</span> invoice,
          resolved into one master record. Confirm what each item actually is — strength, form and units
          per pack — so stock and tax stop depending on how a distributor happened to spell it.
        </p>
      </div>

      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatTile
            label="Awaiting Review"
            value={summary.needs_review}
            icon={Package}
            tone="blue"
            hint={`${summary.total} products in catalogue`}
          />
          <StatTile
            label="Missing Pack Size"
            value={summary.missing_pack_multiplier}
            icon={Layers}
            tone="amber"
            hint="Tablet-level stock unavailable"
          />
          <StatTile
            label="Price Conflicts"
            value={summary.price_conflicts}
            icon={AlertTriangle}
            tone="red"
            hint="Likely two items merged as one"
          />
          <StatTile
            label="Missing HSN"
            value={summary.missing_hsn}
            icon={FileText}
            tone="green"
            hint="Needed for GSTR-2B"
          />
        </div>
      )}

      {/* View switch. The queue and the catalogue are different jobs — one is
          "what needs me", the other "what do we stock" — and collapsing them
          into a single table is what made the section feel like homework. */}
      <div className="flex items-center gap-1 bg-[#f4f5fa] rounded-xl p-1 text-xs font-semibold w-fit">
        {([
          ['queue', 'Review queue', ListChecks, queue?.total_outstanding],
          ['catalogue', 'Full catalogue', Table2, summary?.total],
          ['duplicates', 'Duplicates', GitMerge, duplicates?.candidates.length],
          ['reference', 'Autofill', BookOpen, reference?.fillable]
        ] as const).map(([value, label, Icon, count]) => (
          <button
            key={value}
            onClick={() => setView(value)}
            className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg transition-colors cursor-pointer ${
              view === value ? 'bg-white text-[#1b5dfc] shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon size={13} />
            {label}
            {count !== undefined && count !== null && count > 0 && (
              <span
                className={`px-1.5 py-0.5 rounded-full text-[9px] font-bold ${
                  view === value ? 'bg-blue-50 text-[#1b5dfc]' : 'bg-[#e2e8f0] text-gray-500'
                }`}
              >
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {view === 'queue' && queue && (
        <ReviewQueue
          data={queue}
          busy={queueBusy}
          onOpen={openDetail}
          onReviewBand={workThroughBand}
          onApprove={handleApprove}
        />
      )}

      {view === 'queue' && !queue && queueBusy && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm py-16 text-center text-gray-400">
          <Loader2 size={20} className="animate-spin inline-block mr-2" />
          Working out what still needs you...
        </div>
      )}

      {view === 'reference' && (
        <ReferenceFillPanel
          status={refStatus}
          data={reference}
          busy={referenceBusy}
          applying={referenceApplying}
          onScan={scanReference}
          onApply={applyReference}
        />
      )}

      {view === 'duplicates' && (
        <DuplicatesPanel
          data={duplicates}
          busy={duplicatesBusy}
          products={products}
          onScan={scanDuplicates}
          onMerge={async (sources, target) => {
            try {
              await apiClient.mergeProducts(sources, target);
              showToast('Merged into one product.');
              await refreshAll();
              await scanDuplicates();
            } catch (e: any) {
              showToast(e?.message || 'Merge failed.');
            }
          }}
        />
      )}

      {view === 'catalogue' && (
      <>
      {/* Toolbar */}
      <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex flex-col md:flex-row md:items-center gap-4">
        <div className="relative w-full md:max-w-md">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by product, brand, HSN, or invoice spelling..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-[#f4f5fa] border border-transparent rounded-xl pl-9 pr-4 py-2 text-xs text-[#0f172a] focus:outline-none focus:bg-white focus:border-blue-500 transition-all duration-200"
          />
        </div>

        <div className="flex items-center bg-[#f4f5fa] rounded-xl p-1 text-xs font-semibold">
          {([
            ['needs_review', 'Needs review'],
            ['confirmed', 'Confirmed'],
            ['all', 'All']
          ] as const).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
                statusFilter === value ? 'bg-white text-[#1b5dfc] shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {selectedIds.length >= 2 && (
          <button
            onClick={handleMerge}
            className="md:ml-auto flex items-center gap-1.5 bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-blue-500/10 transition-colors cursor-pointer"
            title={`Merge into "${selectedProducts[0]?.canonical_name || ''}"`}
          >
            <GitMerge size={13} />
            Merge {selectedIds.length} into one
          </button>
        )}
        {selectedIds.length === 1 && (
          <span className="md:ml-auto text-[10px] text-gray-400 font-medium">
            Select one more item to merge
          </span>
        )}
      </div>

      {/* Catalogue table */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                <th className="p-4 pl-6 w-10" />
                <th className="p-4">Product</th>
                <th className="p-4">Strength / Form</th>
                <th className="p-4">Pack / Units</th>
                <th className="p-4">HSN</th>
                <th className="p-4 text-right">Seen</th>
                <th className="p-4">Completeness</th>
                <th className="p-4 pr-6">Needs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0] text-xs text-gray-700">
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-16 text-gray-400">
                    <Loader2 size={20} className="animate-spin inline-block mr-2" />
                    Loading catalogue...
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={8} className="text-center py-16">
                    <AlertTriangle size={22} className="text-amber-500 inline-block mb-2" />
                    <p className="text-gray-500 font-medium">{error}</p>
                    <button
                      onClick={load}
                      className="mt-3 text-[#1b5dfc] font-semibold text-xs hover:underline cursor-pointer"
                    >
                      Retry
                    </button>
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-16 text-gray-400 font-medium">
                    {searchTerm
                      ? 'No products match that search.'
                      : statusFilter === 'needs_review'
                      ? 'Nothing waiting for review — every item on a verified invoice has been classified.'
                      : // Says "verified", not just "scanned": items only reach
                        // the catalogue once an invoice has been checked, so
                        // "scan an invoice and they appear here" would send
                        // someone hunting for a bug that isn't one.
                        'No products yet. Items appear here once you mark an invoice as verified.'}
                  </td>
                </tr>
              ) : (
                products.map((product) => {
                  const high = product.flags.filter((f) => f.severity === 'high');
                  const medium = product.flags.filter((f) => f.severity === 'medium');
                  const selected = selectedIds.includes(product.id);

                  return (
                    <tr
                      key={product.id}
                      onClick={() => openDetail(product.id)}
                      className={`group hover:bg-[#f8fafc] transition-colors cursor-pointer ${
                        selected ? 'bg-blue-50/60' : ''
                      }`}
                    >
                      <td className="p-4 pl-6" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleSelected(product.id)}
                          className="rounded border-gray-300 text-[#1b5dfc] focus:ring-blue-500 cursor-pointer"
                          aria-label={`Select ${product.canonical_name}`}
                        />
                      </td>

                      <td className="p-4">
                        <span className="font-semibold text-[#0f172a] block group-hover:text-[#1b5dfc] group-hover:underline underline-offset-2">
                          {product.brand || product.canonical_name || 'Unnamed item'}
                        </span>
                        {product.aliases.length > 1 && (
                          <span className="text-[10px] text-gray-400 flex items-center gap-1 mt-0.5">
                            <Layers size={10} />
                            {product.aliases.length} spellings merged
                          </span>
                        )}
                        {product.aliases.length === 1 && product.aliases[0].raw_name !== product.brand && (
                          <span className="text-[10px] text-gray-400 font-mono block mt-0.5 truncate max-w-xs">
                            {product.aliases[0].raw_name}
                          </span>
                        )}
                      </td>

                      <td className="p-4">
                        <span className="text-[#0f172a] font-medium">{product.strength || '—'}</span>
                        <span className="block text-[10px] text-gray-400">{product.form || 'form unknown'}</span>
                      </td>

                      <td className="p-4">
                        <span className="text-[#0f172a] font-medium">{product.pack_size || '—'}</span>
                        <span className="block text-[10px] text-gray-400">
                          {product.pack_multiplier
                            ? `${product.pack_multiplier} ${(product.base_unit || 'unit').toLowerCase()}/pack`
                            : 'units per pack unknown'}
                        </span>
                      </td>

                      <td className="p-4 font-mono text-[11px] text-gray-500">{product.hsn || '—'}</td>

                      <td className="p-4 text-right">
                        <span className="font-semibold text-[#0f172a]">{product.times_seen}×</span>
                        <span className="block text-[10px] text-gray-400">
                          {product.invoice_count} invoice{product.invoice_count === 1 ? '' : 's'}
                        </span>
                      </td>

                      <td className="p-4">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-[#e2e8f0] rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                product.completeness === 1
                                  ? 'bg-green-500'
                                  : product.completeness >= 0.5
                                  ? 'bg-amber-500'
                                  : 'bg-red-500'
                              }`}
                              style={{ width: `${product.completeness * 100}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-gray-400 font-semibold">
                            {Math.round(product.completeness * 100)}%
                          </span>
                        </div>
                      </td>

                      <td className="p-4 pr-6">
                        {product.review_status === 'confirmed' && high.length === 0 && medium.length === 0 ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-50 text-green-700 border border-green-200">
                            Confirmed
                          </span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {high.slice(0, 2).map((flag) => (
                              <span
                                key={flag.code}
                                title={flag.message}
                                className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-200"
                              >
                                {flag.code.replace(/^missing_/, '').replace(/_/g, ' ')}
                              </span>
                            ))}
                            {medium.slice(0, high.length ? 1 : 2).map((flag) => (
                              <span
                                key={flag.code}
                                title={flag.message}
                                className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200"
                              >
                                {flag.code.replace(/^missing_/, '').replace(/_/g, ' ')}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      </>
      )}

      {detail && (
        <ProductDetailDrawer
          // Remounts per product. The drawer seeds its form from props on
          // first render, so without this, advancing through a walk would
          // leave the previous item's values in the boxes - editing one
          // product while displaying another.
          key={detail.id}
          product={detail}
          // Position in the walk, so the drawer can say "3 of 11" and offer to
          // move on rather than closing back to a list.
          walkPosition={
            walk.indexOf(detail.id) >= 0
              ? { index: walk.indexOf(detail.id) + 1, total: walk.length }
              : null
          }
          onClose={() => {
            setDetail(null);
            setWalk([]);
          }}
          onSaved={async (message) => {
            showToast(message);
            await refreshAll();
          }}
          onAdvance={() => advanceWalk(detail.id)}
          onReplace={setDetail}
        />
      )}
    </div>
  );
};

// --------------------------------------------------------------------------

const ProductDetailDrawer: React.FC<{
  product: Product;
  // Set when the user is working through a band rather than opening one item.
  walkPosition: { index: number; total: number } | null;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
  // Moves to the next item in the walk. Resolves false when this was the last
  // one, which is the drawer's cue to close.
  onAdvance: () => Promise<boolean>;
  onReplace: (product: Product) => void;
}> = ({ product, walkPosition, onClose, onSaved, onAdvance, onReplace }) => {
  // Only the active types are offered, but the product's own form is kept in
  // the list even if that type has since been switched off — otherwise opening
  // an older product would silently blank its form on the next save.
  const [vocabulary, setVocabulary] = useState<ItemType[]>([]);
  const [knownUnits, setKnownUnits] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiClient.listItemTypes(true).then((data) => {
      if (cancelled) return;
      setVocabulary(data.item_types);
      setKnownUnits(data.known_units);
    }).catch(() => { /* pickers fall back to whatever the product already has */ });
    return () => { cancelled = true; };
  }, []);

  const [form, setForm] = useState({
    brand: product.brand || '',
    strength: product.strength || '',
    form: product.form || '',
    pack_size: product.pack_size || '',
    pack_multiplier: product.pack_multiplier?.toString() || '',
    base_unit: product.base_unit || '',
    manufacturer: product.manufacturer || '',
    composition: product.composition || '',
    hsn: product.hsn || '',
    schedule: product.schedule || '',
    notes: product.notes || ''
  });
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<Product | null>(null);
  const [splitting, setSplitting] = useState<ProductAlias | null>(null);
  // The reference lookup is local, so it runs on open rather than waiting to
  // be asked. The online lookup still needs a click - that one costs someone
  // else a request.
  const [refProposal, setRefProposal] = useState<ReferenceProposal | null>(null);
  const [refBusy, setRefBusy] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getReferenceSuggestions([product.id])
      .then((data) => {
        if (!cancelled) setRefProposal(data.results[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setRefProposal(null);
      })
      .finally(() => {
        if (!cancelled) setRefBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [product.id]);

  const acknowledged = new Set(product.acknowledged_fields || []);
  const suggested = new Set(product.suggested_fields || []);
  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  // Choosing a dosage form answers two other questions at the same time: what
  // the item is counted in, and — for anything sold as a single container —
  // how many units are in a pack. Filling them here saves the reviewer
  // restating what they just said, and stops the three fields contradicting
  // each other.
  //
  // Only fills what is still blank. A value already on the record was either
  // read from the invoice or typed by a person, and neither should be
  // overwritten as a side effect of picking from a dropdown.
  const setDosageForm = (value: string) =>
    setForm((f) => {
      const next = { ...f, form: value };
      const type = vocabulary.find((t) => t.name === value);
      if (type?.base_unit && !f.base_unit) next.base_unit = type.base_unit;
      // A unit carried over from a different form may not be valid for this
      // one; the server refuses those, so correct it here rather than letting
      // the save fail.
      if (type && f.base_unit && !type.supported_units.includes(f.base_unit)) {
        next.base_unit = type.base_unit;
      }
      if (type?.single_container && !f.pack_multiplier) {
        next.pack_multiplier = '1';
      }
      return next;
    });

  // Active types, plus this product's own form if its type was switched off.
  const formOptions = React.useMemo(() => {
    const names = vocabulary.filter((t) => t.active).map((t) => t.name);
    if (form.form && !names.includes(form.form)) names.push(form.form);
    return names;
  }, [vocabulary, form.form]);

  // Only the units this form supports. With no matching type (an unknown or
  // retired form) every known unit is offered rather than none.
  //
  // The product's own unit is always among them, the same way formOptions
  // keeps its own form. Without that, a vocabulary that failed to load - or
  // simply no longer lists this form - leaves a select with no option
  // matching its value, which renders as "Not set" over a unit the product
  // does have. The record is unharmed until someone believes the picker and
  // touches it.
  const unitOptions = React.useMemo(() => {
    const type = vocabulary.find((t) => t.name === form.form);
    const units = type?.supported_units?.length ? [...type.supported_units] : [...knownUnits];
    if (form.base_unit && !units.includes(form.base_unit)) units.push(form.base_unit);
    return units;
  }, [vocabulary, knownUnits, form.form, form.base_unit]);

  const payload = () => ({
    ...form,
    // An empty box means "no value", not the empty string — otherwise the
    // completeness check would count a blank as filled.
    brand: form.brand.trim() || null,
    strength: form.strength.trim() || null,
    form: form.form || null,
    pack_size: form.pack_size.trim() || null,
    pack_multiplier: form.pack_multiplier.trim() ? Number(form.pack_multiplier) : null,
    base_unit: form.base_unit || null,
    manufacturer: form.manufacturer.trim() || null,
    composition: form.composition.trim() || null,
    hsn: form.hsn.trim() || null,
    schedule: form.schedule || null,
    notes: form.notes.trim() || null
  });

  const save = async (confirm: boolean, allowMerge = false) => {
    setSaving(true);
    setConflict(null);
    try {
      const result = await apiClient.updateProduct(product.id, {
        ...payload(),
        confirm,
        allow_merge: allowMerge
      });
      if (result.status === 'conflict' && result.conflict) {
        setConflict(result.conflict);
        return;
      }
      await onSaved(confirm ? 'Product confirmed.' : 'Changes saved.');
      // Mid-walk, saving means "done with this one" — so the next item opens
      // rather than the reviewer being returned to the list to find their
      // place. The walk closing itself on the last item is what tells them
      // the band is finished.
      if (walkPosition && (await onAdvance())) return;
      onClose();
    } catch (e: any) {
      await onSaved(e?.message || 'Save failed.');
    } finally {
      setSaving(false);
    }
  };

  // Skipping leaves the item exactly as it is and moves on. A reviewer who
  // cannot answer this one now must be able to keep going; without it the
  // only way past a hard item is to abandon the whole band.
  const skip = async () => {
    if (!(await onAdvance())) onClose();
  };

  const doSplit = async (alias: ProductAlias, overrides: Record<string, any>) => {
    try {
      const created = await apiClient.splitAlias(alias.id, overrides);
      await onSaved(`"${alias.raw_name}" split into its own product.`);
      setSplitting(null);
      onReplace(created);
    } catch (e: any) {
      await onSaved(e?.message || 'Split failed.');
    }
  };

  const priceRange =
    product.observed_mrps.length > 0
      ? `${currency(product.observed_mrps[0])} – ${currency(product.observed_mrps[product.observed_mrps.length - 1])}`
      : '—';

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-xs" onClick={onClose}>
      <aside
        className="w-full max-w-3xl bg-[#f4f5fa] h-full overflow-y-auto shadow-2xl animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer header */}
        <div className="sticky top-0 bg-white border-b border-[#e2e8f0] px-6 py-4 flex items-start justify-between z-10">
          <div className="min-w-0">
            {walkPosition && (
              <span className="text-[10px] font-bold text-[#1b5dfc] uppercase tracking-wider block mb-0.5">
                Reviewing {walkPosition.index} of {walkPosition.total}
              </span>
            )}
            <h3 className="text-lg font-bold text-[#0f172a] truncate">
              {product.brand || product.canonical_name || 'Unnamed item'}
            </h3>
            <p className="text-[10px] text-gray-400 font-mono truncate">{product.identity_key}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-4">
            <span
              className={`px-2 py-1 rounded text-[10px] font-bold border ${
                product.review_status === 'confirmed'
                  ? 'bg-green-50 text-green-700 border-green-200'
                  : 'bg-amber-50 text-amber-700 border-amber-200'
              }`}
            >
              {product.review_status === 'confirmed' ? 'Confirmed' : 'Needs review'}
            </span>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-[#f4f5fa] rounded-lg transition-colors cursor-pointer"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="p-6 space-y-5">
          {/* Conflict banner — a decision, not an error. */}
          {conflict && (
            <div className="bg-white border border-blue-200 rounded-2xl p-4 shadow-sm space-y-3">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-blue-50 text-[#1b5dfc] rounded-xl shrink-0">
                  <GitMerge size={18} />
                </div>
                <div className="text-xs">
                  <p className="font-bold text-[#0f172a]">These details already describe another product.</p>
                  <p className="text-gray-500 mt-0.5">
                    “{conflict.canonical_name}” has the same brand, strength, form and pack. Merging keeps one
                    record with both purchase histories. Your edits were saved either way.
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setConflict(null)}
                  className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 cursor-pointer"
                >
                  Keep separate
                </button>
                <button
                  onClick={() => save(false, true)}
                  className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs cursor-pointer"
                >
                  Merge them
                </button>
              </div>
            </div>
          )}

          {/* Flags */}
          {product.flags.length > 0 && (
            <div className="space-y-2">
              {product.flags.map((flag: ProductFlag) => (
                <div
                  key={flag.code}
                  className={`flex items-start gap-2 px-4 py-2.5 rounded-xl border text-xs ${
                    SEVERITY_STYLES[flag.severity]
                  }`}
                >
                  {flag.severity === 'high' ? (
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  ) : (
                    <Info size={14} className="shrink-0 mt-0.5" />
                  )}
                  <span className="font-medium">{flag.message}</span>
                </div>
              ))}
            </div>
          )}

          {/* Reference catalogue — instant, local, and the first thing to try. */}
          <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 space-y-3">
            <div>
              <h4 className="text-sm font-bold text-[#0f172a] flex items-center gap-1.5">
                <BookOpen size={14} className="text-gray-400" />
                Reference catalogue
              </h4>
              <p className="text-[11px] text-gray-500">
                What a local index of Indian products says about this name. Only fields every
                matching listing agrees on are offered; nothing is saved until you press save.
              </p>
            </div>
            <ReferenceInline
              proposal={refProposal}
              busy={refBusy}
              suggestedFields={product.suggested_fields || []}
              onApply={(fields) =>
                setForm((prev) => ({
                  ...prev,
                  ...Object.fromEntries(
                    Object.entries(fields).map(([k, v]) => [k, v === null ? '' : String(v)])
                  )
                }))
              }
            />
          </section>

          {/* Catalogue fields */}
          <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 space-y-4">
            <div>
              <h4 className="text-sm font-bold text-[#0f172a]">Catalogue details</h4>
              <p className="text-[11px] text-gray-500">
                What this medicine is. Applies to every invoice that mentions it.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <FieldLabel label="Brand / Product name" acknowledged={acknowledged.has('brand')} suggested={suggested.has('brand')} hasValue={!!form.brand} />
                <input className={inputClass} value={form.brand} onChange={(e) => set('brand')(e.target.value)} placeholder="e.g. MONTICOPE" />
              </div>

              <div>
                <FieldLabel label="Dosage strength" acknowledged={acknowledged.has('strength')} suggested={suggested.has('strength')} hasValue={!!form.strength} />
                <input className={inputClass} value={form.strength} onChange={(e) => set('strength')(e.target.value)} placeholder="e.g. 10MG" />
              </div>

              <div>
                <FieldLabel label="Dosage form" acknowledged={acknowledged.has('form')} suggested={suggested.has('form')} hasValue={!!form.form} />
                <select className={inputClass} value={form.form} onChange={(e) => setDosageForm(e.target.value)}>
                  <option value="">Not set</option>
                  {formOptions.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>

              <div>
                <FieldLabel label="Pack size" acknowledged={acknowledged.has('pack_size')} suggested={suggested.has('pack_size')} hasValue={!!form.pack_size} />
                <input className={inputClass} value={form.pack_size} onChange={(e) => set('pack_size')(e.target.value)} placeholder="e.g. 1*10, 15'S, 100ML" />
              </div>

              <div>
                <FieldLabel label="Units per pack" acknowledged={acknowledged.has('pack_multiplier')} suggested={suggested.has('pack_multiplier')} hasValue={!!form.pack_multiplier} />
                <input
                  className={inputClass}
                  type="number"
                  min="0"
                  step="1"
                  value={form.pack_multiplier}
                  onChange={(e) => set('pack_multiplier')(e.target.value)}
                  placeholder="e.g. 10"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  {/* A lotion has no "individual units" to count — it is one
                      bottle whose size is a volume. Saying otherwise asks the
                      reviewer a question their product doesn't have. */}
                  {vocabulary.find((t) => t.name === form.form)?.single_container
                    ? `A ${form.form.toLowerCase()} is sold as one container, so this is 1 — its size is recorded as the pack size.`
                    : 'Individual tablets, vials or sachets in one pack — this is what turns billed packs into countable stock.'}
                </p>
              </div>

              <div>
                {/* When a form is set, the unit follows from it rather than
                    being read separately - so it is shown with the form's own
                    confidence, not the lower number the parser records for a
                    value it derived. Calling it a guess here would contradict
                    the review queue, which does not ask about it at all. */}
                <FieldLabel
                  label="Dispensing unit" acknowledged={acknowledged.has('base_unit')} suggested={suggested.has('base_unit')}
                  hasValue={!!form.base_unit}
                />
                <select className={inputClass} value={form.base_unit} onChange={(e) => set('base_unit')(e.target.value)}>
                  <option value="">Not set</option>
                  {unitOptions.map((u: string) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
              </div>

              <div>
                <FieldLabel label="Manufacturer" acknowledged={acknowledged.has('manufacturer')} suggested={suggested.has('manufacturer')} hasValue={!!form.manufacturer} />
                <input className={inputClass} value={form.manufacturer} onChange={(e) => set('manufacturer')(e.target.value)} placeholder="e.g. Mankind" />
              </div>

              <div className="sm:col-span-2">
                <FieldLabel label="Salt composition" acknowledged={acknowledged.has('composition')} suggested={suggested.has('composition')} hasValue={!!form.composition} />
                <input className={inputClass} value={form.composition} onChange={(e) => set('composition')(e.target.value)} placeholder="e.g. Olmesartan Medoxomil 20mg + Amlodipine 5mg" />
                <p className="text-[10px] text-gray-400 mt-1">
                  What is actually in it. Invoices never print this — it comes from the reference
                  catalogue, and it is how you recognise that two differently-named products are
                  the same medicine.
                </p>
              </div>

              <div>
                <FieldLabel label="HSN code" acknowledged={acknowledged.has('hsn')} suggested={suggested.has('hsn')} hasValue={!!form.hsn} />
                <input className={inputClass} value={form.hsn} onChange={(e) => set('hsn')(e.target.value)} placeholder="e.g. 30049099" />
                {product.observed_hsns.length > 0 && (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Seen on invoices: {product.observed_hsns.join(', ')}
                  </p>
                )}
              </div>

              <div>
                <FieldLabel label="Schedule" acknowledged={acknowledged.has('schedule')} suggested={suggested.has('schedule')} hasValue={!!form.schedule} />
                <select className={inputClass} value={form.schedule} onChange={(e) => set('schedule')(e.target.value)}>
                  <option value="">Not set</option>
                  {SCHEDULES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <p className="text-[10px] text-gray-400 mt-1">
                  Never inferred from the name — a compliance claim nobody checked is worse than a blank.
                </p>
              </div>

              <div>
                <FieldLabel label="Notes" acknowledged={acknowledged.has('notes')} suggested={suggested.has('notes')} hasValue={!!form.notes} />
                <input className={inputClass} value={form.notes} onChange={(e) => set('notes')(e.target.value)} placeholder="Optional" />
              </div>
            </div>
          </section>

          {/* Spellings */}
          <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-5 space-y-3">
            <div>
              <h4 className="text-sm font-bold text-[#0f172a] flex items-center gap-1.5">
                <Tag size={14} className="text-gray-400" />
                Invoice spellings ({product.aliases.length})
              </h4>
              <p className="text-[11px] text-gray-500">
                Every name distributors have printed for this item. If one of these is really a different
                medicine, split it out.
              </p>
            </div>
            <div className="space-y-2">
              {product.aliases.map((alias) => (
                <div
                  key={alias.id}
                  className="flex items-center justify-between gap-3 bg-[#f8fafc] border border-[#e2e8f0] rounded-xl px-3 py-2"
                >
                  <div className="min-w-0">
                    <span className="text-xs font-mono text-[#0f172a] block truncate">{alias.raw_name}</span>
                    <span className="text-[10px] text-gray-400">
                      seen {alias.times_seen}×
                      {alias.status === 'new' && (
                        <span className="ml-1.5 text-amber-600 font-bold">new since last review</span>
                      )}
                    </span>
                  </div>
                  {product.aliases.length > 1 && (
                    <button
                      onClick={() => setSplitting(alias)}
                      className="shrink-0 flex items-center gap-1 text-[10px] font-semibold text-gray-500 hover:text-red-600 border border-gray-200 hover:border-red-200 bg-white rounded-lg px-2 py-1 transition-colors cursor-pointer"
                      title="Make this spelling its own product"
                    >
                      <Scissors size={11} /> Split
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Evidence */}
          <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm overflow-hidden">
            <div className="p-5 pb-3">
              <h4 className="text-sm font-bold text-[#0f172a]">Purchase history</h4>
              <p className="text-[11px] text-gray-500">
                The invoice lines behind this record. MRP range {priceRange} across {product.invoice_count}{' '}
                invoice{product.invoice_count === 1 ? '' : 's'}
                {product.vendors.length > 0 && ` from ${product.vendors.join(', ')}`}.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[#f8fafc] border-y border-[#e2e8f0] text-gray-400 font-semibold text-[10px] uppercase tracking-wider">
                    <th className="p-3 pl-5">Invoice</th>
                    <th className="p-3">Batch</th>
                    <th className="p-3">Expiry</th>
                    <th className="p-3 text-right">Qty</th>
                    <th className="p-3 text-right">Free</th>
                    <th className="p-3 text-right">MRP</th>
                    <th className="p-3 text-right">Rate</th>
                    <th className="p-3 text-right">GST</th>
                    <th className="p-3 pr-5 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#e2e8f0] text-[11px] text-gray-700">
                  {(product.observations || []).length === 0 ? (
                    <tr>
                      <td colSpan={9} className="text-center py-8 text-gray-400">
                        No invoice lines recorded.
                      </td>
                    </tr>
                  ) : (
                    (product.observations || []).map((obs) => (
                      <tr key={obs.id} className="hover:bg-[#f8fafc] transition-colors">
                        <td className="p-3 pl-5">
                          <span className="font-semibold text-[#0f172a] block">{obs.invoice_number || '—'}</span>
                          <span className="text-[10px] text-gray-400 block">{obs.invoice_date || ''}</span>
                          {obs.alias_name && (
                            <span className="text-[10px] text-gray-400 font-mono block truncate max-w-[12rem]">
                              {obs.alias_name}
                            </span>
                          )}
                        </td>
                        <td className="p-3 font-mono">{obs.batch_number || '—'}</td>
                        <td className="p-3">{obs.expiry_date || '—'}</td>
                        <td className="p-3 text-right font-semibold">{obs.quantity ?? '—'}</td>
                        <td className="p-3 text-right text-gray-500">{obs.free_quantity ?? '—'}</td>
                        <td className="p-3 text-right">{currency(obs.mrp)}</td>
                        <td className="p-3 text-right">{currency(obs.rate)}</td>
                        <td className="p-3 text-right text-gray-500">
                          {obs.gst_percent !== null && obs.gst_percent !== undefined ? `${obs.gst_percent}%` : '—'}
                        </td>
                        <td className="p-3 pr-5 text-right font-semibold text-[#0f172a]">{currency(obs.amount)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        {/* Sticky actions */}
        <div className="sticky bottom-0 bg-white border-t border-[#e2e8f0] px-6 py-4 flex items-center justify-between gap-3">
          <span className="text-[10px] text-gray-400">
            {product.total_base_units !== null
              ? `${product.total_base_units} ${(product.base_unit || 'unit').toLowerCase()} purchased in total`
              : product.base_unit
                // Name the unit this product is actually dispensed in. Saying
                // "tablet level" to someone editing a lotion describes a
                // different product than the one in front of them.
                ? `Set units per pack to track stock at ${product.base_unit.toLowerCase()} level`
                : 'Set dosage form and units per pack to track stock at unit level'}
          </span>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onClose}
              disabled={saving}
              className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50"
            >
              {walkPosition ? 'Stop' : 'Cancel'}
            </button>
            {walkPosition ? (
              <button
                onClick={skip}
                disabled={saving}
                className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
              >
                Skip
                <ArrowRight size={13} />
              </button>
            ) : (
              <button
                onClick={() => save(false)}
                disabled={saving}
                className="bg-white hover:bg-slate-50 text-[#1b5dfc] font-semibold px-4 py-2 rounded-xl text-xs border border-blue-200 shadow-sm transition-colors cursor-pointer disabled:opacity-50"
              >
                Save
              </button>
            )}
            <button
              onClick={() => save(true)}
              disabled={saving}
              className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-blue-500/10 transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
            >
              {saving ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              {walkPosition && walkPosition.index < walkPosition.total
                ? 'Confirm & next'
                : 'Save & confirm'}
            </button>
          </div>
        </div>

        {splitting && (
          <SplitDialog
            alias={splitting}
            onCancel={() => setSplitting(null)}
            onConfirm={(overrides) => doSplit(splitting, overrides)}
          />
        )}
      </aside>
    </div>
  );
};

// --------------------------------------------------------------------------

const SplitDialog: React.FC<{
  alias: ProductAlias;
  onCancel: () => void;
  onConfirm: (overrides: Record<string, any>) => void;
}> = ({ alias, onCancel, onConfirm }) => {
  const [strength, setStrength] = useState('');
  const [packSize, setPackSize] = useState('');
  const [packMultiplier, setPackMultiplier] = useState('');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs" onClick={onCancel}>
      <div
        className="bg-white rounded-2xl border border-gray-200 p-6 max-w-md w-full mx-4 shadow-xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start space-x-3">
          <div className="p-2 bg-amber-50 text-amber-600 rounded-xl shrink-0">
            <Scissors size={20} />
          </div>
          <div className="space-y-1 min-w-0">
            <h3 className="text-base font-bold text-[#0f172a]">Split this spelling into its own product</h3>
            <p className="text-xs text-gray-500 leading-normal">
              Every invoice line that arrived as{' '}
              <span className="font-mono font-semibold text-[#0f172a]">{alias.raw_name}</span> moves to a new
              record. Fill in what makes it different — without it, the new product is identical to the one it
              came from.
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider block mb-1.5">
              Strength
            </label>
            <input className={inputClass} value={strength} onChange={(e) => setStrength(e.target.value)} placeholder="e.g. 10MG" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider block mb-1.5">
                Pack size
              </label>
              <input className={inputClass} value={packSize} onChange={(e) => setPackSize(e.target.value)} placeholder="e.g. 1*15" />
            </div>
            <div>
              <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider block mb-1.5">
                Units per pack
              </label>
              <input className={inputClass} type="number" value={packMultiplier} onChange={(e) => setPackMultiplier(e.target.value)} placeholder="e.g. 15" />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end space-x-2 pt-2 border-t border-gray-100">
          <button
            onClick={onCancel}
            className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={() =>
              onConfirm({
                ...(strength.trim() ? { strength: strength.trim() } : {}),
                ...(packSize.trim() ? { pack_size: packSize.trim() } : {}),
                ...(packMultiplier.trim() ? { pack_multiplier: Number(packMultiplier) } : {})
              })
            }
            className="bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-blue-500/10 cursor-pointer"
          >
            Split it out
          </button>
        </div>
      </div>
    </div>
  );
};

export default ProductsPage;
