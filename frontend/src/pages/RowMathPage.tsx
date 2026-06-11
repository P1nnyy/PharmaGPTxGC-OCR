import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { RowMathResult, RunSummary } from '../api/types';
import { CheckCircle, XCircle, AlertTriangle } from 'lucide-react';

export const RowMathPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [rowMath, setRowMath] = useState<RowMathResult[]>([]);
  const [selectedRowId, setSelectedRowId] = useState<number | null>(null);

  // Load row math validation logs
  useEffect(() => {
    const loadData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);

        const data = await apiClient.getRowMath(activeId);
        setRowMath(data);
        if (data.length > 0) {
          setSelectedRowId(data[0].row_id);
        }
      } catch (err) {
        console.error('Failed to load row math validation:', err);
      }
    };
    loadData();
  }, [runId, currentRunId]);

  const activeRow = rowMath.find(r => r.row_id === selectedRowId) || null;

  // Stats computation
  const passedCount = rowMath.filter(r => r.status === 'pass').length;
  const failedCount = rowMath.filter(r => r.status === 'fail').length;
  const unmeasurableCount = rowMath.filter(r => r.status === 'unmeasurable').length;

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Row Mathematical Reconciliation</h2>
        <p className="text-gray-400 text-sm">Validate line-item arithmetic parameters, audit tax calculation formulas, and isolate rounding discrepancies.</p>
      </div>

      {activeRun && (
        <>
          {/* Summary counters */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Rows Passed</span>
              <strong className="text-xl font-mono text-emerald-400">{passedCount} Rows</strong>
              <span className="text-[10px] text-gray-500 block">Strictly reconciled rows</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Rows Failed</span>
              <strong className={`text-xl font-mono ${failedCount > 0 ? 'text-rose-400' : 'text-gray-400'}`}>{failedCount} Rows</strong>
              <span className="text-[10px] text-gray-500 block">Arithmetic failures</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Unmeasurable</span>
              <strong className={`text-xl font-mono ${unmeasurableCount > 0 ? 'text-amber-400' : 'text-gray-400'}`}>{unmeasurableCount} Rows</strong>
              <span className="text-[10px] text-gray-500 block">Missing factors / OCR anomalies</span>
            </div>

            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-3.5 space-y-1 col-span-2 md:col-span-2">
              <span className="text-[10px] font-mono text-gray-500 uppercase block">Top Failure Reason</span>
              <strong className="text-xs font-sans text-white block truncate mt-1">
                {failedCount > 0
                  ? 'Line items amount mismatches Rate * Qty'
                  : (unmeasurableCount > 0 ? 'Unresolved Batch numbers / OCR artifacts' : 'All checks passed')}
              </strong>
              <span className="text-[10px] text-gray-500 block">Active reconciliation rule warning</span>
            </div>

          </div>

          {/* Table Split */}
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
            
            {/* Left 3 Columns: Math Results table */}
            <div className="xl:col-span-3 space-y-4">
              
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
                <div className="p-4 bg-[#0d1117] border-b border-[#30363d] text-xs font-mono text-gray-500 uppercase">
                  Line Items Arithmetic Logs
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="bg-[#0d1117] border-b border-[#30363d] text-gray-400 uppercase text-[9px]">
                      <tr>
                        <th className="py-2.5 px-4 w-10">Row</th>
                        <th className="py-2.5 px-4">Product Name</th>
                        <th className="py-2.5 px-4 text-right">Qty</th>
                        <th className="py-2.5 px-4 text-right">Rate</th>
                        <th className="py-2.5 px-4 text-right">Disc%</th>
                        <th className="py-2.5 px-4 text-right">GST</th>
                        <th className="py-2.5 px-4 text-right">Expected</th>
                        <th className="py-2.5 px-4 text-right">Actual</th>
                        <th className="py-2.5 px-4 text-right">Diff</th>
                        <th className="py-2.5 px-4 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#30363d]">
                      {rowMath.map(row => {
                        const isSelected = selectedRowId === row.row_id;
                        return (
                          <tr
                            key={row.row_id}
                            onClick={() => setSelectedRowId(row.row_id)}
                            className={`hover:bg-[#1f242c] cursor-pointer transition-colors ${
                              isSelected ? 'bg-[#1f242c]/70' : ''
                            }`}
                          >
                            <td className="py-2.5 px-4 text-gray-500">{row.row_id.toString().padStart(2, '0')}</td>
                            <td className="py-2.5 px-4 text-white font-sans font-medium truncate max-w-[150px]">
                              {row.product}
                            </td>
                            <td className="py-2.5 px-4 text-right text-gray-300">{row.qty}</td>
                            <td className="py-2.5 px-4 text-right text-gray-300">₹{row.rate.toFixed(2)}</td>
                            <td className="py-2.5 px-4 text-right text-gray-400">{row.discount}%</td>
                            <td className="py-2.5 px-4 text-right text-gray-400">{row.gst}%</td>
                            <td className="py-2.5 px-4 text-right text-gray-300">₹{row.expected_amount.toFixed(2)}</td>
                            <td className="py-2.5 px-4 text-right text-white font-semibold">₹{row.actual_amount.toFixed(2)}</td>
                            <td className={`py-2.5 px-4 text-right font-bold ${row.difference !== 0 ? 'text-rose-400' : 'text-gray-500'}`}>
                              ₹{row.difference.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-4 text-center">
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                row.status === 'pass'
                                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-900/30'
                                  : row.status === 'fail'
                                    ? 'bg-rose-950 text-rose-400 border border-rose-900/30'
                                    : 'bg-amber-950 text-amber-400 border border-amber-900/30'
                              }`}>
                                {row.status.toUpperCase()}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

              </div>

            </div>

            {/* Right 1 Column: Equation trace inspector */}
            <div className="xl:col-span-1">
              {activeRow ? (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs h-full flex flex-col justify-between">
                  <div className="space-y-4">
                    <div className="border-b border-[#30363d] pb-2">
                      <span className="text-[10px] text-gray-500 uppercase block">Arithmetic Trace</span>
                      <h4 className="text-white text-sm font-bold truncate">Row {activeRow.row_id.toString().padStart(2, '0')}</h4>
                      <span className="text-[10px] text-gray-400 font-sans block truncate">{activeRow.product}</span>
                    </div>

                    {/* Math parameters breakdown */}
                    <div className="space-y-2">
                      <span className="text-[10px] text-gray-500 uppercase block">Extracted Factors</span>
                      <div className="grid grid-cols-2 gap-2 bg-[#0d1117] border border-[#30363d] p-3 rounded">
                        <div>
                          <span className="text-gray-500 block text-[9px]">QUANTITY:</span>
                          <strong className="text-white font-bold">{activeRow.qty}</strong>
                        </div>
                        <div>
                          <span className="text-gray-500 block text-[9px]">UNIT RATE:</span>
                          <strong className="text-white font-bold">₹{activeRow.rate.toFixed(2)}</strong>
                        </div>
                        <div>
                          <span className="text-gray-500 block text-[9px]">DISCOUNT:</span>
                          <strong className="text-white font-bold">{activeRow.discount}%</strong>
                        </div>
                        <div>
                          <span className="text-gray-500 block text-[9px]">GST RATE:</span>
                          <strong className="text-white font-bold">{activeRow.gst}%</strong>
                        </div>
                      </div>
                    </div>

                    {/* Formula tracing */}
                    <div>
                      <span className="text-[10px] text-gray-500 uppercase block">Equation / Formula Used</span>
                      <div className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-[#00f0ff] font-bold text-center mt-1">
                        {activeRow.formula_used}
                      </div>
                    </div>

                    {/* Comparison audit */}
                    <div className="space-y-1.5 pt-2 border-t border-[#30363d]">
                      <span className="text-[10px] text-gray-500 uppercase block">Expected vs Actual</span>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Calculated Expected:</span>
                        <span className="text-white">₹{activeRow.expected_amount.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Extracted Invoiced:</span>
                        <span className="text-white font-bold">₹{activeRow.actual_amount.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between pt-1 border-t border-[#21262d] font-bold">
                        <span className="text-gray-400">Difference:</span>
                        <span className={activeRow.difference !== 0 ? 'text-rose-400' : 'text-emerald-400'}>
                          ₹{activeRow.difference.toFixed(2)}
                        </span>
                      </div>
                    </div>

                    {/* Verification check */}
                    <div className="border-t border-[#30363d] pt-3">
                      <span className="text-[10px] text-gray-500 uppercase block mb-1">Rounding Rules Check</span>
                      <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded font-sans text-gray-300 text-[11px] leading-relaxed flex items-start space-x-2">
                        {activeRow.status === 'pass' ? (
                          <>
                            <CheckCircle size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                            <span>Difference is 0.00. Arithmetic matches invoices within strict tolerance (0.01).</span>
                          </>
                        ) : activeRow.status === 'fail' ? (
                          <>
                            <XCircle size={14} className="text-rose-400 shrink-0 mt-0.5" />
                            <span>Difference exceeds maximum allowed rounding deviation. Flagged arithmetic mismatch!</span>
                          </>
                        ) : (
                          <>
                            <AlertTriangle size={14} className="text-amber-400 shrink-0 mt-0.5" />
                            <span>Unable to evaluate reconcile formulas due to unmapped OCR batch values.</span>
                          </>
                        )}
                      </div>
                    </div>

                  </div>

                  {/* Inspector footer info */}
                  <div className="text-[10px] text-gray-500 border-t border-[#30363d] pt-4">
                    Reconciliation Tolerance: <strong className="text-white">₹0.01</strong>
                  </div>

                </div>
              ) : (
                <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
                  No row selected.
                </div>
              )}
            </div>

          </div>
        </>
      )}

    </div>
  );
};
