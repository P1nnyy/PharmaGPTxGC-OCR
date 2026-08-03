import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import {
  Upload,
  FileText,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Lightbulb,
  ShieldCheck,
  Zap,
  Boxes,
  Trash2,
  Files,
  X,
  ArrowUp,
  ArrowDown,
  Layers,
  RotateCw,
  RotateCcw
} from 'lucide-react';

interface UploadJob {
  id: number;
  file: File;
  status: 'uploading' | 'extracting' | 'success' | 'failed';
  progress: number;
  error: string | null;
  // Set once the backend has accepted the invoice, so a finished upload can
  // still be opened later instead of only at the instant it completes.
  runId: string | null;
}

export const UploadInvoicePage: React.FC = () => {
  const { uploadInvoiceFile, uploadInvoicePages } = useRun();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const multiInputRef = useRef<HTMLInputElement>(null);

  // States
  const [dragActive, setDragActive] = useState(false);
  // One entry per upload, rather than one set of fields shared by all of them.
  // The previous shape held a single file/status/progress, so starting a
  // second upload while the first was still in flight overwrote the first
  // one's identity: both progress timers then wrote to the same percentage,
  // and whichever request happened to finish first navigated away — showing
  // the wrong filename on the way out and discarding the other result.
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const jobSeq = useRef(0);

  const updateJob = (id: number, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, ...patch } : job)));

  const activeJobs = jobs.filter((j) => j.status === 'uploading' || j.status === 'extracting');

  // Multi-page invoice states
  const [multiDragActive, setMultiDragActive] = useState(false);
  const [pageFiles, setPageFiles] = useState<File[]>([]);
  const [showConfirm, setShowConfirm] = useState(false);
  const [multiStatus, setMultiStatus] = useState<'idle' | 'processing' | 'success' | 'failed'>('idle');
  const [multiError, setMultiError] = useState<string | null>(null);
  // Populated when the backend rejects the pages as belonging to different
  // invoices; lets the user see exactly what disagreed before overriding.
  const [pageMismatch, setPageMismatch] = useState<any>(null);
  // Lightbox for inspecting a queued page at full size before committing.
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  // The file behind the open lightbox, so a rotation made while enlarged is
  // written back to that page rather than lost on close.
  const [previewFile, setPreviewFile] = useState<File | null>(null);

  // Helper check: does any bench data exist to clear
  const hasBenchData = () => {
    const runs = localStorage.getItem('ocr_workbench_runs');
    let parsedRuns = [];
    if (runs) {
      try { parsedRuns = JSON.parse(runs); } catch {}
    }
    
    const inventory = localStorage.getItem('pharmaflow_inventory');
    let parsedInventory = [];
    if (inventory) {
      try { parsedInventory = JSON.parse(inventory); } catch {}
    }
    
    let hasDetail = false;
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (
        key.startsWith('ocr_workbench_run_detail_') || 
        key.startsWith('ocr_workbench_image_') || 
        key.startsWith('ocr_workbench_processed_image_')
      )) {
        hasDetail = true;
        break;
      }
    }
    
    return parsedRuns.length > 0 || parsedInventory.length > 0 || hasDetail || sessionStorage.length > 0;
  };

  const handleClearBenchClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.dispatchEvent(new CustomEvent('trigger-clear-bench'));
  };

  // Drag handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  // Main Upload and API call flow. Every write below targets one job id, so
  // concurrent uploads cannot overwrite each other's progress or status.
  const processFile = async (file: File) => {
    const id = ++jobSeq.current;
    setJobs((prev) => [
      ...prev,
      { id, file, status: 'uploading', progress: 15, error: null, runId: null }
    ]);

    // Simulate upload stages visually before final API call
    const progressTimer = setInterval(() => {
      setJobs((prev) =>
        prev.map((job) =>
          job.id === id && job.status === 'uploading'
            ? { ...job, progress: Math.min(job.progress + 10, 65) }
            : job
        )
      );
    }, 150);

    try {
      // Execute upload client call
      const newRun = await uploadInvoiceFile(file);

      clearInterval(progressTimer);
      updateJob(id, { status: 'success', progress: 100, runId: newRun.run_id });

      // Only leave the page when this was the sole upload in flight.
      // Navigating while another is still processing would abandon it
      // mid-flight and drop the user on a review screen for an invoice they
      // did not just finish; the completed card carries a Review button
      // instead, so nothing is lost either way.
      setJobs((prev) => {
        const othersBusy = prev.some(
          (job) => job.id !== id && (job.status === 'uploading' || job.status === 'extracting')
        );
        if (!othersBusy) {
          setTimeout(() => navigate(`/review/${newRun.run_id}`), 1000);
        }
        return prev;
      });
    } catch (err: any) {
      clearInterval(progressTimer);
      updateJob(id, {
        status: 'failed',
        error: err.message || 'Invoice processing failed. Please check image format validity.'
      });
    }
  };

  const retryJob = (job: UploadJob) => {
    setJobs((prev) => prev.filter((j) => j.id !== job.id));
    processFile(job.file);
  };

  const dismissJob = (id: number) => setJobs((prev) => prev.filter((j) => j.id !== id));

  // --- Multi-page invoice handling ------------------------------------------

  // Object URLs for the queued page previews. Filenames like
  // "WhatsApp Image 2026-07-31 at 16.16.04.jpeg" tell the user nothing about
  // which sheet is which, so the page itself has to be visible.
  const pagePreviews = useMemo(
    () => pageFiles.map((file) => URL.createObjectURL(file)),
    [pageFiles]
  );

  // Revoke the previous batch of URLs whenever the list changes, and on
  // unmount, so removed/reordered pages don't leak their blobs.
  useEffect(() => {
    return () => {
      pagePreviews.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [pagePreviews]);

  // Per-page preview rotation, in degrees.
  //
  // These previews cannot be rotated automatically. The review screen manages
  // it because Azure returns a page angle, but that only exists after the
  // extraction call. Before upload the only metadata that could orient an
  // image is its EXIF Orientation tag, and the photos this actually receives
  // do not carry one - WhatsApp re-encodes and strips EXIF, baking any
  // rotation into the pixels. There is nothing left to read, so orientation
  // here is the reviewer's call rather than a guess.
  //
  // Keyed by File identity, not list position: pages get reordered and
  // removed, and an index-keyed map would silently transfer one page's
  // rotation onto another.
  const [pageRotations, setPageRotations] = useState<Map<File, number>>(new Map());

  const rotationOf = (file: File) => pageRotations.get(file) ?? 0;

  const rotatePage = (file: File, delta: 90 | -90) => {
    setPageRotations((prev) => {
      const next = new Map(prev);
      next.set(file, (((rotationOf(file) + delta) % 360) + 360) % 360);
      return next;
    });
  };

  const addPageFiles = (incoming: FileList | File[]) => {
    const accepted = Array.from(incoming).filter((f) => f.type.startsWith('image/'));
    if (accepted.length === 0) return;
    setMultiError(null);
    setPageMismatch(null);
    setMultiStatus('idle');
    // Append rather than replace, so pages can be added in several drops.
    setPageFiles((prev) => [...prev, ...accepted]);
  };

  const handleMultiDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setMultiDragActive(true);
    else if (e.type === 'dragleave') setMultiDragActive(false);
  };

  const handleMultiDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setMultiDragActive(false);
    if (e.dataTransfer.files?.length) addPageFiles(e.dataTransfer.files);
  };

  const movePage = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= pageFiles.length) return;
    setPageFiles((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const removePage = (index: number) => {
    setPageFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const submitPages = async (force = false) => {
    setShowConfirm(false);
    setMultiStatus('processing');
    setMultiError(null);
    setPageMismatch(null);

    try {
      const newRun = await uploadInvoicePages(pageFiles, { force });
      setMultiStatus('success');
      setTimeout(() => navigate(`/review/${newRun.run_id}`), 800);
    } catch (err: any) {
      setMultiStatus('failed');
      if (err?.isPageMismatch) {
        setPageMismatch({ consistency: err.consistency, pages: err.pages });
        setMultiError(err.message);
      } else {
        setMultiError(err?.message || 'Multi-page invoice processing failed.');
      }
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">Upload New Invoice</h2>
          <p className="text-gray-500 text-sm">Upload single or multi-page pharma invoices to automatically extract SKU data.</p>
        </div>
        {hasBenchData() && (
          <button
            onClick={handleClearBenchClick}
            className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 hover:border-red-300 transition-all duration-200 cursor-pointer shadow-sm self-start sm:self-auto"
            title="Clear all locally stored invoice test runs, history, drafts, and inventory"
          >
            <Trash2 size={14} className="text-red-500" />
            <span>Clear Bench</span>
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
        {/* Left Side Dropzone and Specs (Span 3) */}
        <div className="lg:col-span-3 space-y-6">
          <div
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={triggerFileInput}
            className={`bg-white border-2 border-dashed rounded-3xl p-12 text-center cursor-pointer transition-all duration-300 flex flex-col items-center justify-center min-h-[350px] relative ${
              dragActive 
                ? 'border-[#1b5dfc] bg-blue-50/30' 
                : 'border-[#cbd5e1] hover:border-[#1b5dfc] hover:bg-slate-50/50'
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              accept="image/*,application/pdf"
              onChange={handleFileChange}
              className="hidden"
            />

            <div className="w-16 h-16 rounded-full bg-blue-50 text-[#1b5dfc] flex items-center justify-center mb-6">
              <Upload size={32} />
            </div>

            <h3 className="text-lg font-bold text-[#0f172a] mb-2">
              Drag and drop your invoice here or <span className="text-[#1b5dfc] hover:underline">click to browse</span>
            </h3>
            <p className="text-gray-500 text-xs max-w-md leading-relaxed mb-1">
              Supports PDF, JPG, and PNG. Extract medicines, batch, expiry, and tax details automatically.
            </p>
            <span className="text-[10px] text-gray-400">Max file size: 10MB</span>

            {dragActive && (
              <div className="absolute inset-0 bg-blue-500/5 rounded-3xl pointer-events-none border-2 border-[#1b5dfc] transition-all duration-200" />
            )}
          </div>

          {/* Multi-page invoice dropzone */}
          <div className="bg-white rounded-3xl border border-[#e2e8f0] shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-[#e2e8f0] flex items-center space-x-2.5">
              <div className="p-1.5 bg-indigo-50 text-indigo-600 rounded-lg">
                <Layers size={15} />
              </div>
              <div className="min-w-0">
                <h3 className="text-xs font-bold text-[#0f172a]">Multi-page invoice</h3>
                <p className="text-[10px] text-gray-500 leading-normal">
                  Drop every page of the <span className="font-semibold">same</span> invoice here — they'll be combined into one record.
                </p>
              </div>
            </div>

            <div
              onDragEnter={handleMultiDrag}
              onDragOver={handleMultiDrag}
              onDragLeave={handleMultiDrag}
              onDrop={handleMultiDrop}
              onClick={() => multiInputRef.current?.click()}
              className={`m-4 border-2 border-dashed rounded-2xl px-6 py-8 text-center cursor-pointer transition-all duration-300 ${
                multiDragActive
                  ? 'border-indigo-500 bg-indigo-50/40'
                  : 'border-[#cbd5e1] hover:border-indigo-400 hover:bg-slate-50/60'
              }`}
            >
              <input
                type="file"
                ref={multiInputRef}
                accept="image/*"
                multiple
                onChange={(e) => {
                  if (e.target.files?.length) addPageFiles(e.target.files);
                  e.target.value = '';
                }}
                className="hidden"
              />
              <div className="w-11 h-11 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center mx-auto mb-3">
                <Files size={20} />
              </div>
              <p className="text-sm font-semibold text-[#0f172a]">
                Drop pages here or <span className="text-indigo-600 hover:underline">browse</span>
              </p>
              <p className="text-[10px] text-gray-400 mt-1">
                Select 2 or more images. You can add them in any order and reorder below.
              </p>
            </div>

            {pageFiles.length > 0 && (
              <div className="px-4 pb-4 space-y-2">
                <div className="flex items-center justify-between px-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                    {pageFiles.length} page{pageFiles.length === 1 ? '' : 's'} queued
                  </span>
                  <button
                    onClick={() => { setPageFiles([]); setMultiError(null); setPageMismatch(null); setMultiStatus('idle'); }}
                    className="text-[10px] font-semibold text-gray-400 hover:text-red-500 transition-colors cursor-pointer"
                  >
                    Clear all
                  </button>
                </div>

                {pageFiles.map((file, index) => (
                  <div
                    key={`${file.name}-${index}`}
                    className="flex items-center gap-3 p-2.5 bg-slate-50 border border-slate-200/70 rounded-xl"
                  >
                    <span className="w-7 h-7 shrink-0 rounded-lg bg-indigo-600 text-white text-xs font-bold flex items-center justify-center">
                      {index + 1}
                    </span>
                    {/* The page itself — the only reliable way to tell which
                        sheet is which, since camera filenames are opaque. */}
                    <button
                      type="button"
                      onClick={() => { setPreviewUrl(pagePreviews[index]); setPreviewFile(file); }}
                      className="shrink-0 rounded-lg overflow-hidden border border-slate-300 bg-white hover:border-indigo-500 transition-colors cursor-zoom-in"
                      title="Click to enlarge"
                    >
                      {/* The rotation is applied to an inner wrapper rather
                          than the button, so the thumbnail's footprint in the
                          row stays the same size whichever way the page is
                          turned and the list does not jump about. */}
                      <div className="w-24 h-28 flex items-center justify-center overflow-hidden">
                        <img
                          src={pagePreviews[index]}
                          alt={`Page ${index + 1}`}
                          style={{ transform: `rotate(${rotationOf(file)}deg)` }}
                          className={
                            rotationOf(file) % 180 === 0
                              ? 'w-24 h-28 object-cover object-top transition-transform'
                              : // A quarter turn swaps the axes, so the box to
                                // fit within is the opposite one.
                                'h-24 w-28 object-cover object-top transition-transform'
                          }
                        />
                      </div>
                    </button>
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] font-semibold text-[#0f172a] truncate">{file.name}</p>
                      <p className="text-[9px] text-gray-400 font-mono">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                      <div className="mt-1 flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => rotatePage(file, -90)}
                          className="p-1 rounded-md border border-slate-300 bg-white text-gray-500 hover:text-indigo-600 hover:border-indigo-400 transition-colors cursor-pointer"
                          title="Rotate left"
                          aria-label={`Rotate page ${index + 1} left`}
                        >
                          <RotateCcw size={11} />
                        </button>
                        <button
                          type="button"
                          onClick={() => rotatePage(file, 90)}
                          className="p-1 rounded-md border border-slate-300 bg-white text-gray-500 hover:text-indigo-600 hover:border-indigo-400 transition-colors cursor-pointer"
                          title="Rotate right"
                          aria-label={`Rotate page ${index + 1} right`}
                        >
                          <RotateCw size={11} />
                        </button>
                        <span className="text-[9px] text-indigo-600 font-semibold ml-1">Click image to enlarge</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <button
                        onClick={() => movePage(index, -1)}
                        disabled={index === 0}
                        className="p-1 text-gray-400 hover:text-indigo-600 rounded transition-colors cursor-pointer disabled:opacity-25 disabled:cursor-not-allowed"
                        title="Move up"
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        onClick={() => movePage(index, 1)}
                        disabled={index === pageFiles.length - 1}
                        className="p-1 text-gray-400 hover:text-indigo-600 rounded transition-colors cursor-pointer disabled:opacity-25 disabled:cursor-not-allowed"
                        title="Move down"
                      >
                        <ArrowDown size={13} />
                      </button>
                      <button
                        onClick={() => removePage(index)}
                        className="p-1 text-gray-400 hover:text-red-500 rounded transition-colors cursor-pointer"
                        title="Remove page"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  </div>
                ))}

                {multiStatus === 'failed' && multiError && (
                  <div className="bg-red-50 border border-red-200/60 p-3 rounded-xl space-y-2">
                    <div className="flex items-start space-x-2 text-[11px] text-red-700">
                      <AlertTriangle size={13} className="text-red-600 shrink-0 mt-0.5" />
                      <div className="space-y-1 min-w-0">
                        <span className="font-bold block">{pageMismatch ? 'Pages may not match' : 'Processing failed'}</span>
                        <p className="text-[10px] text-red-600/90 leading-normal">{multiError}</p>
                      </div>
                    </div>

                    {pageMismatch && (
                      <div className="space-y-1.5 pl-5">
                        {(pageMismatch.consistency?.conflicts || []).map((c: any, i: number) => (
                          <p key={i} className="text-[10px] text-red-600/90 leading-normal">• {c.message}</p>
                        ))}
                        <div className="pt-1 space-y-0.5">
                          {(pageMismatch.pages || []).map((p: any) => (
                            <p key={p.page} className="text-[9px] text-gray-500 font-mono">
                              page {p.page}: {p.invoice_number || 'no invoice no.'} · {p.line_item_count} items
                            </p>
                          ))}
                        </div>
                        <button
                          onClick={() => submitPages(true)}
                          className="mt-1 text-[10px] font-bold text-red-700 underline hover:text-red-800 cursor-pointer"
                        >
                          They are the same invoice — combine anyway
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {multiStatus === 'success' && (
                  <div className="bg-green-50 border border-green-200/60 p-2.5 rounded-xl flex items-center space-x-2 text-[11px] text-green-700">
                    <CheckCircle2 size={13} className="text-green-600" />
                    <span className="font-semibold">Pages combined — opening review…</span>
                  </div>
                )}

                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={pageFiles.length < 2 || multiStatus === 'processing' || multiStatus === 'success'}
                  className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2.5 rounded-xl text-xs font-bold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
                >
                  {multiStatus === 'processing' ? (
                    <>
                      <RefreshCw size={13} className="animate-spin" />
                      <span>Processing {pageFiles.length} pages…</span>
                    </>
                  ) : (
                    <span>
                      {pageFiles.length < 2
                        ? 'Add at least 2 pages'
                        : `Combine ${pageFiles.length} pages into one invoice`}
                    </span>
                  )}
                </button>
              </div>
            )}
          </div>

          {/* Core Feature highlight boxes underneath */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-start space-x-3">
              <div className="p-2 bg-green-50 text-green-600 rounded-lg shrink-0">
                <ShieldCheck size={18} />
              </div>
              <div>
                <h4 className="text-xs font-bold text-[#0f172a] mb-1">99% Accuracy</h4>
                <p className="text-[10px] text-gray-500 leading-normal">
                  OCR engine optimized specifically for layout patterns in Indian pharmaceutical distribution.
                </p>
              </div>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-start space-x-3">
              <div className="p-2 bg-blue-50 text-[#1b5dfc] rounded-lg shrink-0">
                <Zap size={18} />
              </div>
              <div>
                <h4 className="text-xs font-bold text-[#0f172a] mb-1">Instant Processing</h4>
                <p className="text-[10px] text-gray-500 leading-normal">
                  Powered by cloud instances to structure and normalise tables in under 3 seconds per page.
                </p>
              </div>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-[#e2e8f0] shadow-sm flex items-start space-x-3">
              <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg shrink-0">
                <Boxes size={18} />
              </div>
              <div>
                <h4 className="text-xs font-bold text-[#0f172a] mb-1">Auto-Inventory</h4>
                <p className="text-[10px] text-gray-500 leading-normal">
                  Extracted row items are cross-linked directly for immediate SKU mapping and stock audits.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side queue and tips sidebar */}
        <div className="space-y-6">
          {/* Processing Queue panel */}
          <div className="bg-white rounded-2xl border border-[#e2e8f0] p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-[#e2e8f0]">
              <h4 className="text-xs font-bold text-[#0f172a] uppercase tracking-wider">Processing Queue</h4>
              {activeJobs.length > 0 && (
                <span className="bg-blue-50 text-[#1b5dfc] text-[10px] px-2 py-0.5 rounded-full font-bold animate-pulse">
                  {activeJobs.length} Active
                </span>
              )}
            </div>

            {jobs.length > 0 ? (
              <div className="space-y-3">
                {jobs.map((job) => (
                  <div
                    key={job.id}
                    className="p-4 bg-slate-50 border border-slate-200/60 rounded-xl space-y-3 relative overflow-hidden"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center space-x-2 min-w-0">
                        <div className="p-2 bg-white rounded-lg border border-[#e2e8f0] text-gray-500 shrink-0">
                          <FileText size={16} />
                        </div>
                        <div className="min-w-0">
                          <h5 className="text-xs font-semibold text-[#0f172a] truncate">{job.file.name}</h5>
                          <p className="text-[9px] text-gray-400 font-mono">
                            {(job.file.size / 1024 / 1024).toFixed(2)} MB
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {job.status === 'uploading' && (
                          <span className="text-[10px] font-bold font-mono text-[#1b5dfc]">{job.progress}%</span>
                        )}
                        {(job.status === 'success' || job.status === 'failed') && (
                          <button
                            onClick={() => dismissJob(job.id)}
                            className="p-0.5 text-gray-300 hover:text-gray-600 transition-colors cursor-pointer"
                            aria-label={`Dismiss ${job.file.name}`}
                          >
                            <X size={13} />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Progress Indicators */}
                    {job.status === 'uploading' && (
                      <div className="space-y-1">
                        <div className="w-full bg-[#e2e8f0] h-1.5 rounded-full overflow-hidden">
                          <div
                            className="bg-[#1b5dfc] h-full rounded-full transition-all duration-300"
                            style={{ width: `${job.progress}%` }}
                          />
                        </div>
                        <span className="text-[9px] text-gray-400 flex items-center space-x-1 font-mono">
                          <RefreshCw size={10} className="animate-spin text-blue-500" />
                          <span>Uploading to secure vault...</span>
                        </span>
                      </div>
                    )}

                    {job.status === 'extracting' && (
                      <div className="space-y-1">
                        <div className="w-full bg-blue-100 h-1.5 rounded-full overflow-hidden">
                          <div className="bg-[#1b5dfc] h-full rounded-full w-4/5 animate-pulse" />
                        </div>
                        <span className="text-[9px] text-amber-600 flex items-center space-x-1 font-mono">
                          <RefreshCw size={10} className="animate-spin" />
                          <span>Extracting line items...</span>
                        </span>
                      </div>
                    )}

                    {job.status === 'success' && (
                      <div className="space-y-2">
                        <div className="bg-green-50 border border-green-200/50 p-2 rounded-lg flex items-center space-x-2 text-[10px] text-green-700 font-mono">
                          <CheckCircle2 size={12} className="text-green-600" />
                          <span>{activeJobs.length > 0 ? 'Ready to review.' : 'Ready! Redirecting to editor...'}</span>
                        </div>
                        {/* Shown while other uploads are still running, since
                            the page will not navigate on its own then. */}
                        {activeJobs.length > 0 && job.runId && (
                          <button
                            onClick={() => navigate(`/review/${job.runId}`)}
                            className="w-full bg-white hover:bg-slate-50 text-[#1b5dfc] border border-blue-200 py-1.5 rounded-lg text-[10px] font-bold transition-colors cursor-pointer"
                          >
                            Review this invoice
                          </button>
                        )}
                      </div>
                    )}

                    {job.status === 'failed' && (
                      <div className="space-y-2">
                        <div className="bg-red-50 border border-red-200/50 p-2 rounded-lg flex items-start space-x-2 text-[10px] text-red-700">
                          <AlertTriangle size={12} className="text-red-600 shrink-0 mt-0.5" />
                          <div className="space-y-1">
                            <span className="font-semibold font-mono block">Extraction Failed</span>
                            <p className="text-[9px] text-gray-500 leading-normal">{job.error}</p>
                          </div>
                        </div>
                        <button
                          onClick={() => retryJob(job)}
                          className="w-full bg-[#1b5dfc] hover:bg-[#154ecb] text-white py-1.5 rounded-lg text-[10px] font-bold transition-colors cursor-pointer"
                        >
                          Retry Upload
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-gray-400 text-xs font-medium">
                No active uploads in queue.
              </div>
            )}
          </div>

          {/* Extraction Tips card */}
          <div className="bg-[#b45309] text-white p-5 rounded-2xl shadow-sm space-y-3 relative overflow-hidden">
            <div className="p-2 bg-white/10 rounded-lg w-fit">
              <Lightbulb size={16} />
            </div>
            <h4 className="text-xs font-bold uppercase tracking-wider">Extraction Tip</h4>
            <p className="text-[11px] text-amber-50 leading-relaxed font-medium">
              For best results, ensure the invoice is well-lit and all four corners are visible in the photo or scan. Batch numbers are automatically verified against manufacturer registries.
            </p>
          </div>
        </div>
      </div>

      {/* Full-size page preview, so the user can actually read the sheet
          before deciding whether it belongs to this invoice. */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-6 cursor-zoom-out"
          onClick={() => { setPreviewUrl(null); setPreviewFile(null); }}
        >
          {/* A quarter turn swaps width and height, so a rotated page sized
              against max-w/max-h would overflow the viewport on its new long
              axis. Constraining against the SWAPPED viewport dimension keeps
              the whole sheet on screen either way, which is the entire point
              of enlarging it. */}
          {/* A quarter turn swaps width and height, so a rotated page sized
              against max-w/max-h would overflow the viewport on its new long
              axis. Constraining against the SWAPPED viewport dimension keeps
              the whole sheet on screen either way, which is the entire point
              of enlarging it. */}
          <img
            src={previewUrl}
            alt="Invoice page preview"
            style={{
              transform: `rotate(${previewFile ? rotationOf(previewFile) : 0}deg)`,
              maxWidth: (previewFile ? rotationOf(previewFile) : 0) % 180 === 0 ? '100%' : '85vh',
              maxHeight: (previewFile ? rotationOf(previewFile) : 0) % 180 === 0 ? '100%' : '85vw',
            }}
            className="object-contain rounded-lg shadow-2xl transition-transform"
          />

          {/* Stops clicks on the controls from reaching the backdrop, which
              closes the lightbox. Rotating here writes through to the same
              per-page state the thumbnail reads, so the two never disagree. */}
          <div
            className="absolute top-4 right-4 flex items-center gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => previewFile && rotatePage(previewFile, -90)}
              className="p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors cursor-pointer"
              title="Rotate left"
              aria-label="Rotate preview left"
            >
              <RotateCcw size={18} />
            </button>
            <button
              onClick={() => previewFile && rotatePage(previewFile, 90)}
              className="p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors cursor-pointer"
              title="Rotate right"
              aria-label="Rotate preview right"
            >
              <RotateCw size={18} />
            </button>
            <button
              onClick={() => { setPreviewUrl(null); setPreviewFile(null); }}
              className="p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors cursor-pointer"
              title="Close preview"
            >
              <X size={20} />
            </button>
          </div>
        </div>
      )}

      {/* Single-order confirmation — asked before spending an extraction call
          per page, and before several pages are welded into one record. */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl border border-gray-200 p-6 max-w-md w-full shadow-xl space-y-4">
            <div className="flex items-start space-x-3">
              <div className="p-2 bg-indigo-50 text-indigo-600 rounded-xl shrink-0">
                <Layers size={22} />
              </div>
              <div className="space-y-1 min-w-0">
                <h3 className="text-base font-bold text-[#0f172a]">
                  Are these {pageFiles.length} pages all the same invoice?
                </h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  They'll be combined into a single invoice record, with the totals taken
                  from the page carrying the final amount. Pages from different orders must
                  be uploaded separately.
                </p>
              </div>
            </div>

            <div className="bg-slate-50 border border-slate-200/70 rounded-xl p-3 max-h-72 overflow-y-auto">
              <div className="flex gap-3 flex-wrap">
                {pageFiles.map((file, index) => (
                  <div key={`${file.name}-${index}`} className="space-y-1.5 w-[104px]">
                    <div className="relative rounded-lg overflow-hidden border border-slate-300 bg-white">
                      <img
                        src={pagePreviews[index]}
                        alt={`Page ${index + 1}`}
                        className="w-full h-32 object-cover object-top"
                      />
                      <span className="absolute top-1 left-1 w-5 h-5 rounded bg-indigo-600 text-white text-[9px] font-bold flex items-center justify-center shadow">
                        {index + 1}
                      </span>
                    </div>
                    <p className="text-[9px] text-slate-500 truncate" title={file.name}>{file.name}</p>
                  </div>
                ))}
              </div>
            </div>

            <p className="text-[10px] text-gray-400 leading-relaxed">
              Page order matters — page 1 should be the sheet carrying the invoice header.
            </p>

            <div className="flex items-center justify-end space-x-2 pt-1">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => submitPages(false)}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 transition-colors cursor-pointer"
              >
                Yes, combine into one invoice
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default UploadInvoicePage;
