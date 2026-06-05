import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { Search, Upload, Filter, AlertTriangle, CheckCircle2, RefreshCw, ArrowRight, Layers } from 'lucide-react';

export const RunsPage: React.FC = () => {
  const {
    runs,
    currentRunId,
    setCurrentRunId,
    compareRunId,
    setCompareRunId,
    uploadInvoiceFile
  } = useRun();

  const navigate = useNavigate();

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'safe_for_erp' | 'needs_review' | 'failed'>('all');
  
  // File Upload State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<'idle' | 'uploading' | 'processing' | 'success' | 'failed'>('idle');
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Selected Row for Right Drawer Summary
  const [selectedRunId, setSelectedRunId] = useState<string | null>(currentRunId);

  const selectedRun = runs.find(r => r.run_id === selectedRunId) || runs[0] || null;

  // Handles File Input Selection
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
      setUploadProgress('idle');
      setUploadError(null);
    }
  };

  // Triggers Backend Upload
  const handleUploadSubmit = async () => {
    if (!selectedFile) return;
    setUploadProgress('uploading');
    setUploadError(null);
    try {
      // Simulate file upload phase
      await new Promise(resolve => setTimeout(resolve, 800));
      setUploadProgress('processing');
      // Execute upload client call
      const newRun = await uploadInvoiceFile(selectedFile);
      setUploadProgress('success');
      // Redirect to debugger on success
      setTimeout(() => {
        navigate(`/debugger/${newRun.run_id}`);
      }, 1000);
    } catch (err: any) {
      setUploadProgress('failed');
      setUploadError(err.message || 'Invoice processing failed. Please check image validity.');
    }
  };

  // Filtered list
  const filteredRuns = runs.filter(run => {
    const matchesSearch = run.filename.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          run.run_id.toLowerCase().includes(searchQuery.toLowerCase());
    
    const matchesStatus = statusFilter === 'all' || run.status === statusFilter;
    
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Pipeline Executions (Runs)</h2>
        <p className="text-gray-400 text-sm">Upload invoice images to execute the OCR / spatial reconstruction pipeline, and manage historical debug logs.</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        
        {/* Left 3 columns: Upload and Runs Table */}
        <div className="xl:col-span-3 space-y-6">
          
          {/* Upload Card */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
            <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider font-mono">Execute New Reconstruction Pipeline</h3>
            
            <div className="flex flex-col md:flex-row items-center gap-5">
              
              {/* File Dropzone */}
              <div className="flex-1 w-full border-2 border-dashed border-[#30363d] hover:border-[#58a6ff] rounded-lg p-6 flex flex-col items-center justify-center text-center cursor-pointer transition-colors relative">
                <input
                  type="file"
                  accept="image/*,application/pdf"
                  onChange={handleFileChange}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                />
                <Upload size={32} className="text-gray-500 mb-2" />
                <span className="text-sm text-gray-300 font-medium">
                  {selectedFile ? selectedFile.name : 'Select Invoice Image or PDF'}
                </span>
                <span className="text-xs text-gray-500 mt-1">Supports PNG, JPG, JPEG, and PDF up to 10MB</span>
              </div>

              {/* Upload CTA & Status */}
              <div className="w-full md:w-64 flex flex-col justify-between self-stretch">
                <div>
                  {uploadProgress === 'uploading' && (
                    <div className="flex items-center space-x-2 text-xs text-[#58a6ff] font-mono bg-[#1f242c] p-3 rounded border border-blue-900">
                      <RefreshCw size={14} className="animate-spin" />
                      <span>Uploading file to backend...</span>
                    </div>
                  )}

                  {uploadProgress === 'processing' && (
                    <div className="flex items-center space-x-2 text-xs text-amber-400 font-mono bg-amber-950/20 p-3 rounded border border-amber-900">
                      <RefreshCw size={14} className="animate-spin" />
                      <span>Reconstructing spatial cells...</span>
                    </div>
                  )}

                  {uploadProgress === 'success' && (
                    <div className="flex items-center space-x-2 text-xs text-emerald-400 font-mono bg-emerald-950/20 p-3 rounded border border-emerald-900">
                      <CheckCircle2 size={14} />
                      <span>Pipeline Completed! Redirecting...</span>
                    </div>
                  )}

                  {uploadProgress === 'failed' && (
                    <div className="flex flex-col space-y-1 text-xs text-rose-400 font-mono bg-rose-950/20 p-3 rounded border border-rose-900">
                      <div className="flex items-center space-x-1.5 font-bold">
                        <AlertTriangle size={14} />
                        <span>Execution Failed</span>
                      </div>
                      <span className="text-[10px] text-gray-400">{uploadError}</span>
                    </div>
                  )}

                  {uploadProgress === 'idle' && selectedFile && (
                    <div className="text-xs text-gray-400 font-mono bg-[#21262d] p-3 rounded border border-[#30363d]">
                      Ready to execute: <strong className="text-white">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</strong>
                    </div>
                  )}
                </div>

                <button
                  onClick={handleUploadSubmit}
                  disabled={!selectedFile || uploadProgress === 'uploading' || uploadProgress === 'processing'}
                  className="w-full mt-3 md:mt-0 bg-[#2ea44f] hover:bg-[#2c974b] disabled:bg-gray-800 disabled:text-gray-600 text-white font-medium py-2 rounded text-sm transition-colors cursor-pointer flex items-center justify-center space-x-1"
                >
                  <Upload size={16} />
                  <span>Run Pipeline</span>
                </button>
              </div>

            </div>
          </div>

          {/* Runs Table Card */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
            
            {/* Table Header toolbar */}
            <div className="p-4 border-b border-[#30363d] flex flex-col md:flex-row items-center justify-between gap-4">
              
              {/* Search */}
              <div className="relative w-full md:w-80">
                <Search size={16} className="absolute left-3 top-2.5 text-gray-500" />
                <input
                  type="text"
                  placeholder="Search by filename or Run ID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-[#0d1117] border border-[#30363d] rounded pl-9 pr-3 py-1.5 text-xs text-white placeholder-gray-500 font-mono focus:outline-none focus:border-[#58a6ff]"
                />
              </div>

              {/* Status Filter */}
              <div className="flex items-center space-x-2 w-full md:w-auto overflow-x-auto">
                <span className="text-xs text-gray-400 flex items-center space-x-1 shrink-0">
                  <Filter size={12} />
                  <span>Filter:</span>
                </span>
                
                {(['all', 'safe_for_erp', 'needs_review', 'failed'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setStatusFilter(f)}
                    className={`px-2.5 py-1 rounded text-xs font-medium border font-mono capitalize transition-colors shrink-0 cursor-pointer ${
                      statusFilter === f
                        ? 'bg-[#21262d] border-[#58a6ff] text-[#58a6ff]'
                        : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
                    }`}
                  >
                    {f === 'all' ? 'All' : f.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>

            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0d1117] border-b border-[#30363d] text-gray-400 uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Run ID</th>
                    <th className="py-3 px-4">Filename</th>
                    <th className="py-3 px-4">Timestamp</th>
                    <th className="py-3 px-4 text-center">Status</th>
                    <th className="py-3 px-4 text-right">Confidence</th>
                    <th className="py-3 px-4 text-right">Coverage</th>
                    <th className="py-3 px-4 text-right">TSR</th>
                    <th className="py-3 px-4 text-center">Row Math</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363d]">
                  {filteredRuns.length > 0 ? (
                    filteredRuns.map((run) => {
                      const isSelected = selectedRunId === run.run_id;
                      return (
                        <tr
                          key={run.run_id}
                          onClick={() => {
                            setSelectedRunId(run.run_id);
                            setCurrentRunId(run.run_id);
                          }}
                          className={`hover:bg-[#1f242c] cursor-pointer transition-colors ${
                            isSelected ? 'bg-[#1f242c]/75 border-l-2 border-[#58a6ff]' : ''
                          }`}
                        >
                          <td className="py-3 px-4 text-[#58a6ff] font-semibold">{run.run_id.substring(0, 15)}...</td>
                          <td className="py-3 px-4 text-white font-sans font-medium">{run.filename}</td>
                          <td className="py-3 px-4 text-gray-500">{new Date(run.timestamp).toLocaleString()}</td>
                          <td className="py-3 px-4 text-center">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              run.status === 'safe_for_erp'
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/40'
                                : run.status === 'needs_review'
                                  ? 'bg-amber-950 text-amber-400 border border-amber-800/40'
                                  : 'bg-rose-950 text-rose-400 border border-rose-800/40'
                            }`}>
                              {run.status === 'safe_for_erp' ? 'SAFE' : run.status === 'needs_review' ? 'REVIEW' : 'FAILED'}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right text-gray-300">{(run.confidence * 100).toFixed(1)}%</td>
                          <td className="py-3 px-4 text-right text-gray-300">{(run.token_coverage * 100).toFixed(1)}%</td>
                          <td className="py-3 px-4 text-right text-gray-300">{(run.representability_score * 100).toFixed(1)}%</td>
                          <td className="py-3 px-4 text-center">
                            <span className={`px-1.5 py-0.5 rounded text-[9px] ${
                              run.row_math_status === 'pass'
                                ? 'text-emerald-400 bg-emerald-950/20'
                                : run.row_math_status === 'fail'
                                  ? 'text-rose-400 bg-rose-950/20 font-bold'
                                  : 'text-gray-400 bg-gray-900'
                            }`}>
                              {run.row_math_status.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={8} className="text-center py-8 text-gray-500">
                        No pipeline runs matched search query or filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

          </div>
        </div>

        {/* Right 1 column: Selection Inspector Details */}
        <div className="xl:col-span-1">
          {selectedRun ? (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-5 h-full flex flex-col justify-between">
              <div className="space-y-4">
                <div className="border-b border-[#30363d] pb-3">
                  <span className="text-[10px] font-mono text-gray-500 uppercase">Run Inspector</span>
                  <h4 className="text-sm font-bold text-white font-mono truncate">{selectedRun.run_id}</h4>
                  <span className="text-xs text-gray-400 font-sans">{selectedRun.filename}</span>
                </div>

                {/* Score Dashboard */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-[#0d1117] p-2.5 rounded border border-[#30363d] text-center">
                    <span className="text-[10px] text-gray-500 block">OCR CONFIDENCE</span>
                    <strong className="text-sm font-mono text-white">{(selectedRun.confidence * 100).toFixed(1)}%</strong>
                  </div>
                  <div className="bg-[#0d1117] p-2.5 rounded border border-[#30363d] text-center">
                    <span className="text-[10px] text-gray-500 block">TSR REPRESENTABILITY</span>
                    <strong className="text-sm font-mono text-white">{(selectedRun.representability_score * 100).toFixed(1)}%</strong>
                  </div>
                  <div className="bg-[#0d1117] p-2.5 rounded border border-[#30363d] text-center col-span-2">
                    <span className="text-[10px] text-gray-500 block">TOKEN COVERAGE</span>
                    <strong className="text-sm font-mono text-white">{(selectedRun.token_coverage * 100).toFixed(1)}%</strong>
                  </div>
                </div>

                {/* Status card */}
                <div className={`p-3 rounded border text-xs ${
                  selectedRun.status === 'safe_for_erp'
                    ? 'bg-emerald-950/20 text-emerald-400 border-emerald-800'
                    : selectedRun.status === 'needs_review'
                      ? 'bg-amber-950/20 text-amber-400 border-amber-800'
                      : 'bg-rose-950/20 text-rose-400 border-rose-800'
                }`}>
                  <h5 className="font-bold mb-1">
                    {selectedRun.status === 'safe_for_erp'
                      ? '✓ ERP READY'
                      : selectedRun.status === 'needs_review'
                        ? '⚠ MANUAL RECONCILIATION REQUIRED'
                        : '❌ PIPELINE FAILURE'}
                  </h5>
                  <p className="text-[11px] text-gray-400 font-sans leading-relaxed">
                    {selectedRun.status === 'safe_for_erp'
                      ? 'All structural columns, cells, and values resolved with mathematical consistency.'
                      : selectedRun.status === 'needs_review'
                        ? `This run is flagged because of missing fields: [${selectedRun.missing_fields.join(', ')}].`
                        : 'OCR extraction failure: processing confidence score was below safety threshold.'}
                  </p>
                </div>

                {/* Additional metadata */}
                <div className="space-y-2 text-xs font-mono">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Selected Grid:</span>
                    <span className="text-gray-300">{selectedRun.selected_table_shape}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Table ID:</span>
                    <span className="text-[#58a6ff]">{selectedRun.selected_table_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Missing fields:</span>
                    <span className="text-gray-300">{selectedRun.missing_fields.join(', ') || 'None'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Timestamp:</span>
                    <span className="text-gray-400">{new Date(selectedRun.timestamp).toLocaleString()}</span>
                  </div>
                </div>

                {/* Diff Comparison Setup */}
                <div className="border-t border-[#30363d] pt-4 space-y-2">
                  <span className="text-[10px] font-mono text-gray-500 uppercase block">Diff Comparison Run</span>
                  <select
                    value={compareRunId || ''}
                    onChange={(e) => setCompareRunId(e.target.value || null)}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded text-xs p-1.5 text-white font-mono focus:outline-none"
                  >
                    <option value="">-- No comparison selected --</option>
                    {runs
                      .filter(r => r.run_id !== selectedRun.run_id)
                      .map(r => (
                        <option key={r.run_id} value={r.run_id}>
                          {r.filename} ({r.run_id.substring(4, 12)})
                        </option>
                      ))}
                  </select>
                  {compareRunId && (
                    <div className="flex items-center text-[10px] text-[#58a6ff] space-x-1">
                      <Layers size={10} />
                      <span>Diff Mode active against run {compareRunId.substring(4, 12)}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Action buttons */}
              <div className="space-y-2 pt-4 border-t border-[#30363d]">
                <button
                  onClick={() => {
                    setCurrentRunId(selectedRun.run_id);
                    navigate(`/debugger/${selectedRun.run_id}`);
                  }}
                  className="w-full bg-[#21262d] hover:bg-[#30363d] text-white font-medium py-2 rounded text-xs border border-[#30363d] transition-colors cursor-pointer flex items-center justify-center space-x-1.5"
                >
                  <span>Launch Visual Debugger</span>
                  <ArrowRight size={14} />
                </button>
              </div>

            </div>
          ) : (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
              No runs loaded. Upload an invoice to start.
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
