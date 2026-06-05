import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { OCRBlock, CandidateTable, SelectedTable, RunSummary } from '../api/types';
import { getInvoiceImageSvgUrl } from '../api/client';
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  Move,
  Eye,
  RefreshCw,
  FileCode,
  FileSpreadsheet,
  Folder,
  AlertTriangle,
  CheckCircle,
  HelpCircle,
  Flag,
  RotateCcw
} from 'lucide-react';

export const DebuggerPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const {
    currentRunId,
    setCurrentRunId,
    settings,
    updateSettings,
    triggerOCR,
    triggerReconstruction,
    flagAnomaly,
    anomalies
  } = useRun();

  // Active run details state
  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [ocrBlocks, setOcrBlocks] = useState<OCRBlock[]>([]);
  const [candidateTables, setCandidateTables] = useState<CandidateTable[]>([]);
  const [selectedTable, setSelectedTable] = useState<SelectedTable | null>(null);
  const [activeTab, setActiveTab] = useState<'runs' | 'details'>('details');

  // Zoom & Pan State
  const [zoom, setZoom] = useState(0.8);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Inspector Selection state
  const [selectedObject, setSelectedObject] = useState<{
    type: 'ocr_block' | 'table_cell' | 'candidate_table' | 'none';
    data: any;
  }>({ type: 'none', data: null });

  // UI state for modals & tooltips
  const [showAnomalyModal, setShowAnomalyModal] = useState(false);
  const [anomalyNote, setAnomalyNote] = useState('');
  const [showForceOCRModal, setShowForceOCRModal] = useState(false);
  const [actionLoading, setActionLoading] = useState<'idle' | 'ocr' | 'reconstruct'>('idle');
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [hoveredOverlay, setHoveredOverlay] = useState<{ id: string; text: string; confidence: number } | null>(null);

  // Load run details when active run ID changes
  useEffect(() => {
    const fetchRunData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);
        if (runId !== currentRunId) {
          setCurrentRunId(activeId);
        }

        const blocks = await apiClient.getOCRBlocks(activeId);
        setOcrBlocks(blocks);

        const candidates = await apiClient.getCandidateTables(activeId);
        setCandidateTables(candidates);

        const table = await apiClient.getSelectedTable(activeId);
        setSelectedTable(table);
      } catch (err) {
        console.error('Failed to load run details:', err);
      }
    };
    fetchRunData();
  }, [runId, currentRunId]);

  // Utility toast helper
  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 3000);
  };

  // Run OCR trigger
  const handleRunOCR = async (force = false) => {
    if (!currentRunId) return;
    setActionLoading('ocr');
    try {
      await triggerOCR();
      const updatedBlocks = await apiClient.getOCRBlocks(currentRunId);
      setOcrBlocks(updatedBlocks);
      const updatedTable = await apiClient.getSelectedTable(currentRunId);
      setSelectedTable(updatedTable);
      
      showToast(force ? 'Forced OCR Re-recognition completed!' : 'OCR completed successfully!');
    } catch (err) {
      showToast('OCR execution failed.', 'error');
    } finally {
      setActionLoading('idle');
      setShowForceOCRModal(false);
    }
  };

  // Re-run Reconstruction trigger
  const handleReconstruction = async () => {
    if (!currentRunId) return;
    setActionLoading('reconstruct');
    try {
      await triggerReconstruction();
      const candidates = await apiClient.getCandidateTables(currentRunId);
      setCandidateTables(candidates);
      const table = await apiClient.getSelectedTable(currentRunId);
      setSelectedTable(table);
      showToast('Layout Reconstruction pipeline completed!');
    } catch (err) {
      showToast('Reconstruction pipeline failed.', 'error');
    } finally {
      setActionLoading('idle');
    }
  };

  // Zoom helpers
  const handleZoomIn = () => setZoom(prev => Math.min(prev + 0.1, 2.0));
  const handleZoomOut = () => setZoom(prev => Math.max(prev - 0.1, 0.4));
  const handleResetZoom = () => {
    setZoom(0.85);
    setPan({ x: 0, y: 0 });
  };

  // Pan Mouse Handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    // Only pan if middle click or left click with spacebar/pan tool (using left click for ease here)
    if (e.button !== 0) return;
    setIsPanning(true);
    setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isPanning) return;
    setPan({
      x: e.clientX - panStart.x,
      y: e.clientY - panStart.y
    });
  };

  const handleMouseUp = () => {
    setIsPanning(false);
  };

  // Export handlers
  const handleExportJSON = () => {
    if (!currentRunId) return;
    apiClient.downloadArtifact(currentRunId, 'full_diagnostics.json');
  };

  const handleExportCSV = () => {
    if (!currentRunId) return;
    apiClient.downloadArtifact(currentRunId, 'selected_table.csv');
  };

  const handleFlagAnomalySubmit = () => {
    if (currentRunId && anomalyNote) {
      flagAnomaly(anomalyNote);
      setShowAnomalyModal(false);
      setAnomalyNote('');
      showToast('Run successfully flagged as OCR anomaly.');
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)] gap-4 select-none">
      
      {/* Toast Alert */}
      {toastMessage && (
        <div className={`fixed top-16 right-6 px-4 py-2.5 rounded text-xs font-semibold z-50 flex items-center space-x-2 border shadow-lg transition-all ${
          toastMessage.type === 'success'
            ? 'bg-emerald-950 text-emerald-400 border-emerald-800'
            : 'bg-rose-950 text-rose-400 border-rose-800'
        }`}>
          <span>{toastMessage.text}</span>
        </div>
      )}

      {/* Dynamic Sub-Toolbar */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3 flex flex-wrap items-center justify-between gap-3 shrink-0">
        
        {/* Visual Layer Toggles */}
        <div className="flex items-center space-x-1">
          <span className="text-[10px] text-gray-500 font-mono uppercase mr-2 flex items-center space-x-1">
            <Eye size={12} />
            <span>Overlays:</span>
          </span>

          {[
            { label: 'OCR Blocks', key: 'overlayOCRBlocks' },
            { label: 'Row Boxes', key: 'overlayRowBoxes' },
            { label: 'Column Lines', key: 'overlayColBoundaries' },
            { label: 'Selected Table', key: 'overlaySelectedTable' },
            { label: 'Candidates', key: 'overlayCandidateTables' },
            { label: 'Orphans', key: 'overlayOrphans' },
            { label: 'Low Conf', key: 'overlayLowConfidence' }
          ].map(tog => {
            const active = settings[tog.key as keyof typeof settings];
            return (
              <button
                key={tog.key}
                onClick={() => updateSettings({ [tog.key]: !active })}
                className={`px-2.5 py-1 rounded text-[11px] font-medium border font-mono transition-all cursor-pointer ${
                  active
                    ? 'bg-[#1f242c] border-[#58a6ff] text-[#58a6ff] font-semibold'
                    : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
                }`}
              >
                {tog.label}
              </button>
            );
          })}
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-2">
          
          <button
            onClick={() => handleRunOCR(false)}
            disabled={actionLoading !== 'idle'}
            className="bg-[#21262d] hover:bg-[#30363d] text-white px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 cursor-pointer disabled:opacity-40"
          >
            <RefreshCw size={12} className={actionLoading === 'ocr' ? 'animate-spin' : ''} />
            <span>{actionLoading === 'ocr' ? 'Running...' : 'Run OCR'}</span>
          </button>

          <button
            onClick={handleReconstruction}
            disabled={actionLoading !== 'idle'}
            className="bg-[#21262d] hover:bg-[#30363d] text-white px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 cursor-pointer disabled:opacity-40"
          >
            <RotateCcw size={12} className={actionLoading === 'reconstruct' ? 'animate-spin' : ''} />
            <span>{actionLoading === 'reconstruct' ? 'Reconstructing...' : 'Re-run TSR'}</span>
          </button>

          <button
            onClick={handleExportJSON}
            className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 cursor-pointer"
          >
            <FileCode size={12} />
            <span>JSON</span>
          </button>

          <button
            onClick={handleExportCSV}
            className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 cursor-pointer"
          >
            <FileSpreadsheet size={12} />
            <span>CSV</span>
          </button>

          <button
            onClick={() => navigate(`/artifacts/${currentRunId}`)}
            className="bg-[#21262d] hover:bg-[#30363d] text-[#58a6ff] px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 cursor-pointer"
          >
            <Folder size={12} />
            <span>Artifacts</span>
          </button>

        </div>

      </div>

      {/* Main split work area */}
      <div className="flex-1 flex gap-4 min-h-0 overflow-hidden">
        
        {/* Left pane: Image viewer workspace */}
        <div className="flex-1 bg-[#161b22] border border-[#30363d] rounded-lg flex flex-col overflow-hidden relative">
          
          {/* Zoom controls float */}
          <div className="absolute top-3 left-3 bg-[#0d1117]/85 border border-[#30363d] rounded p-1 flex items-center space-x-1 z-20 backdrop-blur-sm">
            <button onClick={handleZoomIn} className="p-1 text-gray-400 hover:text-white cursor-pointer" title="Zoom In">
              <ZoomIn size={14} />
            </button>
            <button onClick={handleZoomOut} className="p-1 text-gray-400 hover:text-white cursor-pointer" title="Zoom Out">
              <ZoomOut size={14} />
            </button>
            <button onClick={handleResetZoom} className="p-1 text-gray-400 hover:text-white cursor-pointer border-l border-[#30363d] pl-1.5 text-[10px] font-mono" title="Reset Zoom">
              <Maximize2 size={13} className="inline mr-1" />
              <span>{(zoom * 100).toFixed(0)}%</span>
            </button>
            <div className="border-l border-[#30363d] pl-1.5 flex items-center text-[10px] text-gray-500 font-mono space-x-1">
              <Move size={12} />
              <span>Drag to Pan</span>
            </div>
          </div>

          {/* Hover Tooltip Overlay */}
          {hoveredOverlay && (
            <div className="absolute bottom-3 left-3 bg-[#0d1117]/95 border border-[#30363d] rounded-lg p-2.5 z-20 backdrop-blur-sm max-w-sm text-xs font-mono shadow-2xl">
              <div className="text-gray-500 text-[9px] uppercase tracking-wider mb-0.5">Hover Inspector</div>
              <div className="text-white font-bold truncate mb-1">ID: {hoveredOverlay.id}</div>
              <div className="text-gray-300 font-sans leading-relaxed border-t border-[#30363d] pt-1">"{hoveredOverlay.text}"</div>
              <div className="mt-1 flex items-center justify-between text-[10px]">
                <span className="text-gray-500">Confidence Score:</span>
                <span className={`font-semibold ${hoveredOverlay.confidence > 0.85 ? 'text-emerald-400' : hoveredOverlay.confidence > 0.6 ? 'text-amber-400' : 'text-rose-400'}`}>
                  {(hoveredOverlay.confidence * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          )}

          {/* Interactive Workspace Area */}
          <div
            ref={containerRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            className={`flex-1 overflow-hidden relative flex items-center justify-center bg-[#0d1117] ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
          >
            {activeRun ? (
              <div
                style={{
                  transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`,
                  transformOrigin: 'center center',
                  transition: isPanning ? 'none' : 'transform 0.1s ease-out'
                }}
                className="relative w-[800px] h-[1000px] select-none"
              >
                {/* SVG Rendered Invoice Image beneath */}
                <img
                  src={getInvoiceImageSvgUrl(activeRun.filename)}
                  alt="Invoice Scanned Document"
                  className="w-full h-full pointer-events-none select-none"
                  draggable={false}
                />

                {/* SVG OVERLAY RECTANGLES LAYER */}
                <svg
                  width="800"
                  height="1000"
                  viewBox="0 0 800 1000"
                  className="absolute inset-0 w-full h-full pointer-events-auto"
                >
                  
                  {/* Row Boxes overlay */}
                  {settings.overlayRowBoxes && (
                    <g opacity="0.15">
                      <rect x="40" y="255" width="720" height="40" fill="#a855f7" stroke="#c084fc" strokeWidth="2" />
                      <rect x="40" y="295" width="720" height="40" fill="#a855f7" stroke="#c084fc" strokeWidth="2" />
                      <rect x="40" y="335" width="720" height="40" fill="#a855f7" stroke="#c084fc" strokeWidth="2" />
                    </g>
                  )}

                  {/* Column Boundaries overlay */}
                  {settings.overlayColBoundaries && (
                    <g opacity="0.45" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 3">
                      <line x1="40" y1="220" x2="40" y2="420" />
                      <line x1="80" y1="220" x2="80" y2="420" />
                      <line x1="330" y1="220" x2="330" y2="420" />
                      <line x1="430" y1="220" x2="430" y2="420" />
                      <line x1="510" y1="220" x2="510" y2="420" />
                      <line x1="560" y1="220" x2="560" y2="420" />
                      <line x1="620" y1="220" x2="620" y2="420" />
                      <line x1="680" y1="220" x2="680" y2="420" />
                      <line x1="760" y1="220" x2="760" y2="420" />
                    </g>
                  )}

                  {/* Selected Table outline */}
                  {settings.overlaySelectedTable && (
                    <rect
                      x="38"
                      y="218"
                      width="724"
                      height="204"
                      fill="none"
                      stroke="#00f0ff"
                      strokeWidth="2.5"
                      opacity="0.8"
                    />
                  )}

                  {/* Candidate Table outlines */}
                  {settings.overlayCandidateTables && candidateTables.map(tbl => (
                    <rect
                      key={tbl.table_id}
                      x={tbl.table_id.includes('001') ? 36 : 320}
                      y={tbl.table_id.includes('001') ? 216 : 50}
                      width={tbl.table_id.includes('001') ? 728 : 440}
                      height={tbl.table_id.includes('001') ? 208 : 100}
                      fill="none"
                      stroke={tbl.selected ? '#00f0ff' : '#f59e0b'}
                      strokeWidth="1.5"
                      opacity="0.65"
                      className="cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedObject({ type: 'candidate_table', data: tbl });
                      }}
                      onMouseEnter={() => setHoveredOverlay({ id: tbl.table_id, text: `TSR Candidate: ${tbl.source_engine} Grid (${tbl.rows}x${tbl.cols})`, confidence: tbl.score })}
                      onMouseLeave={() => setHoveredOverlay(null)}
                    />
                  ))}

                  {/* Raw OCR Blocks */}
                  {settings.overlayOCRBlocks && ocrBlocks
                    .filter(b => b.status !== 'orphan' && b.status !== 'low_confidence')
                    .map(b => (
                      <rect
                        key={b.block_id}
                        x={b.bbox[0]}
                        y={b.bbox[1]}
                        width={b.bbox[2] - b.bbox[0]}
                        height={b.bbox[3] - b.bbox[1]}
                        fill="rgba(56, 139, 253, 0.05)"
                        stroke="#58a6ff"
                        strokeWidth="1"
                        opacity="0.75"
                        className="cursor-pointer hover:fill-blue-500/20"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedObject({ type: 'ocr_block', data: b });
                        }}
                        onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: b.text, confidence: b.confidence })}
                        onMouseLeave={() => setHoveredOverlay(null)}
                      />
                    ))}

                  {/* Orphan Tokens highlight */}
                  {settings.overlayOrphans && ocrBlocks
                    .filter(b => b.status === 'orphan')
                    .map(b => (
                      <rect
                        key={b.block_id}
                        x={b.bbox[0]}
                        y={b.bbox[1]}
                        width={b.bbox[2] - b.bbox[0]}
                        height={b.bbox[3] - b.bbox[1]}
                        fill="rgba(239, 68, 68, 0.08)"
                        stroke="#ef4444"
                        strokeWidth="1.5"
                        strokeDasharray="3 3"
                        className="cursor-pointer hover:fill-red-500/20"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedObject({ type: 'ocr_block', data: b });
                        }}
                        onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: `Orphan: ${b.text}`, confidence: b.confidence })}
                        onMouseLeave={() => setHoveredOverlay(null)}
                      />
                    ))}

                  {/* Low Confidence Blocks highlight */}
                  {settings.overlayLowConfidence && ocrBlocks
                    .filter(b => b.status === 'low_confidence')
                    .map(b => (
                      <rect
                        key={b.block_id}
                        x={b.bbox[0]}
                        y={b.bbox[1]}
                        width={b.bbox[2] - b.bbox[0]}
                        height={b.bbox[3] - b.bbox[1]}
                        fill="rgba(245, 158, 11, 0.08)"
                        stroke="#f59e0b"
                        strokeWidth="1.5"
                        className="cursor-pointer hover:fill-amber-500/20"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedObject({ type: 'ocr_block', data: b });
                        }}
                        onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: `Low Conf: ${b.text}`, confidence: b.confidence })}
                        onMouseLeave={() => setHoveredOverlay(null)}
                      />
                    ))}

                  {/* Selected Table Cells overlap (handles cell clicking) */}
                  {selectedTable && selectedTable.cells.map((rowCells) => 
                    rowCells.map(cell => (
                      <rect
                        key={cell.cell_id}
                        x={cell.bbox[0]}
                        y={cell.bbox[1]}
                        width={cell.bbox[2] - cell.bbox[0]}
                        height={cell.bbox[3] - cell.bbox[1]}
                        fill="none"
                        stroke="transparent"
                        strokeWidth="1"
                        className="cursor-pointer pointer-events-auto"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedObject({ type: 'table_cell', data: cell });
                        }}
                        onMouseEnter={() => setHoveredOverlay({ id: cell.cell_id, text: `Cell (${cell.row_id}, ${cell.col_id}): ${cell.text}`, confidence: cell.confidence })}
                        onMouseLeave={() => setHoveredOverlay(null)}
                      />
                    ))
                  )}

                </svg>

              </div>
            ) : (
              <div className="text-gray-500 font-mono text-xs">Loading Invoice Viewer...</div>
            )}
          </div>
        </div>

        {/* Right pane: Inspector Panel */}
        <aside className="w-80 bg-[#161b22] border border-[#30363d] rounded-lg flex flex-col justify-between overflow-hidden shrink-0">
          
          {/* Inspector Header tabs */}
          <div>
            <div className="flex border-b border-[#30363d] text-xs font-mono">
              <button
                onClick={() => setActiveTab('details')}
                className={`flex-1 py-3 text-center border-r border-[#30363d] cursor-pointer transition-colors ${
                  activeTab === 'details' ? 'bg-[#1f242c] text-white font-bold border-b-2 border-b-[#58a6ff]' : 'text-gray-500 hover:text-white'
                }`}
              >
                Selected Object
              </button>
              <button
                onClick={() => setActiveTab('runs')}
                className={`flex-1 py-3 text-center cursor-pointer transition-colors ${
                  activeTab === 'runs' ? 'bg-[#1f242c] text-white font-bold border-b-2 border-b-[#58a6ff]' : 'text-gray-500 hover:text-white'
                }`}
              >
                Run Summary
              </button>
            </div>

            {/* Content for Tabs */}
            <div className="p-4 overflow-y-auto max-h-[calc(100vh-23rem)] space-y-4 custom-scrollbar">
              
              {activeTab === 'runs' && activeRun && (
                <div className="space-y-4 font-mono text-xs">
                  <div>
                    <span className="text-[10px] text-gray-500 block uppercase">RUN FILENAME</span>
                    <span className="text-white font-sans font-medium text-sm block truncate">{activeRun.filename}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-gray-500 block uppercase">RUN TIMESTAMP</span>
                    <span className="text-gray-300">{new Date(activeRun.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="border-t border-[#30363d] pt-3">
                    <span className="text-[10px] text-gray-500 block uppercase mb-1">PIPELINE STATUS</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      activeRun.status === 'safe_for_erp' ? 'bg-emerald-950 text-emerald-400' : 'bg-amber-950 text-amber-400'
                    }`}>
                      {activeRun.status.replace(/_/g, ' ').toUpperCase()}
                    </span>
                  </div>
                  <div className="border-t border-[#30363d] pt-3 space-y-1.5">
                    <span className="text-[10px] text-gray-500 block uppercase">MISSING REQUIRED FIELDS</span>
                    {activeRun.missing_fields.length > 0 ? (
                      activeRun.missing_fields.map(f => (
                        <div key={f} className="flex items-center space-x-1.5 text-rose-400">
                          <AlertTriangle size={12} />
                          <span>{f}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-emerald-400 flex items-center space-x-1.5">
                        <CheckCircle size={12} />
                        <span>All fields resolved</span>
                      </div>
                    )}
                  </div>

                  {anomalies[activeRun.run_id] && (
                    <div className="border-t border-[#30363d] pt-3 bg-red-950/20 p-2.5 rounded border border-red-900/40">
                      <span className="text-[10px] text-red-400 font-bold block uppercase mb-1">MARKED AS ANOMALY</span>
                      <p className="text-[11px] text-gray-400 font-sans font-normal italic">"{anomalies[activeRun.run_id]}"</p>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'details' && (
                <>
                  {/* Nothing selected state */}
                  {selectedObject.type === 'none' && (
                    <div className="text-center py-10 text-gray-500 text-xs font-sans space-y-2">
                      <HelpCircle size={32} className="mx-auto text-gray-600 stroke-[1.5]" />
                      <p>Click on any OCR bounding box, table cell, or candidate outline in the viewer to inspect layout properties.</p>
                    </div>
                  )}

                  {/* OCR Block selected */}
                  {selectedObject.type === 'ocr_block' && (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="border-b border-[#30363d] pb-2">
                        <span className="text-[10px] text-gray-500 uppercase font-bold block">Object: OCR Block</span>
                        <h4 className="text-white text-sm font-bold">{selectedObject.data.block_id}</h4>
                      </div>

                      <div>
                        <span className="text-[10px] text-gray-500 uppercase block">Extracted Text</span>
                        <div className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-white leading-relaxed select-text font-sans font-medium text-xs break-all mt-1">
                          "{selectedObject.data.text}"
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Confidence</span>
                          <strong className={`text-xs ${selectedObject.data.confidence > 0.85 ? 'text-emerald-400' : 'text-amber-400'}`}>
                            {(selectedObject.data.confidence * 100).toFixed(1)}%
                          </strong>
                        </div>
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Status</span>
                          <span className="text-gray-300 capitalize">{selectedObject.data.status}</span>
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] text-gray-500 uppercase block">Geometry (BBox)</span>
                        <span className="text-gray-400 font-semibold text-[10px] block">
                          [{selectedObject.data.bbox.join(', ')}]
                        </span>
                      </div>

                      {selectedObject.data.assigned_row_id !== undefined && (
                        <div className="border-t border-[#30363d] pt-2 space-y-1">
                          <span className="text-[10px] text-gray-500 uppercase block">Grid Assignment</span>
                          <div className="flex justify-between">
                            <span className="text-gray-400">Row: {selectedObject.data.assigned_row_id}</span>
                            <span className="text-gray-400">Col: {selectedObject.data.assigned_col_id}</span>
                          </div>
                          <div className="text-gray-500 text-[10px]">
                            Assigned Cell ID: <span className="text-[#00f0ff]">{selectedObject.data.assigned_cell_id}</span>
                          </div>
                        </div>
                      )}

                      {selectedObject.data.warnings && (
                        <div className="border-t border-rose-900/40 bg-rose-950/10 p-2 rounded border border-[#30363d] text-rose-400 text-[11px] font-sans space-y-1">
                          <strong className="block text-xs font-semibold">Warnings:</strong>
                          {selectedObject.data.warnings.map((w: string, i: number) => (
                            <div key={i} className="flex items-start space-x-1">
                              <span className="mt-0.5">•</span>
                              <span className="leading-tight">{w}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Table Cell selected */}
                  {selectedObject.type === 'table_cell' && (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="border-b border-[#30363d] pb-2">
                        <span className="text-[10px] text-gray-500 uppercase font-bold block">Object: Table Cell</span>
                        <h4 className="text-[#00f0ff] text-sm font-bold">{selectedObject.data.cell_id}</h4>
                        <span className="text-[10px] text-gray-400">Grid position: Row {selectedObject.data.row_id}, Col {selectedObject.data.col_id}</span>
                      </div>

                      <div>
                        <span className="text-[10px] text-gray-500 uppercase block">Resolved Value</span>
                        <div className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-white font-sans font-semibold text-xs mt-1">
                          {selectedObject.data.text}
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Semantic Label</span>
                          <span className="text-gray-300 font-semibold">{selectedObject.data.semantic_label}</span>
                        </div>
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Confidence</span>
                          <span className="text-emerald-400 font-semibold">{(selectedObject.data.confidence * 100).toFixed(1)}%</span>
                        </div>
                      </div>

                      <div className="border-t border-[#30363d] pt-2 space-y-1">
                        <span className="text-[10px] text-gray-500 uppercase block">Assignment Trace</span>
                        <p className="text-[10px] text-gray-400 leading-normal font-sans">
                          OCR Source Block <strong className="text-white">"{selectedObject.data.source_blocks[0] || 'N/A'}"</strong> ➔ Bound column boundaries ➔ cell validation normalization.
                        </p>
                      </div>

                      {selectedObject.data.warnings && selectedObject.data.warnings.length > 0 && (
                        <div className="border-t border-amber-900/40 bg-amber-950/10 p-2 rounded border border-[#30363d] text-amber-400 text-[11px] font-sans space-y-1">
                          <strong className="block text-xs font-semibold">Anomalies Detected:</strong>
                          {selectedObject.data.warnings.map((w: string, i: number) => (
                            <div key={i} className="flex items-start space-x-1">
                              <span className="mt-0.5">•</span>
                              <span className="leading-tight">{w}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Candidate Table selected */}
                  {selectedObject.type === 'candidate_table' && (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="border-b border-[#30363d] pb-2">
                        <span className="text-[10px] text-gray-500 uppercase font-bold block">Object: TSR Candidate</span>
                        <h4 className="text-amber-400 text-sm font-bold">{selectedObject.data.table_id}</h4>
                        <span className="text-[10px] text-gray-400">Engine: {selectedObject.data.source_engine}</span>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Dimensions</span>
                          <span className="text-white font-semibold">{selectedObject.data.rows} x {selectedObject.data.cols}</span>
                        </div>
                        <div>
                          <span className="text-[10px] text-gray-500 uppercase block">Score</span>
                          <span className="text-[#58a6ff] font-semibold">{selectedObject.data.score.toFixed(3)}</span>
                        </div>
                      </div>

                      <div className="space-y-1">
                        <span className="text-[10px] text-gray-500 uppercase block">Coverage</span>
                        <div className="text-gray-300">
                          X: {selectedObject.data.x_coverage}% | Y: {selectedObject.data.y_coverage}%
                        </div>
                      </div>

                      <div className="space-y-1">
                        <span className="text-[10px] text-gray-500 uppercase block">Selection Status</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          selectedObject.data.selected ? 'bg-emerald-950 text-emerald-400' : 'bg-rose-950 text-rose-400'
                        }`}>
                          {selectedObject.data.selected ? 'SELECTED PRIMARY' : 'REJECTED CANDIDATE'}
                        </span>
                      </div>

                      {selectedObject.data.rejection_reason && (
                        <div className="border-t border-[#30363d] pt-2">
                          <span className="text-[10px] text-gray-500 uppercase block">Rejection Reason</span>
                          <p className="text-[11px] text-rose-400 leading-normal font-sans pt-0.5">
                            "{selectedObject.data.rejection_reason}"
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

            </div>
          </div>

          {/* Inspector footer: Custom Debug Actions */}
          <div className="p-4 border-t border-[#30363d] bg-[#0d1117] space-y-2">
            <button
              onClick={() => setShowForceOCRModal(true)}
              className="w-full bg-[#161b22] hover:bg-[#21262d] text-gray-300 font-medium py-2 rounded text-xs border border-[#30363d] transition-colors cursor-pointer flex items-center justify-center space-x-1.5"
            >
              <RefreshCw size={12} />
              <span>Force Re-recognition</span>
            </button>

            <button
              onClick={() => setShowAnomalyModal(true)}
              className="w-full bg-rose-950/20 hover:bg-rose-950/40 text-rose-400 font-medium py-2 rounded text-xs border border-rose-900/50 transition-colors cursor-pointer flex items-center justify-center space-x-1.5"
            >
              <Flag size={12} />
              <span>Flag as Anomaly</span>
            </button>
          </div>

        </aside>

      </div>

      {/* Bottom selected table preview */}
      {selectedTable && (
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden shrink-0">
          <div className="bg-[#0d1117] px-4 py-2 border-b border-[#30363d] flex items-center justify-between text-xs font-mono">
            <div className="flex items-center space-x-2">
              <span className="text-gray-500 uppercase">Extracted Table:</span>
              <strong className="text-white">{selectedTable.table_id}</strong>
              <span className="text-gray-600">({selectedTable.rows} Rows x {selectedTable.cols} Columns)</span>
            </div>
            <div className="flex items-center space-x-4 text-[10px] text-gray-500">
              <div className="flex items-center space-x-1">
                <span className="w-2 h-2 rounded bg-emerald-500" />
                <span>Good</span>
              </div>
              <div className="flex items-center space-x-1">
                <span className="w-2 h-2 rounded bg-amber-500" />
                <span>Low Conf</span>
              </div>
              <div className="flex items-center space-x-1">
                <span className="w-2 h-2 rounded bg-rose-500" />
                <span>Anomaly/Error</span>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto max-h-32 custom-scrollbar">
            <table className="w-full text-left text-xs font-mono">
              <tbody className="divide-y divide-[#30363d]">
                {selectedTable.cells.map((rowCells, rIdx) => {
                  const isHeader = rIdx === 0;
                  return (
                    <tr key={rIdx} className={isHeader ? 'bg-[#0d1117]' : 'hover:bg-[#1f242c]'}>
                      <td className="p-1 px-3 border-r border-[#30363d] text-gray-500 text-[10px] text-center w-8 select-none">
                        {isHeader ? '#' : rIdx.toString().padStart(2, '0')}
                      </td>
                      {rowCells.map(cell => {
                        const isSelected = selectedObject.type === 'table_cell' && selectedObject.data.cell_id === cell.cell_id;
                        
                        let cellBg = '';
                        if (!isHeader) {
                          if (cell.status === 'error') cellBg = 'bg-rose-950/20 text-rose-400 font-semibold border-rose-900/60';
                          else if (cell.status === 'warning') cellBg = 'bg-amber-950/20 text-amber-400 border-amber-900/60';
                          else if (cell.status === 'good') cellBg = 'bg-emerald-950/10 text-emerald-400 border-emerald-900/20';
                        }
                        
                        return (
                          <td
                            key={cell.cell_id}
                            onClick={() => setSelectedObject({ type: 'table_cell', data: cell })}
                            className={`p-1 px-3 border-r border-[#30363d] cursor-pointer text-xs truncate max-w-[150px] transition-all select-none border-b border-[#30363d] ${cellBg} ${
                              isHeader ? 'text-gray-400 font-bold text-[10px] uppercase py-1.5' : 'text-gray-200'
                            } ${isSelected ? 'ring-1 ring-[#58a6ff] bg-[#1f242c]' : ''}`}
                          >
                            {cell.text}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Force OCR Confirmation Modal */}
      {showForceOCRModal && (
        <div className="fixed inset-0 bg-[#0b0f17]/80 flex items-center justify-center z-50 p-4">
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg max-w-sm w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center space-x-2 text-amber-500">
              <AlertTriangle size={20} />
              <h4 className="font-bold text-white">Confirm OCR Re-recognition</h4>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed font-sans">
              This will bypass the MD5 document cache, invoke the GPU Surya/PaddleOCR inference pipeline, and force a fresh evaluation of OCR tokens. This action takes up to 3 seconds.
            </p>
            <div className="flex justify-end space-x-2 pt-2 text-xs">
              <button
                onClick={() => setShowForceOCRModal(false)}
                className="bg-[#21262d] border border-[#30363d] hover:bg-[#30363d] px-3 py-1.5 rounded text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRunOCR(true)}
                className="bg-[#d29922] hover:bg-[#c68e17] text-[#0d1117] font-bold px-3 py-1.5 rounded cursor-pointer"
              >
                Execute Force
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Flag Anomaly Modal */}
      {showAnomalyModal && (
        <div className="fixed inset-0 bg-[#0b0f17]/80 flex items-center justify-center z-50 p-4">
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg max-w-sm w-full p-5 space-y-4 shadow-2xl font-mono text-xs">
            <div className="flex items-center space-x-2 text-rose-500">
              <Flag size={20} />
              <h4 className="font-bold text-white uppercase">Flag Run as Anomaly</h4>
            </div>
            <div className="space-y-1.5">
              <label className="text-gray-500 block">Anomaly Details/Issue Notes:</label>
              <textarea
                value={anomalyNote}
                onChange={(e) => setAnomalyNote(e.target.value)}
                placeholder="E.g., Column 6 rate parsing overlaps Exp date, or footer grand total has stamp occlusion."
                className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 text-white font-sans text-xs focus:outline-none focus:border-rose-500 h-24"
              />
            </div>
            <div className="flex justify-end space-x-2 pt-2">
              <button
                onClick={() => {
                  setShowAnomalyModal(false);
                  setAnomalyNote('');
                }}
                className="bg-[#21262d] border border-[#30363d] hover:bg-[#30363d] px-3 py-1.5 rounded text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleFlagAnomalySubmit}
                disabled={!anomalyNote}
                className="bg-rose-700 hover:bg-rose-800 disabled:opacity-40 text-white font-bold px-3 py-1.5 rounded cursor-pointer"
              >
                Save Anomaly Flag
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};
