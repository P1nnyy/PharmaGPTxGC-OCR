import React, { useState, useRef } from 'react';
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
  Trash2
} from 'lucide-react';

export const UploadInvoicePage: React.FC = () => {
  const { uploadInvoiceFile } = useRun();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // States
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'extracting' | 'success' | 'failed'>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

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

  // Main Upload and API call flow
  const processFile = async (file: File) => {
    setSelectedFile(file);
    setUploadStatus('uploading');
    setErrorMsg(null);
    setUploadProgress(15);

    // Simulate upload stages visually before final API call
    const progressTimer = setInterval(() => {
      setUploadProgress((prev) => {
        if (prev >= 65) {
          clearInterval(progressTimer);
          return 65;
        }
        return prev + 10;
      });
    }, 150);

    try {
      // Execute upload client call
      const newRun = await uploadInvoiceFile(file);
      
      clearInterval(progressTimer);
      setUploadProgress(100);
      setUploadStatus('success');

      // Short delay for visual verification checkmark
      setTimeout(() => {
        navigate(`/review/${newRun.run_id}`);
      }, 1000);
    } catch (err: any) {
      clearInterval(progressTimer);
      setUploadStatus('failed');
      setErrorMsg(err.message || 'Invoice processing failed. Please check image format validity.');
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
              {selectedFile && uploadStatus !== 'success' && uploadStatus !== 'failed' && (
                <span className="bg-blue-50 text-[#1b5dfc] text-[10px] px-2 py-0.5 rounded-full font-bold animate-pulse">
                  1 Active
                </span>
              )}
            </div>

            {selectedFile ? (
              <div className="space-y-3">
                <div className="p-4 bg-slate-50 border border-slate-200/60 rounded-xl space-y-3 relative overflow-hidden">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center space-x-2 min-w-0">
                      <div className="p-2 bg-white rounded-lg border border-[#e2e8f0] text-gray-500 shrink-0">
                        <FileText size={16} />
                      </div>
                      <div className="min-w-0">
                        <h5 className="text-xs font-semibold text-[#0f172a] truncate">{selectedFile.name}</h5>
                        <p className="text-[9px] text-gray-400 font-mono">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                      </div>
                    </div>
                    {uploadStatus === 'uploading' && (
                      <span className="text-[10px] font-bold font-mono text-[#1b5dfc]">{uploadProgress}%</span>
                    )}
                  </div>

                  {/* Progress Indicators */}
                  {uploadStatus === 'uploading' && (
                    <div className="space-y-1">
                      <div className="w-full bg-[#e2e8f0] h-1.5 rounded-full overflow-hidden">
                        <div 
                          className="bg-[#1b5dfc] h-full rounded-full transition-all duration-300"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                      <span className="text-[9px] text-gray-400 flex items-center space-x-1 font-mono">
                        <RefreshCw size={10} className="animate-spin text-blue-500" />
                        <span>Uploading to secure vault...</span>
                      </span>
                    </div>
                  )}

                  {uploadStatus === 'extracting' && (
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

                  {uploadStatus === 'success' && (
                    <div className="bg-green-50 border border-green-200/50 p-2 rounded-lg flex items-center space-x-2 text-[10px] text-green-700 font-mono">
                      <CheckCircle2 size={12} className="text-green-600" />
                      <span>Ready! Redirecting to editor...</span>
                    </div>
                  )}

                  {uploadStatus === 'failed' && (
                    <div className="space-y-2">
                      <div className="bg-red-50 border border-red-200/50 p-2 rounded-lg flex items-start space-x-2 text-[10px] text-red-700">
                        <AlertTriangle size={12} className="text-red-600 shrink-0 mt-0.5" />
                        <div className="space-y-1">
                          <span className="font-semibold font-mono block">Extraction Failed</span>
                          <p className="text-[9px] text-gray-500 leading-normal">{errorMsg}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => processFile(selectedFile)}
                        className="w-full bg-[#1b5dfc] hover:bg-[#154ecb] text-white py-1.5 rounded-lg text-[10px] font-bold transition-colors cursor-pointer"
                      >
                        Retry Upload
                      </button>
                    </div>
                  )}
                </div>
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
    </div>
  );
};

export default UploadInvoicePage;
