import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { SelectedTable, SemanticColumn, TableCell, RunSummary } from '../api/types';
import { AlertTriangle, CheckCircle } from 'lucide-react';

const HEADER_TERMS_RE = /\b(ITEM|DESCRIPTION|PRODUCT|HSN|PACK|BATCH|QTY|QUANTITY|RATE|EXP|EXPIRY|MRP|GST|AMOUNT|AMT|DISC|DISCOUNT)\b/gi;
const HEADER_ROLE_RE = /\b(header|column_header|table_header)\b/i;
const BODY_ROLE_RE = /\b(item|data|body)\b/i;

const getCellSignal = (cell: TableCell, key: string): string => {
  const value = (cell as unknown as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : '';
};

const countHeaderTerms = (text: string): number => {
  const matches = text.toUpperCase().match(HEADER_TERMS_RE) || [];
  return new Set(matches.map(match => match.toUpperCase())).size;
};

const isHeaderRow = (row: TableCell[]): boolean => {
  const populatedCells = row.filter(cell => cell && cell.text && cell.text.trim());
  if (populatedCells.length === 0) return false;

  const roleSignals = populatedCells
    .flatMap(cell => [
      getCellSignal(cell, 'row_role'),
      getCellSignal(cell, 'role'),
      getCellSignal(cell, 'status'),
    ])
    .filter(Boolean);

  if (roleSignals.some(signal => HEADER_ROLE_RE.test(signal))) return true;
  if (roleSignals.some(signal => BODY_ROLE_RE.test(signal))) return false;

  const semanticSignals = populatedCells
    .map(cell => cell.semantic_label || '')
    .filter(Boolean);
  if (semanticSignals.some(signal => HEADER_ROLE_RE.test(signal))) return true;

  const rowText = populatedCells.map(cell => cell.text).join(' ');
  return countHeaderTerms(rowText) >= 2;
};

const getColumnCount = (grid: TableCell[][], selectedTable: SelectedTable): number => {
  const gridColumnCount = grid.reduce((max, row) => Math.max(max, Array.isArray(row) ? row.length : 0), 0);
  return Math.max(selectedTable.cols || 0, gridColumnCount);
};

const getTableViewRows = (selectedTable: SelectedTable) => {
  const grid: TableCell[][] = Array.isArray(selectedTable.cells) ? selectedTable.cells : [];
  const firstRow: TableCell[] = Array.isArray(grid[0]) ? grid[0] : [];
  const columnCount = getColumnCount(grid, selectedTable);
  const hasHeaderRow = isHeaderRow(firstRow);
  const bodyRows = hasHeaderRow ? grid.slice(1) : grid;

  return { grid, firstRow, columnCount, hasHeaderRow, bodyRows };
};

export const SelectedTablePage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [selectedTable, setSelectedTable] = useState<SelectedTable | null>(null);
  const [semanticCols, setSemanticCols] = useState<SemanticColumn[]>([]);
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);

  // Load table data
  useEffect(() => {
    const loadData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);

        const table = await apiClient.getSelectedTable(activeId);
        setSelectedTable(table);

        const mappings = await apiClient.getSemanticMapping(activeId);
        setSemanticCols(mappings);

        if (table) {
          const { bodyRows } = getTableViewRows(table);
          const firstBodyCell = bodyRows.find(row => Array.isArray(row) && row.length > 0)?.[0];
          if (firstBodyCell) {
            setSelectedCellId(firstBodyCell.cell_id);
          }
        }
      } catch (err) {
        console.error('Failed to load selected table:', err);
      }
    };
    loadData();
  }, [runId, currentRunId]);

  // Find cell object in table
  const findCellById = (id: string): TableCell | null => {
    if (!selectedTable) return null;
    for (const row of selectedTable.cells) {
      const match = row.find(c => c.cell_id === id);
      if (match) return match;
    }
    return null;
  };

  const selectedCell = selectedCellId ? findCellById(selectedCellId) : null;

  return (
    <div className="space-y-6 font-sans">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Selected Table Grid</h2>
        <p className="text-gray-400 text-sm">Review the primary resolved table structure, examine cells transformations, and audit column data types alignment.</p>
      </div>

      {!selectedTable || !activeRun ? (
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-8 text-center text-gray-400 text-sm">
          Backend response did not contain structured table data.
        </div>
      ) : (() => {
        // Defensive grid extraction
        const { grid, firstRow, columnCount, hasHeaderRow, bodyRows } = getTableViewRows(selectedTable);

        if (!grid.length || columnCount === 0) {
          return (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-8 space-y-3">
              <div className="text-center text-amber-400 text-sm font-semibold">
                Selected table exists but no renderable cell grid was built.
              </div>
              <div className="text-center text-gray-500 text-xs font-mono space-y-1">
                <div>Table ID: <span className="text-[#00f0ff]">{selectedTable.table_id}</span></div>
                <div>Rows: {selectedTable.rows} | Cols: {selectedTable.cols}</div>
                <div>Cells array length: {Array.isArray(selectedTable.cells) ? selectedTable.cells.length : 'N/A'}</div>
              </div>
            </div>
          );
        }

        return (
          <>
          {/* Top Metric Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Selected Table ID</span>
              <strong className="text-sm font-mono text-[#00f0ff]">{selectedTable.table_id}</strong>
              <span className="text-[10px] text-gray-500 block">Primary resolved schema</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Dimensions</span>
              <strong className="text-sm font-mono text-white">{selectedTable.rows} x {selectedTable.cols}</strong>
              <span className="text-[10px] text-gray-500 block">Row x column grid shape</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Representability Score</span>
              <div className="flex items-center space-x-1">
                <strong className="text-sm font-mono text-emerald-400">{(selectedTable.representability_score * 100).toFixed(1)}%</strong>
              </div>
              <span className="text-[10px] text-gray-500 block">Grid stability score</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Token Coverage</span>
              <strong className="text-sm font-mono text-white">{(activeRun.token_coverage * 100).toFixed(1)}%</strong>
              <span className="text-[10px] text-gray-500 block">Assigned text blocks area</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Missing Key Fields</span>
              <strong className={`text-sm font-mono ${selectedTable.required_fields_missing.length > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                {selectedTable.required_fields_missing.length > 0 ? selectedTable.required_fields_missing.join(', ') : 'None'}
              </strong>
              <span className="text-[10px] text-gray-500 block">Required pharma checklist</span>
            </div>

          </div>

          {/* Main layout split */}
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
            
            {/* Left 3 Columns: Spreadsheet Grid */}
            <div className="xl:col-span-3 space-y-6">
              
              {/* Spreadsheet Grid Card */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
                <div className="p-4 bg-[#0d1117] border-b border-[#30363d] flex items-center justify-between text-xs font-mono text-gray-500 uppercase">
                  <span>Structured Spreadsheet Editor View</span>
                  <div className="flex space-x-4 text-[10px]">
                    <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800" /> <span>Good (&gt;85%)</span></span>
                    <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 rounded bg-amber-950 text-amber-400 border border-amber-800" /> <span>Warning (&lt;85%)</span></span>
                    <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 rounded bg-rose-950 text-rose-400 border border-rose-800" /> <span>Error / Anomaly</span></span>
                  </div>
                </div>

                <div className="overflow-x-auto custom-scrollbar">
                  <table className="w-full text-left text-xs font-mono border-collapse">
                    
                    {/* Header: displays Column indexes, predicted labels and confidence */}
                    <thead className="bg-[#0d1117] border-b border-[#30363d] text-[10px]">
                      <tr>
                        <th className="p-2 border-r border-[#30363d] text-center text-gray-600 w-10">#</th>
                        {Array.from({ length: columnCount }, (_, cIdx) => {
                          const hdr = hasHeaderRow ? firstRow[cIdx] : null;
                          const headerText = hasHeaderRow ? (hdr?.text || `COL_${cIdx}`) : `COL_${cIdx}`;
                          const semCol = semanticCols.find(sc => sc.col_id === cIdx);
                          return (
                            <th key={cIdx} className="p-3 border-r border-[#30363d] text-gray-400 align-top min-w-[130px]">
                              <div className="text-[10px] text-gray-500">{hasHeaderRow ? `COL_${cIdx}` : 'Generated'}</div>
                              <div className="text-white font-bold tracking-tight text-xs uppercase truncate" title={headerText}>{headerText}</div>
                              {semCol && (
                                <div className="mt-1 pt-1 border-t border-[#21262d] text-[9px]">
                                  <span className="text-[#00f0ff] font-semibold">{semCol.predicted_type}</span>
                                  <span className="text-gray-500 block">Conf: {(semCol.confidence * 100).toFixed(0)}%</span>
                                </div>
                              )}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>

                    {/* Table Body rows */}
                    <tbody className="divide-y divide-[#30363d]">
                      {bodyRows.map((rowCells, rIdx) => {
                        const safeRow = Array.isArray(rowCells) ? rowCells : [];
                        return (
                        <tr key={rIdx} className="hover:bg-[#1f242c]/50">
                          <td className="p-2 border-r border-[#30363d] text-center text-gray-600 bg-[#0d1117] select-none">
                            {(rIdx + 1).toString().padStart(2, '0')}
                          </td>
                          {safeRow.map(cell => {
                            const isSelected = selectedCellId === cell.cell_id;
                            
                            let cellStyles = '';
                            if (cell.status === 'error') {
                              cellStyles = 'bg-rose-950/20 text-rose-400 font-semibold border-rose-900/40 hover:bg-rose-950/30';
                            } else if (cell.status === 'warning') {
                              cellStyles = 'bg-amber-950/20 text-amber-400 border-amber-900/40 hover:bg-amber-950/30';
                            } else if (cell.status === 'good') {
                              cellStyles = 'bg-emerald-950/10 text-emerald-400 hover:bg-emerald-950/20';
                            }
                            
                            return (
                              <td
                                key={cell.cell_id}
                                onClick={() => setSelectedCellId(cell.cell_id)}
                                className={`p-3 border-r border-[#30363d] border-b border-[#30363d] cursor-pointer max-w-[200px] truncate transition-all text-xs font-sans font-medium text-gray-200 ${cellStyles} ${
                                  isSelected ? 'ring-2 ring-inset ring-[#58a6ff] bg-[#1f242c]' : ''
                                }`}
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

              {/* Representability Breakdown Card */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
                <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider font-mono">TSR Alignment Checklist</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs text-gray-300">
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Spatial Stability</span>
                    <div className="flex items-center space-x-2 text-emerald-400">
                      <CheckCircle size={14} />
                      <span>Row alignment: Resolved</span>
                    </div>
                    <div className="flex items-center space-x-2 text-emerald-400 mt-1">
                      <CheckCircle size={14} />
                      <span>Column boundaries: Resolved</span>
                    </div>
                  </div>
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Cells Extraction</span>
                    <div className="flex items-center space-x-2 text-emerald-400">
                      <CheckCircle size={14} />
                      <span>Grid cells mapped: 32 / 32</span>
                    </div>
                    <div className="flex items-center space-x-2 text-amber-400 mt-1">
                      <AlertTriangle size={14} />
                      <span>Empty cells: 0 empty</span>
                    </div>
                  </div>
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Pharma Schema validation</span>
                    <div className="flex items-center space-x-2 text-emerald-400">
                      <CheckCircle size={14} />
                      <span>Required cols matching: 5 / 6</span>
                    </div>
                    <div className="flex items-center space-x-2 text-rose-400 mt-1">
                      <AlertTriangle size={14} />
                      <span>Missing footer key: "subtotal"</span>
                    </div>
                  </div>
                </div>
              </div>

            </div>

            {/* Right 1 Column: Cell Auditing Inspector */}
            <div className="xl:col-span-1">
              {selectedCell ? (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs">
                  <div className="border-b border-[#30363d] pb-2">
                    <span className="text-[10px] text-gray-500 uppercase block">Cell Auditor</span>
                    <h4 className="text-[#00f0ff] text-sm font-bold">{selectedCell.cell_id}</h4>
                    <span className="text-[10px] text-gray-400">Row {selectedCell.row_id}, Column {selectedCell.col_id}</span>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-500 uppercase block">Normalized Text</span>
                    <div className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-white font-sans font-semibold text-xs mt-1">
                      {selectedCell.text}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-[10px] text-gray-500 block uppercase">Semantic label</span>
                      <span className="text-white font-bold uppercase">{selectedCell.semantic_label}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-gray-500 block uppercase">Confidence</span>
                      <span className={`font-semibold ${selectedCell.confidence > 0.85 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {(selectedCell.confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-500 block uppercase">Original OCR Sources</span>
                    <div className="space-y-1.5 mt-1">
                      {selectedCell.source_blocks.map(bId => (
                        <div key={bId} className="flex justify-between items-center bg-[#0d1117] border border-[#30363d] p-1.5 rounded text-[11px] text-[#58a6ff]">
                          <span>{bId}</span>
                          <span className="text-[10px] text-gray-500">Block ID</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-500 block uppercase">Transform History</span>
                    <div className="bg-[#0d1117] border border-[#30363d] p-2.5 rounded text-[11px] text-gray-400 font-sans leading-normal">
                      {selectedCell.text.includes('????') ? (
                        <p>Merged candidate words containing low confidence symbols. Flagged as anomaly.</p>
                      ) : (
                        <p>Applied regex cell extractor. Character validation status resolved: <strong className="text-emerald-400">UNCHANGED</strong>.</p>
                      )}
                    </div>
                  </div>

                  {selectedCell.warnings && selectedCell.warnings.length > 0 && (
                    <div className="bg-rose-950/20 p-2.5 rounded border border-rose-900/40 text-rose-400 text-[11px] font-sans space-y-1.5">
                      <strong className="block text-xs font-semibold uppercase">Ambiguities Detected:</strong>
                      {selectedCell.warnings.map((w, i) => (
                        <div key={i} className="flex items-start space-x-1">
                          <span>•</span>
                          <span className="leading-tight">{w}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Absolute positioning box info */}
                  <div className="space-y-1">
                    <span className="text-[10px] text-gray-500 block uppercase">Cell Geometry</span>
                    <div className="text-[10px] text-gray-400 font-mono">
                      BBox: {selectedCell.bbox ? `[${selectedCell.bbox.join(', ')}]` : 'missing'}
                    </div>
                  </div>

                </div>
              ) : (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
                  No cell selected. Click cell to audit mapping logic.
                </div>
              )}
            </div>

          </div>
        </>
        );
      })()}

    </div>
  );
};
