import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { OCRBlock, RunSummary } from '../api/types';
import { Search, Filter, AlertTriangle, Hash, Calendar, Link as LinkIcon, Info } from 'lucide-react';
import { getInvoiceImageUrl } from '../api/client';

export const OcrTokensPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [tokens, setTokens] = useState<OCRBlock[]>([]);
  const [selectedTokenId, setSelectedTokenId] = useState<string | null>(null);

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<'all' | 'orphan' | 'low_confidence' | 'numeric' | 'date' | 'mapped'>('all');

  // Load active tokens
  useEffect(() => {
    const loadTokens = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);

        const blocks = await apiClient.getOCRBlocks(activeId);
        setTokens(blocks);
        if (blocks.length > 0) {
          setSelectedTokenId(blocks[0].block_id);
        }
      } catch (err) {
        console.error('Failed to load OCR tokens:', err);
      }
    };
    loadTokens();
  }, [runId, currentRunId]);

  const selectedToken = tokens.find(t => t.block_id === selectedTokenId) || null;

  // Filter Logic
  const filteredTokens = tokens.filter(tok => {
    // Search query
    const matchesSearch =
      tok.text.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tok.block_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (tok.assigned_cell_id && tok.assigned_cell_id.toLowerCase().includes(searchQuery.toLowerCase()));

    if (!matchesSearch) return false;

    // Category filters
    switch (activeFilter) {
      case 'orphan':
        return tok.status === 'orphan';
      case 'low_confidence':
        return tok.status === 'low_confidence' || tok.confidence < 0.65;
      case 'mapped':
        return tok.status === 'mapped';
      case 'numeric':
        return /^\d+(\.\d+)?%?$/.test(tok.text.replace(/[$,]/g, '').trim());
      case 'date':
        return /\d{2}\/\d{2}\/\d{4}/.test(tok.text) || /\d{2}-\d{2}-\d{4}/.test(tok.text);
      default:
        return true;
    }
  });

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Raw OCR Tokens &amp; BBoxes</h2>
        <p className="text-gray-400 text-sm">Inspect raw output blocks from the OCR engines, examine bounding boxes, and audit spatial grid assignments.</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        
        {/* Left 3 Columns: Tokens list and search */}
        <div className="xl:col-span-3 space-y-4">
          
          {/* Table Header Filter Toolbar */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 flex flex-col md:flex-row items-center justify-between gap-4">
            
            {/* Search */}
            <div className="relative w-full md:w-80">
              <Search size={16} className="absolute left-3 top-2.5 text-gray-500" />
              <input
                type="text"
                placeholder="Search by text, ID, or cell assignment..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded pl-9 pr-3 py-1.5 text-xs text-white placeholder-gray-500 font-mono focus:outline-none focus:border-[#58a6ff]"
              />
            </div>

            {/* Filter Buttons */}
            <div className="flex items-center space-x-1.5 w-full md:w-auto overflow-x-auto">
              <span className="text-xs text-gray-400 flex items-center space-x-1 shrink-0">
                <Filter size={12} />
                <span>Filter:</span>
              </span>

              {[
                { name: 'All', value: 'all', icon: null },
                { name: 'Orphans Only', value: 'orphan', icon: Info },
                { name: 'Low Confidence', value: 'low_confidence', icon: AlertTriangle },
                { name: 'Mapped Only', value: 'mapped', icon: LinkIcon },
                { name: 'Numeric', value: 'numeric', icon: Hash },
                { name: 'Dates', value: 'date', icon: Calendar }
              ].map(f => {
                const Icon = f.icon;
                return (
                  <button
                    key={f.value}
                    onClick={() => setActiveFilter(f.value as any)}
                    className={`px-2.5 py-1 rounded text-xs font-medium border font-mono transition-colors shrink-0 cursor-pointer flex items-center space-x-1.5 ${
                      activeFilter === f.value
                        ? 'bg-[#1f242c] border-[#58a6ff] text-[#58a6ff]'
                        : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:text-white'
                    }`}
                  >
                    {Icon && <Icon size={12} />}
                    <span>{f.name}</span>
                  </button>
                );
              })}
            </div>

          </div>

          {/* Tokens List Table */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
            <div className="overflow-x-auto max-h-[calc(100vh-22rem)] custom-scrollbar">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0d1117] border-b border-[#30363d] text-gray-400 uppercase text-[9px] sticky top-0 z-10">
                  <tr>
                    <th className="py-3 px-4">Block ID</th>
                    <th className="py-3 px-4">Raw Text</th>
                    <th className="py-3 px-4 text-right">Confidence</th>
                    <th className="py-3 px-4">Bounding Box (Bbox)</th>
                    <th className="py-3 px-4 text-center">Row</th>
                    <th className="py-3 px-4 text-center">Col</th>
                    <th className="py-3 px-4 text-center">Cell ID</th>
                    <th className="py-3 px-4 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363d]">
                  {filteredTokens.length > 0 ? (
                    filteredTokens.map((tok) => {
                      const isSelected = selectedTokenId === tok.block_id;
                      return (
                        <tr
                          key={tok.block_id}
                          onClick={() => setSelectedTokenId(tok.block_id)}
                          className={`hover:bg-[#1f242c] cursor-pointer transition-colors ${
                            isSelected ? 'bg-[#1f242c]/75 border-l-2 border-[#58a6ff]' : ''
                          }`}
                        >
                          <td className="py-2.5 px-4 text-[#58a6ff] font-bold">{tok.block_id}</td>
                          <td className="py-2.5 px-4 text-white max-w-[200px] truncate select-text">"{tok.text}"</td>
                          <td className={`py-2.5 px-4 text-right font-semibold ${
                            tok.confidence > 0.85
                              ? 'text-emerald-400'
                              : tok.confidence > 0.6
                                ? 'text-amber-400'
                                : 'text-rose-400'
                          }`}>
                            {(tok.confidence * 100).toFixed(1)}%
                          </td>
                          <td className="py-2.5 px-4 text-gray-500 text-[10px]">
                            {tok.bbox ? `[${tok.bbox.join(', ')}]` : 'missing'}
                          </td>
                          <td className="py-2.5 px-4 text-center text-gray-300">{tok.assigned_row_id !== undefined ? tok.assigned_row_id : '—'}</td>
                          <td className="py-2.5 px-4 text-center text-gray-300">{tok.assigned_col_id !== undefined ? tok.assigned_col_id : '—'}</td>
                          <td className="py-2.5 px-4 text-center text-[#00f0ff]">{tok.assigned_cell_id || '—'}</td>
                          <td className="py-2.5 px-4 text-center">
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold font-mono ${
                              tok.status === 'mapped'
                                ? 'bg-emerald-950/45 text-emerald-400 border border-emerald-900/20'
                                : tok.status === 'orphan'
                                  ? 'bg-rose-950/45 text-rose-400 border border-rose-900/20'
                                  : tok.status === 'missing_geometry'
                                    ? 'bg-rose-950/60 text-rose-400 border border-rose-800'
                                    : 'bg-amber-950/45 text-amber-400 border border-amber-900/20'
                            }`}>
                              {tok.status.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={8} className="text-center py-8 text-gray-500">
                        No OCR tokens matched filter rules.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right 1 Column: Token Details and Mini SVG Canvas */}
        <div className="xl:col-span-1">
          {selectedToken && activeRun ? (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs">
              <div className="border-b border-[#30363d] pb-2">
                <span className="text-[10px] text-gray-500 uppercase">OCR Block Details</span>
                <h4 className="text-white text-sm font-bold">{selectedToken.block_id}</h4>
              </div>

              <div>
                <span className="text-[10px] text-gray-500 uppercase block">Recognized String</span>
                <div className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-white font-sans font-medium text-xs break-all mt-1 select-text">
                  "{selectedToken.text}"
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-[10px] text-gray-500 block uppercase">Confidence</span>
                  <span className={`font-semibold ${selectedToken.confidence > 0.85 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {(selectedToken.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-gray-500 block uppercase">Status</span>
                  <span className="text-gray-300 capitalize">{selectedToken.status}</span>
                </div>
              </div>

              <div>
                <span className="text-[10px] text-gray-500 block uppercase">Absolute BBox</span>
                <span className="text-gray-400">
                  {selectedToken.bbox ? `[${selectedToken.bbox.join(', ')}]` : 'missing'}
                </span>
              </div>

              <div className="border-t border-[#30363d] pt-3">
                <span className="text-[10px] text-gray-500 block uppercase mb-1">Spatial Layout Mapping</span>
                <div className="bg-[#0d1117] rounded border border-[#30363d] p-3 text-[11px] font-sans text-gray-400 leading-normal space-y-1">
                  {selectedToken.status === 'mapped' ? (
                    <>
                      <p>✓ This block is assigned to cell <strong className="text-[#00f0ff] font-mono">{selectedToken.assigned_cell_id}</strong> inside the Selected Table grid.</p>
                      <p className="text-[10px] text-gray-500 mt-1">Grid coordinates: Row {selectedToken.assigned_row_id}, Column {selectedToken.assigned_col_id}.</p>
                    </>
                  ) : (
                    <>
                      <p className="text-rose-400 font-semibold">⚠ ORPHAN / UNMAPPED BLOCK</p>
                      <p className="text-[10px]">
                        The coordinates of this token fell outside the primary column boundaries or structure grids selected by the TSR heuristics resolver.
                      </p>
                    </>
                  )}
                </div>
              </div>

              {/* Warnings */}
              {selectedToken.warnings && (
                <div className="bg-rose-950/20 p-2.5 rounded border border-rose-900/40 text-rose-400 text-[11px] font-sans space-y-1">
                  <span className="font-semibold block text-xs">Diagnostic Warnings:</span>
                  {selectedToken.warnings.map((w, i) => (
                    <div key={i} className="flex items-start space-x-1">
                      <span>•</span>
                      <span className="leading-tight">{w}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Mini visual overlay preview */}
              <div className="border-t border-[#30363d] pt-3">
                <span className="text-[10px] text-gray-500 block uppercase mb-2">Location on Document</span>
                <div className="bg-[#0d1117] border border-[#30363d] rounded h-40 relative overflow-hidden flex items-center justify-center">
                  
                  {/* Styled Document preview box */}
                  <div className="w-[300px] h-[375px] relative shrink-0" style={{ transform: 'scale(0.38)', transformOrigin: 'center center' }}>
                    <img
                      src={getInvoiceImageUrl(activeRun.run_id, activeRun.filename)}
                      alt="Mini Invoice View"
                      className="absolute inset-0 w-full h-full pointer-events-none"
                    />
                    
                    {/* SVG boundary highlight box */}
                    {selectedToken.bbox && (
                      <svg className="absolute inset-0 w-full h-full">
                        <rect
                          x={selectedToken.bbox[0]}
                          y={selectedToken.bbox[1]}
                          width={selectedToken.bbox[2] - selectedToken.bbox[0]}
                          height={selectedToken.bbox[3] - selectedToken.bbox[1]}
                          fill="rgba(0, 240, 255, 0.25)"
                          stroke="#00f0ff"
                          strokeWidth="4"
                        />
                      </svg>
                    )}
                  </div>

                </div>
              </div>

            </div>
          ) : (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
              No token selected.
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
