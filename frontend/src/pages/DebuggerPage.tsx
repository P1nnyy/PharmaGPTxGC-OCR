import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient, getDetailsData, getInvoiceImageUrl, getProcessedInvoiceImageUrl, ENABLE_MOCK_DATA } from '../api/client';
import type { OCRBlock, CandidateTable, SelectedTable, RunSummary } from '../api/types';
import { normalizeBBox, mapBBoxToDisplaySpace, getRenderedImageMetrics } from '../utils/overlayGeometry';
import type { BBox } from '../utils/overlayGeometry';
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

  // Geometry tracking states
  const [runDetail, setRunDetail] = useState<any | null>(null);
  const [imageSize, setImageSize] = useState({ width: 800, height: 1000 });
  const [imageDisplayMode, setImageDisplayMode] = useState<'original' | 'ocr_corrected'>('ocr_corrected');
  const [showDebugCoords, setShowDebugCoords] = useState(false);
  const [, setMetricsTrigger] = useState(0);
  const imageRef = useRef<HTMLImageElement>(null);

  // Inspector Selection state
  const [selectedObject, setSelectedObject] = useState<{
    type: 'ocr_block' | 'table_cell' | 'candidate_table' | 'none';
    data: any;
  }>({ type: 'none', data: null });

  // UI state for modals & tooltips
  const [showAnomalyModal, setShowAnomalyModal] = useState(false);
  const [anomalyNote, setAnomalyNote] = useState('');

  const missingGeometryCount = ocrBlocks.filter(b => !b.bbox || b.bbox.length !== 4).length;
  const [showForceOCRModal, setShowForceOCRModal] = useState(false);
  const [actionLoading, setActionLoading] = useState<'idle' | 'ocr' | 'reconstruct'>('idle');
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [hoveredOverlay, setHoveredOverlay] = useState<{ id: string; text: string; confidence: number } | null>(null);

  const activeImageRunId = activeRun?.run_id || runId || currentRunId || '';
  const processedImageMeta = runDetail?.metadata?.processed_image || runDetail?.processed_image || null;
  const processedImageUrl = (activeImageRunId ? getProcessedInvoiceImageUrl(activeImageRunId) : null)
    || processedImageMeta?.processed_image_data_url
    || null;
  const processedImageAvailable = Boolean(
    processedImageUrl &&
    processedImageMeta?.coordinate_space === 'processed_image' &&
    typeof processedImageMeta?.processed_width === 'number' &&
    typeof processedImageMeta?.processed_height === 'number'
  );
  const activeImageMode = processedImageAvailable && imageDisplayMode === 'ocr_corrected'
    ? 'ocr_corrected'
    : 'original';
  const displayedImageUrl = activeRun
    ? (activeImageMode === 'ocr_corrected' && processedImageUrl
      ? processedImageUrl
      : getInvoiceImageUrl(activeRun.run_id, activeRun.filename))
    : '';
  const overlayCoordinateSpace = processedImageMeta?.coordinate_space || 'original_image';
  const showingOriginalWithProcessedOverlays = activeImageMode === 'original' && overlayCoordinateSpace === 'processed_image';

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

        const detail = getDetailsData(activeId);
        setRunDetail(detail);
      } catch (err) {
        console.error('Failed to load run details:', err);
      }
    };
    fetchRunData();
  }, [runId, currentRunId]);

  useEffect(() => {
    if (processedImageAvailable) {
      setImageDisplayMode('ocr_corrected');
    }
  }, [processedImageAvailable]);

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
      
      const detail = getDetailsData(currentRunId);
      setRunDetail(detail);
      
      showToast(force ? 'Forced OCR Re-recognition completed!' : 'OCR completed successfully!');
    } catch (err: any) {
      showToast(err.message || 'OCR execution failed.', 'error');
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
      
      const detail = getDetailsData(currentRunId);
      setRunDetail(detail);
      
      showToast('Layout Reconstruction pipeline completed!');
    } catch (err: any) {
      showToast(err.message || 'Reconstruction pipeline failed.', 'error');
    } finally {
      setActionLoading('idle');
    }
  };

  // Geometry computation helper functions
  const getOriginalSourceSize = () => {
    if (runDetail) {
      // 1. image_width / image_height
      if (typeof runDetail.image_width === 'number' && typeof runDetail.image_height === 'number') {
        return { width: runDetail.image_width, height: runDetail.image_height };
      }
      // 2. metadata.image_width / metadata.image_height
      if (runDetail.metadata && typeof runDetail.metadata.image_width === 'number' && typeof runDetail.metadata.image_height === 'number') {
        return { width: runDetail.metadata.image_width, height: runDetail.metadata.image_height };
      }
      // 3. source_image_dimensions (array or object)
      if (runDetail.source_image_dimensions) {
        const dims = runDetail.source_image_dimensions;
        if (Array.isArray(dims) && dims.length === 2 && typeof dims[0] === 'number' && typeof dims[1] === 'number') {
          return { width: dims[0], height: dims[1] };
        }
        if (typeof dims.width === 'number' && typeof dims.height === 'number') {
          return { width: dims.width, height: dims.height };
        }
      }
      // 4. image_validation.properties.width / height
      if (runDetail.image_validation && runDetail.image_validation.properties) {
        const props = runDetail.image_validation.properties;
        if (typeof props.width === 'number' && typeof props.height === 'number') {
          return { width: props.width, height: props.height };
        }
      }
    }
    // Fallback to imageElement.naturalWidth / naturalHeight
    if (imageRef.current && imageRef.current.naturalWidth && imageRef.current.naturalHeight) {
      return { width: imageRef.current.naturalWidth, height: imageRef.current.naturalHeight };
    }
    // Ultimate fallback
    return { width: imageSize.width, height: imageSize.height };
  };

  const getSourceSize = () => {
    if (
      activeImageMode === 'ocr_corrected' &&
      typeof processedImageMeta?.processed_width === 'number' &&
      typeof processedImageMeta?.processed_height === 'number'
    ) {
      return {
        width: processedImageMeta.processed_width,
        height: processedImageMeta.processed_height,
      };
    }
    return getOriginalSourceSize();
  };

  const sourceSize = getSourceSize();
  const baseWidth = 800;
  const aspectRatio = sourceSize.width > 0 ? sourceSize.height / sourceSize.width : 1.25;
  const baseHeight = baseWidth * aspectRatio;

  const metrics = getRenderedImageMetrics(imageRef.current, containerRef.current);

  const getDisplayMockBBox = (x: number, y: number, w: number, h: number): BBox => {
    const scaledBBox: BBox = [
      (x * sourceSize.width) / 800,
      (y * sourceSize.height) / 1000,
      ((x + w) * sourceSize.width) / 800,
      ((y + h) * sourceSize.height) / 1000
    ];
    return mapBBoxToDisplaySpace(scaledBBox, sourceSize, metrics);
  };

  const getDisplayBBox = (rawBbox: any): BBox | null => {
    const bbox = normalizeBBox(rawBbox);
    if (!bbox) return null;
    return mapBBoxToDisplaySpace(bbox, sourceSize, metrics);
  };

  const isDemoRun = ENABLE_MOCK_DATA && activeRun?.is_demo === true;

  const realRowBBoxes = !isDemoRun ? (() => {
    const bboxes: BBox[] = [];
    const rows = runDetail?.structured_tables?.[0]?.rows;
    if (Array.isArray(rows)) {
      for (const r of rows) {
        const bbox = normalizeBBox(r);
        if (bbox) bboxes.push(bbox);
      }
    }
    return bboxes;
  })() : [];

  const realColBoundariesX = !isDemoRun ? (() => {
    const xCoords = new Set<number>();
    const columns = runDetail?.structured_tables?.[0]?.columns;
    if (Array.isArray(columns)) {
      for (const col of columns) {
        const bbox = normalizeBBox(col);
        if (bbox) {
          xCoords.add(bbox[0]);
          xCoords.add(bbox[2]);
        }
      }
    }
    return Array.from(xCoords).sort((a, b) => a - b);
  })() : [];

  const hasRealSelectedTableGeometry = !!(selectedTable?.bbox);
  const hasRealCandidateTableGeometry = candidateTables.some(t => !!t.bbox);

  const showMissingGeometryWarning = !isDemoRun && (
    (settings.overlayRowBoxes && realRowBBoxes.length === 0) ||
    (settings.overlayColBoundaries && realColBoundariesX.length === 0) ||
    (settings.overlaySelectedTable && !hasRealSelectedTableGeometry) ||
    (settings.overlayCandidateTables && !hasRealCandidateTableGeometry)
  );

  // Overlay HUD counts
  const ocrBlocksTotal = ocrBlocks.length;
  const ocrBlocksDrawable = ocrBlocks.filter(b => !!getDisplayBBox(b.bbox || b.normalized_bbox)).length;
  const ocrBlocksMissing = ocrBlocksTotal - ocrBlocksDrawable;

  const candidateTablesTotal = candidateTables.length;
  const candidateTablesDrawable = candidateTables.filter(tbl => {
    if (tbl.bbox) return true;
    if (isDemoRun) return true;
    return false;
  }).length;
  const candidateTablesMissing = candidateTablesTotal - candidateTablesDrawable;

  const selectedTableGeometryPresent = !!(selectedTable && (selectedTable.bbox || isDemoRun));

  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (img.naturalWidth && img.naturalHeight) {
      setImageSize({ width: img.naturalWidth, height: img.naturalHeight });
    }
    setMetricsTrigger(prev => prev + 1);
  };

  useEffect(() => {
    const handleResize = () => setMetricsTrigger(prev => prev + 1);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

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
          
          <button
            onClick={() => setShowDebugCoords(prev => !prev)}
            className={`px-2.5 py-1 rounded text-[11px] font-medium border font-mono transition-all cursor-pointer ${
              showDebugCoords
                ? 'bg-[#1f242c] border-[#58a6ff] text-[#58a6ff] font-semibold'
                : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
            }`}
          >
            Debug Coords
          </button>

          {missingGeometryCount > 0 && (
            <span className="ml-3 px-2 py-0.5 rounded text-[10px] font-semibold font-mono bg-rose-950 text-rose-400 border border-rose-800 flex items-center space-x-1">
              <AlertTriangle size={11} />
              <span>{missingGeometryCount} OCR blocks missing geometry</span>
            </span>
          )}

          <div className="ml-3 flex items-center space-x-1 border-l border-[#30363d] pl-3">
            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold font-mono border ${
              activeImageMode === 'ocr_corrected'
                ? 'bg-emerald-950 text-emerald-400 border-emerald-800'
                : 'bg-[#0d1117] text-gray-400 border-[#30363d]'
            }`}>
              Viewing: {activeImageMode === 'ocr_corrected' ? 'OCR-corrected image' : 'Original upload'}
            </span>
            <button
              onClick={() => setImageDisplayMode('original')}
              className={`px-2 py-1 rounded text-[10px] font-medium border font-mono transition-all cursor-pointer ${
                activeImageMode === 'original'
                  ? 'bg-[#1f242c] border-[#58a6ff] text-[#58a6ff]'
                  : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
              }`}
            >
              Original
            </button>
            <button
              onClick={() => setImageDisplayMode('ocr_corrected')}
              disabled={!processedImageAvailable}
              className={`px-2 py-1 rounded text-[10px] font-medium border font-mono transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                activeImageMode === 'ocr_corrected'
                  ? 'bg-[#1f242c] border-[#58a6ff] text-[#58a6ff]'
                  : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
              }`}
            >
              OCR Corrected
            </button>
          </div>
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
              <>
                {/* 1. Zoomed / Panned Image Wrapper */}
                <div
                  style={{
                    transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`,
                    transformOrigin: 'center center',
                    transition: isPanning ? 'none' : 'transform 0.1s ease-out',
                    width: `${baseWidth}px`,
                    height: `${baseHeight}px`
                  }}
                  className="relative select-none"
                >
                  {/* SVG Rendered Invoice Image beneath */}
                  <img
                    ref={imageRef}
                    src={displayedImageUrl}
                    alt="Invoice Scanned Document"
                    className="w-full h-full pointer-events-none select-none"
                    draggable={false}
                    onLoad={handleImageLoad}
                  />
                </div>

                {/* 2. SVG OVERLAY RECTANGLES LAYER (Absolute over container, pointer-events-none) */}
                <svg
                  className="absolute inset-0 w-full h-full pointer-events-none z-10"
                >
                  
                  {/* Row Boxes overlay */}
                  {settings.overlayRowBoxes && (
                    <g opacity="0.15">
                      {isDemoRun ? (
                        <>
                          {(() => {
                            const [xMin, yMin, xMax, yMax] = getDisplayMockBBox(40, 255, 720, 40);
                            return <rect x={xMin} y={yMin} width={xMax - xMin} height={yMax - yMin} fill="#a855f7" stroke="#c084fc" strokeWidth="2" />;
                          })()}
                          {(() => {
                            const [xMin, yMin, xMax, yMax] = getDisplayMockBBox(40, 295, 720, 40);
                            return <rect x={xMin} y={yMin} width={xMax - xMin} height={yMax - yMin} fill="#a855f7" stroke="#c084fc" strokeWidth="2" />;
                          })()}
                          {(() => {
                            const [xMin, yMin, xMax, yMax] = getDisplayMockBBox(40, 335, 720, 40);
                            return <rect x={xMin} y={yMin} width={xMax - xMin} height={yMax - yMin} fill="#a855f7" stroke="#c084fc" strokeWidth="2" />;
                          })()}
                        </>
                      ) : (
                        realRowBBoxes.map((bbox, idx) => {
                          const displayBbox = mapBBoxToDisplaySpace(bbox, sourceSize, metrics);
                          const [xMin, yMin, xMax, yMax] = displayBbox;
                          return (
                            <rect
                              key={idx}
                              x={xMin}
                              y={yMin}
                              width={xMax - xMin}
                              height={yMax - yMin}
                              fill="#a855f7"
                              stroke="#c084fc"
                              strokeWidth="2"
                            />
                          );
                        })
                      )}
                    </g>
                  )}

                  {/* Column Boundaries overlay */}
                  {settings.overlayColBoundaries && (
                    <g opacity="0.45" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 3">
                      {isDemoRun ? (
                        [40, 80, 330, 430, 510, 560, 620, 680, 760].map((colX, idx) => {
                          const [xMin, yMin, , yMax] = getDisplayMockBBox(colX, 220, 0, 200);
                          return <line key={idx} x1={xMin} y1={yMin} x2={xMin} y2={yMax} />;
                        })
                      ) : (
                        realColBoundariesX.map((colX, idx) => {
                          const tableBBox = selectedTable?.bbox || (runDetail?.structured_tables?.[0] ? normalizeBBox(runDetail.structured_tables[0]) : null);
                          const yMin = tableBBox ? tableBBox[1] : 0;
                          const yMax = tableBBox ? tableBBox[3] : sourceSize.height;
                          
                          const [xMin, yMinDisplay, , yMaxDisplay] = mapBBoxToDisplaySpace([colX, yMin, colX, yMax], sourceSize, metrics);
                          return <line key={idx} x1={xMin} y1={yMinDisplay} x2={xMin} y2={yMaxDisplay} />;
                        })
                      )}
                    </g>
                  )}

                  {/* Selected Table outline */}
                  {settings.overlaySelectedTable && (() => {
                    if (isDemoRun) {
                      const [xMin, yMin, xMax, yMax] = getDisplayMockBBox(38, 218, 724, 204);
                      return (
                        <rect
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="none"
                          stroke="#00f0ff"
                          strokeWidth="2.5"
                          opacity="0.8"
                        />
                      );
                    } else if (selectedTable?.bbox) {
                      const [xMin, yMin, xMax, yMax] = mapBBoxToDisplaySpace(selectedTable.bbox, sourceSize, metrics);
                      return (
                        <rect
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="none"
                          stroke="#00f0ff"
                          strokeWidth="2.5"
                          opacity="0.8"
                        />
                      );
                    }
                    return null;
                  })()}

                  {/* Candidate Table outlines */}
                  {settings.overlayCandidateTables && candidateTables.map(tbl => {
                    if (tbl.bbox) {
                      const [xMin, yMin, xMax, yMax] = mapBBoxToDisplaySpace(tbl.bbox, sourceSize, metrics);
                      return (
                        <rect
                          key={tbl.table_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="none"
                          stroke={tbl.selected ? '#00f0ff' : '#f59e0b'}
                          strokeWidth="1.5"
                          opacity="0.65"
                          className="cursor-pointer pointer-events-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedObject({ type: 'candidate_table', data: tbl });
                          }}
                          onMouseEnter={() => setHoveredOverlay({ id: tbl.table_id, text: `TSR Candidate: ${tbl.source_engine} Grid (${tbl.rows}x${tbl.cols})`, confidence: tbl.score })}
                          onMouseLeave={() => setHoveredOverlay(null)}
                        />
                      );
                    } else if (isDemoRun) {
                      const tblX = tbl.table_id.includes('001') ? 36 : 320;
                      const tblY = tbl.table_id.includes('001') ? 216 : 50;
                      const tblW = tbl.table_id.includes('001') ? 728 : 440;
                      const tblH = tbl.table_id.includes('001') ? 208 : 100;
                      const [xMin, yMin, xMax, yMax] = getDisplayMockBBox(tblX, tblY, tblW, tblH);
                      return (
                        <rect
                          key={tbl.table_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="none"
                          stroke={tbl.selected ? '#00f0ff' : '#f59e0b'}
                          strokeWidth="1.5"
                          opacity="0.65"
                          className="cursor-pointer pointer-events-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedObject({ type: 'candidate_table', data: tbl });
                          }}
                          onMouseEnter={() => setHoveredOverlay({ id: tbl.table_id, text: `TSR Candidate: ${tbl.source_engine} Grid (${tbl.rows}x${tbl.cols})`, confidence: tbl.score })}
                          onMouseLeave={() => setHoveredOverlay(null)}
                        />
                      );
                    }
                    return null;
                  })}

                  {/* Raw OCR Blocks */}
                  {settings.overlayOCRBlocks && ocrBlocks
                    .filter(b => b.status !== 'orphan' && b.status !== 'low_confidence')
                    .map(b => {
                      const displayBbox = getDisplayBBox(b.bbox || b.normalized_bbox);
                      if (!displayBbox) return null;
                      const [xMin, yMin, xMax, yMax] = displayBbox;
                      return (
                        <rect
                          key={b.block_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="rgba(56, 139, 253, 0.05)"
                          stroke="#58a6ff"
                          strokeWidth="1"
                          opacity="0.75"
                          className="cursor-pointer hover:fill-blue-500/20 pointer-events-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedObject({ type: 'ocr_block', data: b });
                          }}
                          onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: b.text, confidence: b.confidence })}
                          onMouseLeave={() => setHoveredOverlay(null)}
                        />
                      );
                    })}

                  {/* Orphan Tokens highlight */}
                  {settings.overlayOrphans && ocrBlocks
                    .filter(b => b.status === 'orphan')
                    .map(b => {
                      const displayBbox = getDisplayBBox(b.bbox || b.normalized_bbox);
                      if (!displayBbox) return null;
                      const [xMin, yMin, xMax, yMax] = displayBbox;
                      return (
                        <rect
                          key={b.block_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="rgba(239, 68, 68, 0.08)"
                          stroke="#ef4444"
                          strokeWidth="1.5"
                          strokeDasharray="3 3"
                          className="cursor-pointer hover:fill-red-500/20 pointer-events-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedObject({ type: 'ocr_block', data: b });
                          }}
                          onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: `Orphan: ${b.text}`, confidence: b.confidence })}
                          onMouseLeave={() => setHoveredOverlay(null)}
                        />
                      );
                    })}

                  {/* Low Confidence Blocks highlight */}
                  {settings.overlayLowConfidence && ocrBlocks
                    .filter(b => b.status === 'low_confidence')
                    .map(b => {
                      const displayBbox = getDisplayBBox(b.bbox || b.normalized_bbox);
                      if (!displayBbox) return null;
                      const [xMin, yMin, xMax, yMax] = displayBbox;
                      return (
                        <rect
                          key={b.block_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
                          fill="rgba(245, 158, 11, 0.08)"
                          stroke="#f59e0b"
                          strokeWidth="1.5"
                          className="cursor-pointer hover:fill-amber-500/20 pointer-events-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedObject({ type: 'ocr_block', data: b });
                          }}
                          onMouseEnter={() => setHoveredOverlay({ id: b.block_id, text: `Low Conf: ${b.text}`, confidence: b.confidence })}
                          onMouseLeave={() => setHoveredOverlay(null)}
                        />
                      );
                    })}

                  {/* Selected Table Cells overlap (handles cell clicking) */}
                  {selectedTable && selectedTable.cells.map((rowCells) => 
                    rowCells.map(cell => {
                      const displayBbox = getDisplayBBox(cell.bbox || cell.normalized_bbox);
                      if (!displayBbox) return null;
                      const [xMin, yMin, xMax, yMax] = displayBbox;
                      return (
                        <rect
                          key={cell.cell_id}
                          x={xMin}
                          y={yMin}
                          width={xMax - xMin}
                          height={yMax - yMin}
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
                      );
                    })
                  )}

                </svg>

                {showingOriginalWithProcessedOverlays && (
                  <div className="absolute top-14 left-3 bg-[#0d1117]/95 border border-amber-800 rounded p-2.5 z-20 backdrop-blur-sm text-[10px] font-mono text-amber-300 max-w-sm shadow-lg flex items-start space-x-1.5 pointer-events-none">
                    <AlertTriangle size={12} className="text-amber-400 shrink-0 mt-0.5" />
                    <span>Overlay coordinates are based on OCR-corrected image; original image display may not align.</span>
                  </div>
                )}

                {/* 3. Debug Coordinates HUD Readout */}
                {showDebugCoords && (
                  <div className="absolute top-14 left-3 bg-[#0d1117]/90 border border-[#30363d] rounded p-2.5 z-20 backdrop-blur-sm text-[10px] font-mono text-gray-300 space-y-1 shadow-md pointer-events-none">
                    <div>source image: {sourceSize.width} x {sourceSize.height}</div>
                    <div>viewing: {activeImageMode === 'ocr_corrected' ? 'OCR-corrected' : 'original'}</div>
                    <div>rendered image: {Math.round(metrics.width)} x {Math.round(metrics.height)}</div>
                    <div>scaleX / scaleY: {metrics.scaleX.toFixed(3)} / {metrics.scaleY.toFixed(3)}</div>
                    <div>offsetX / offsetY: {Math.round(metrics.offsetLeft)} / {Math.round(metrics.offsetTop)}</div>
                    <div>zoom: {(zoom * 100).toFixed(0)}%</div>
                  </div>
                )}

                {/* 4. Overlay HUD Status Counts */}
                <div className="absolute top-3 right-3 bg-[#0d1117]/85 border border-[#30363d] rounded p-2 z-20 backdrop-blur-sm text-[10px] font-mono text-gray-300 space-y-0.5 shadow-md pointer-events-none">
                  <div className="text-gray-400 font-bold uppercase tracking-wider text-[8px] mb-1">Overlay Status</div>
                  <div>OCR Blocks: {ocrBlocksTotal} total / {ocrBlocksDrawable} drawable / {ocrBlocksMissing} missing</div>
                  <div>Candidate Tables: {candidateTablesTotal} total / {candidateTablesDrawable} drawable / {candidateTablesMissing} missing</div>
                  <div>Selected Table: <span className={selectedTableGeometryPresent ? 'text-emerald-400' : 'text-rose-400'}>{selectedTableGeometryPresent ? 'PRESENT' : 'MISSING'}</span></div>
                </div>

                {/* 5. Missing Geometry Warn HUD */}
                {showMissingGeometryWarning && (
                  <div className="absolute bottom-16 right-3 bg-[#0d1117]/95 border border-[#30363d] rounded p-2.5 z-20 backdrop-blur-sm text-[10px] font-mono text-amber-300 max-w-xs shadow-lg flex items-center space-x-1.5 pointer-events-none">
                    <AlertTriangle size={12} className="text-amber-400 shrink-0" />
                    <span>No real row/table geometry available for this overlay.</span>
                  </div>
                )}
              </>
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
                          <span className={`text-xs font-semibold ${!selectedObject.data.bbox ? 'text-rose-400' : 'text-gray-300'} capitalize`}>
                            {!selectedObject.data.bbox ? 'missing_geometry' : selectedObject.data.status}
                          </span>
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] text-gray-500 uppercase block">Geometry (BBox)</span>
                        <span className={`font-semibold text-[10px] block ${!selectedObject.data.bbox ? 'text-rose-400' : 'text-gray-400'}`}>
                          {!selectedObject.data.bbox ? 'missing' : `[${selectedObject.data.bbox.join(', ')}]`}
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
