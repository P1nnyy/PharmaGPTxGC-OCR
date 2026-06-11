import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { SemanticColumn, SelectedTable } from '../api/types';
import { AlertTriangle, Shuffle } from 'lucide-react';

export const SemanticMappingPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [semanticCols, setSemanticCols] = useState<SemanticColumn[]>([]);
  const [selectedColId, setSelectedColId] = useState<number | null>(null);
  const [selectedTable, setSelectedTable] = useState<SelectedTable | null>(null);

  // Load semantic mapping data
  useEffect(() => {
    const loadData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const data = await apiClient.getSemanticMapping(activeId);
        setSemanticCols(data);
        if (data.length > 0) {
          setSelectedColId(data[0].col_id);
        }

        const table = await apiClient.getSelectedTable(activeId);
        setSelectedTable(table);
      } catch (err) {
        console.error('Failed to load semantic mapping data:', err);
      }
    };
    loadData();
  }, [runId, currentRunId]);

  const activeColumn = semanticCols.find(sc => sc.col_id === selectedColId) || null;

  // Missing required semantics checklist
  const requiredSemantics = ['product_name', 'quantity', 'unit_price', 'row_total', 'batch_no', 'expiry_date'];
  const mappedSemantics = semanticCols.map(sc => sc.predicted_type);

  if (semanticCols.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">Column Classifier &amp; Semantic Mapping</h2>
          <p className="text-gray-400 text-sm">Audit column taxonomy predictions, examine classifier confidence distributions, and review competing candidates.</p>
        </div>
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-8 text-center text-gray-400 text-sm">
          Backend response did not contain semantic column diagnostics.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Column Classifier &amp; Semantic Mapping</h2>
        <p className="text-gray-400 text-sm">Audit column taxonomy predictions, examine classifier confidence distributions, and review competing candidates.</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        
        {/* Left 3 columns: Columns list and previews */}
        <div className="xl:col-span-3 space-y-6">
          
          {/* Missing Required Columns Panel */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div className="flex items-start space-x-3">
              <div className="bg-amber-950 p-2 rounded text-amber-400">
                <AlertTriangle size={18} />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white font-sans">Required Indian Pharma Semantics Check</h4>
                <p className="text-xs text-gray-400">The pipeline requires core columns to execute down-stream tax and reconciliation checks.</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {requiredSemantics.map(rs => {
                const present = mappedSemantics.includes(rs);
                return (
                  <span
                    key={rs}
                    className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono border ${
                      present
                        ? 'bg-emerald-950/20 text-emerald-400 border-emerald-900/40'
                        : 'bg-rose-950/20 text-rose-400 border-rose-900/40 animate-pulse'
                    }`}
                  >
                    {present ? '✓' : '✖'} {rs.replace(/_/g, ' ').toUpperCase()}
                  </span>
                );
              })}
            </div>
          </div>

          {/* Column list grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {semanticCols.map(col => {
              const isSelected = selectedColId === col.col_id;
              return (
                <div
                  key={col.col_id}
                  onClick={() => setSelectedColId(col.col_id)}
                  className={`bg-[#161b22] border rounded-lg p-4 cursor-pointer transition-all space-y-3 ${
                    isSelected ? 'border-[#58a6ff] ring-1 ring-[#58a6ff]' : 'border-[#30363d] hover:border-gray-500'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-gray-500 uppercase">COL_{col.col_id}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold ${
                      col.confidence > 0.9
                        ? 'text-emerald-400 bg-emerald-950/25 border border-emerald-900/30'
                        : 'text-amber-400 bg-amber-950/25 border border-amber-900/30'
                    }`}>
                      {(col.confidence * 100).toFixed(0)}% Conf
                    </span>
                  </div>

                  <div>
                    <h4 className="text-white font-bold text-xs truncate uppercase font-mono">{col.header_text}</h4>
                    <span className="text-[11px] text-[#00f0ff] font-mono uppercase block mt-0.5">{col.predicted_type}</span>
                  </div>

                  {/* Sample Values snippet */}
                  <div className="bg-[#0d1117] border border-[#21262d] rounded p-2 text-[10px] font-mono text-gray-400 space-y-0.5">
                    <div className="text-gray-600 font-bold border-b border-[#21262d] pb-0.5 uppercase text-[8px]">Sample Values</div>
                    {(col.sample_values || []).slice(0, 3).map((v, i) => (
                      <div key={i} className="truncate">"{v}"</div>
                    ))}
                  </div>

                  {col.warnings && (
                    <div className="text-[10px] text-amber-400 flex items-center space-x-1 font-sans italic">
                      <AlertTriangle size={10} className="shrink-0" />
                      <span className="truncate">{col.warnings[0]}</span>
                    </div>
                  )}

                </div>
              );
            })}
          </div>

          {/* selected column values preview */}
          {activeColumn && selectedTable && (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
              <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider font-mono">
                Column values preview (COL_{activeColumn.col_id}: {activeColumn.header_text})
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {selectedTable.cells.slice(1).map((row, rIdx) => {
                  const cell = row[activeColumn.col_id];
                  if (!cell) return null;
                  return (
                    <div key={rIdx} className="bg-[#0d1117] border border-[#30363d] p-2 rounded text-center font-mono">
                      <span className="text-[9px] text-gray-500 block">Row {rIdx+1}</span>
                      <strong className="text-xs text-gray-200 block truncate mt-1">"{cell.text}"</strong>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

        </div>

        {/* Right 1 Column: Classifier Conflict Inspector */}
        <div className="xl:col-span-1">
          {activeColumn ? (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-5 font-mono text-xs h-full flex flex-col justify-between">
              <div className="space-y-4">
                <div className="border-b border-[#30363d] pb-2">
                  <span className="text-[10px] text-gray-500 uppercase block">Semantic Details</span>
                  <h4 className="text-white text-sm font-bold">COL_{activeColumn.col_id}</h4>
                  <span className="text-[10px] text-gray-400">{activeColumn.header_text}</span>
                </div>

                <div>
                  <span className="text-[10px] text-gray-500 uppercase block">Predicted Type</span>
                  <span className="text-sm font-bold text-[#00f0ff] uppercase block mt-0.5">{activeColumn.predicted_type}</span>
                </div>

                {/* Competing Candidates Bar chart */}
                <div className="space-y-2">
                  <span className="text-[10px] text-gray-500 uppercase block">Competing Candidates</span>
                  <div className="space-y-2">
                    {activeColumn.competing_candidates.map(cand => (
                      <div key={cand.type} className="space-y-0.5">
                        <div className="flex justify-between text-[10px]">
                          <span className="text-gray-300 font-semibold">{cand.type}</span>
                          <span className="text-gray-400">{(cand.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <div className="w-full bg-[#0d1117] h-1.5 rounded overflow-hidden">
                          <div
                            style={{ width: `${cand.confidence * 100}%` }}
                            className={`h-full ${cand.type === activeColumn.predicted_type ? 'bg-[#58a6ff]' : 'bg-gray-700'}`}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Conflict Resolution reasoning */}
                {activeColumn.conflict_resolution_reason && (
                  <div className="border-t border-[#30363d] pt-3">
                    <span className="text-[10px] text-gray-500 uppercase block mb-1">Conflict Resolver decision</span>
                    <div className="bg-[#0d1117] border border-[#30363d] p-3 rounded font-sans text-gray-300 text-[11px] leading-relaxed flex items-start space-x-2">
                      <Shuffle size={14} className="text-purple-400 shrink-0 mt-0.5" />
                      <span>{activeColumn.conflict_resolution_reason}</span>
                    </div>
                  </div>
                )}

                {/* Warnings list */}
                {activeColumn.warnings && (
                  <div className="bg-amber-950/20 p-2.5 rounded border border-amber-900/40 text-amber-400 text-[11px] font-sans space-y-1">
                    <span className="font-semibold block text-xs">Extraction Warnings:</span>
                    {activeColumn.warnings.map((w, i) => (
                      <div key={i} className="flex items-start space-x-1">
                        <span>•</span>
                        <span className="leading-tight">{w}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Classifier meta info */}
              <div className="border-t border-[#30363d] pt-4 text-[10px] text-gray-500 space-y-1">
                <div className="flex justify-between">
                  <span>Engine:</span>
                  <span>PharmaSemantic_V3</span>
                </div>
                <div className="flex justify-between">
                  <span>Heuristics mode:</span>
                  <span>Strict Header Rules</span>
                </div>
              </div>

            </div>
          ) : (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 text-center text-gray-500 text-xs">
              No column selected.
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
