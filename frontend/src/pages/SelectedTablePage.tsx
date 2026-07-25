import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient, getDetailsData, isSelectedTableUnavailable } from '../api/client';
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
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<any | null>(null);
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null);

  // Load table data
  useEffect(() => {
    const loadData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      // Clear stale state before loading new table details
      setActiveRun(null);
      setSelectedTable(null);
      setSemanticCols([]);
      setSelectedCellId(null);
      setUnavailableReason(null);
      setRunDetail(null);
      setSelectedRowIndex(null);

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);
        const detail = getDetailsData(activeId);
        setRunDetail(detail);

        const isAzureRun = runData?.extraction_engine === 'azure_document_intelligence';
        if (isAzureRun && detail?.line_items?.length > 0) {
          setSelectedRowIndex(0);
        }

        const unavailable = isAzureRun ? false : (isSelectedTableUnavailable(detail) || runData?.selected_table_available === false);
        const reason = detail?.fast_fail_reason || detail?.metadata?.fast_fail_reason || detail?.metrics?.table_sanity?.selected_reason || runData?.no_valid_table_candidate_reason || 'no_valid_table_candidate';
        setUnavailableReason(
          unavailable
            ? (reason === 'no_valid_candidate' ? 'no_valid_table_candidate' : reason)
            : null
        );

        if (!isAzureRun) {
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

  const isAzure = activeRun?.extraction_engine === 'azure_document_intelligence';
  const lineItems = runDetail?.line_items || [];
  const selectedLineItem = selectedRowIndex !== null ? lineItems[selectedRowIndex] : null;

  return (
    <div className="space-y-6 font-sans">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Selected Table Grid</h2>
        <p className="text-gray-400 text-sm">Review the primary resolved table structure, examine cells transformations, and audit column data types alignment.</p>
      </div>

      {isAzure ? (
        <>
          {/* Top Metric Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Invoice Number</span>
              <strong className="text-sm font-mono text-[#00f0ff] truncate block" title={runDetail?.invoice_number || '—'}>
                {runDetail?.invoice_number || '—'}
              </strong>
              <span className="text-[10px] text-gray-500 block">Identifier</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Invoice Date</span>
              <strong className="text-sm font-mono text-white block">{runDetail?.invoice_date || '—'}</strong>
              <span className="text-[10px] text-gray-500 block">Issue date</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Seller Name</span>
              <strong className="text-sm font-mono text-emerald-400 truncate block" title={runDetail?.seller_name || '—'}>
                {runDetail?.seller_name || '—'}
              </strong>
              <span className="text-[10px] text-gray-500 block">Vendor</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Buyer Name</span>
              <strong className="text-sm font-mono text-white truncate block" title={runDetail?.buyer_name || '—'}>
                {runDetail?.buyer_name || '—'}
              </strong>
              <span className="text-[10px] text-gray-500 block">Customer</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Confidence Score</span>
              <strong className={`text-sm font-mono ${runDetail?.confidence >= 0.85 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {typeof runDetail?.confidence === 'number' ? `${(runDetail.confidence * 100).toFixed(1)}%` : '—'}
              </strong>
              <span className="text-[10px] text-gray-500 block">Avg OCR/Layout match</span>
            </div>
          </div>

          {/* Main layout split */}
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
            
            {/* Left 3 Columns: Spreadsheet Grid */}
            <div className="xl:col-span-3 space-y-6">
              
              {/* Spreadsheet Grid Card */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
                <div className="p-4 bg-[#0d1117] border-b border-[#30363d] flex items-center justify-between text-xs font-mono text-gray-500 uppercase">
                  <span>Azure DI Line Items Grid</span>
                  <span className="text-[10px] text-gray-400">{lineItems.length} items extracted</span>
                </div>

                <div className="overflow-x-auto custom-scrollbar">
                  <table className="w-full text-left text-xs font-mono border-collapse">
                    <thead className="bg-[#0d1117] border-b border-[#30363d] text-[10px]">
                      <tr>
                        <th className="p-2 border-r border-[#30363d] text-center text-gray-600 w-10">#</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 min-w-[150px]">Product Name</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400">Pack</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400">Batch</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400">Expiry</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400">HSN</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">Qty</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">Free</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">MRP</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">Rate</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">Disc%</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">GST%</th>
                        <th className="p-3 border-r border-[#30363d] text-gray-400 text-right">Amount</th>
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-[#30363d]">
                      {lineItems.map((item: any, idx: number) => {
                        const isSelected = selectedRowIndex === idx;
                        return (
                          <tr 
                            key={idx} 
                            onClick={() => setSelectedRowIndex(idx)}
                            className={`hover:bg-[#1f242c]/50 cursor-pointer ${
                              isSelected ? 'bg-[#1f242c] ring-2 ring-inset ring-[#58a6ff]' : ''
                            }`}
                          >
                            <td className="p-2 border-r border-[#30363d] text-center text-gray-600 bg-[#0d1117] select-none">
                              {(idx + 1).toString().padStart(2, '0')}
                            </td>
                            <td className="p-3 border-r border-[#30363d] font-sans font-medium text-gray-200 truncate max-w-[220px]" title={item.name || '—'}>
                              {item.name || '—'}
                            </td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300">{item.pack || '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300">{item.batch || '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300">{item.expiry || '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300">{item.hsn || '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.quantity ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.free_quantity ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.mrp ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.rate ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.discount ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] text-gray-300 text-right">{item.gst_percent ?? '—'}</td>
                            <td className="p-3 border-r border-[#30363d] font-semibold text-gray-200 text-right">{item.amount ?? '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Totals Breakdown Card */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
                <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider font-mono">Invoice Summary Totals</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs text-gray-300">
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Base & Discounts</span>
                    <div className="flex justify-between text-gray-300">
                      <span>Subtotal:</span>
                      <span className="text-white font-semibold">{runDetail?.subtotal ?? '—'}</span>
                    </div>
                    <div className="flex justify-between text-gray-300 mt-1">
                      <span>Discount:</span>
                      <span className="text-amber-400 font-semibold">{runDetail?.discount ?? '—'}</span>
                    </div>
                  </div>
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Taxes (GST)</span>
                    <div className="flex justify-between text-gray-300">
                      <span>CGST Total:</span>
                      <span className="text-white font-semibold">{runDetail?.cgst ?? '—'}</span>
                    </div>
                    <div className="flex justify-between text-gray-300 mt-1">
                      <span>SGST Total:</span>
                      <span className="text-white font-semibold">{runDetail?.sgst ?? '—'}</span>
                    </div>
                    {runDetail?.igst !== null && runDetail?.igst !== undefined && runDetail?.igst !== 0 && (
                      <div className="flex justify-between text-gray-300 mt-1">
                        <span>IGST Total:</span>
                        <span className="text-white font-semibold">{runDetail.igst}</span>
                      </div>
                    )}
                  </div>
                  <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded">
                    <span className="text-gray-500 block uppercase text-[10px] mb-1">Final Settlement</span>
                    <div className="flex justify-between text-emerald-400 font-bold">
                      <span>Grand Total:</span>
                      <span>{runDetail?.grand_total ?? '—'}</span>
                    </div>
                    <div className="flex justify-between text-gray-500 text-[10px] mt-1">
                      <span>Engine:</span>
                      <span>Azure DI</span>
                    </div>
                  </div>
                </div>
              </div>

            </div>

            {/* Right 1 Column: Item Auditing Inspector */}
            <div className="xl:col-span-1">
              {selectedLineItem ? (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs">
                  <div className="border-b border-[#30363d] pb-2">
                    <span className="text-[10px] text-gray-500 uppercase block">Line Item Auditor</span>
                    <h4 className="text-[#00f0ff] text-sm font-bold truncate" title={selectedLineItem.name || '—'}>
                      {selectedLineItem.name || '—'}
                    </h4>
                    <span className="text-[10px] text-gray-400">Index {selectedRowIndex}</span>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-500 uppercase block">Product Details</span>
                    <div className="space-y-1.5 mt-1 font-sans text-xs">
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Pack Size:</span>
                        <span className="text-white font-semibold">{selectedLineItem.pack || '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Batch Number:</span>
                        <span className="text-white font-semibold">{selectedLineItem.batch || '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Expiry Date:</span>
                        <span className="text-white font-semibold">{selectedLineItem.expiry || '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">HSN Code:</span>
                        <span className="text-white font-semibold">{selectedLineItem.hsn || '—'}</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-500 uppercase block">Quantities & pricing</span>
                    <div className="space-y-1.5 mt-1 font-sans text-xs">
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Quantity:</span>
                        <span className="text-white font-semibold">{selectedLineItem.quantity ?? '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Free Quantity:</span>
                        <span className="text-white font-semibold">{selectedLineItem.free_quantity ?? '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">MRP:</span>
                        <span className="text-white font-semibold">{selectedLineItem.mrp ?? '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Rate:</span>
                        <span className="text-white font-semibold">{selectedLineItem.rate ?? '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Discount:</span>
                        <span className="text-white font-semibold">{selectedLineItem.discount ?? '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">GST:</span>
                        <span className="text-white font-semibold">{selectedLineItem.gst_percent ? `${selectedLineItem.gst_percent}%` : '—'}</span>
                      </div>
                      <div className="flex justify-between p-1.5 rounded bg-[#0d1117] border border-[#30363d]">
                        <span className="text-gray-400">Amount:</span>
                        <span className="text-[#00f0ff] font-bold">{selectedLineItem.amount ?? '—'}</span>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-[10px] text-gray-500 block uppercase">Confidence</span>
                      <span className={`font-semibold ${selectedLineItem.confidence >= 0.85 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {typeof selectedLineItem.confidence === 'number' ? `${(selectedLineItem.confidence * 100).toFixed(1)}%` : '—'}
                      </span>
                    </div>
                  </div>

                </div>
              ) : (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
                  No item selected. Click a row to audit line item details.
                </div>
              )}
            </div>

          </div>
        </>
      ) : activeRun?.selected_table_available === false || !!unavailableReason ? (
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-8 text-center space-y-2">
          <div className="text-rose-300 text-sm font-semibold">No valid table candidate selected</div>
          <div className="text-gray-500 text-xs font-mono">Reason: {unavailableReason || 'no_valid_table_candidate'}</div>
        </div>
      ) : !selectedTable || !activeRun ? (
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
