import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { CandidateTable, RunSummary } from '../api/types';
import { CheckCircle, Info } from 'lucide-react';

export const CandidateTablesPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const {
    currentRunId,
    compareRunId
  } = useRun();

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [compareRun, setCompareRun] = useState<RunSummary | null>(null);
  const [candidates, setCandidates] = useState<CandidateTable[]>([]);
  const [compareCandidates, setCompareCandidates] = useState<CandidateTable[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);

  // Fetch run and candidate tables
  useEffect(() => {
    const loadData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);

        const data = await apiClient.getCandidateTables(activeId);
        setCandidates(data);
        if (data.length > 0) {
          const selected = data.find(c => c.selected);
          setSelectedCandidateId(selected ? selected.table_id : data[0].table_id);
        }

        if (compareRunId) {
          const compData = await apiClient.getRun(compareRunId);
          setCompareRun(compData);

          const compCands = await apiClient.getCandidateTables(compareRunId);
          setCompareCandidates(compCands);
        } else {
          setCompareRun(null);
          setCompareCandidates([]);
        }
      } catch (err) {
        console.error('Failed to load candidate tables data:', err);
      }
    };
    loadData();
  }, [runId, currentRunId, compareRunId]);

  const activeCandidate = candidates.find(c => c.table_id === selectedCandidateId) || null;

  // Compute structure score (average score of candidates)
  const getStructureScore = (cands: CandidateTable[]) => {
    if (cands.length === 0) return 0;
    const selected = cands.find(c => c.selected);
    return selected ? selected.representability_score : cands[0].representability_score;
  };

  const primaryScore = getStructureScore(candidates);
  const compScore = getStructureScore(compareCandidates);
  const scoreDiff = compScore ? primaryScore - compScore : 0;

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">TSR &amp; Candidate Tables</h2>
        <p className="text-gray-400 text-sm">Audit Table Structure Recognition (TSR) engines, inspect heuristics, and trace candidate rejection reasons.</p>
      </div>

      {/* TSR ENGINE DIFF METRICS */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        
        {/* Structure Score */}
        <div className="space-y-1">
          <span className="text-[10px] font-mono text-gray-500 uppercase block">TSR Score</span>
          <div className="flex items-baseline space-x-2">
            <strong className="text-2xl font-bold font-mono text-white">
              {primaryScore.toFixed(3)}
            </strong>
            {compareRun && (
              <span className={`text-xs font-mono font-semibold ${scoreDiff >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {scoreDiff >= 0 ? '+' : ''}{(scoreDiff * 100).toFixed(1)}%
              </span>
            )}
          </div>
          <span className="text-[10px] text-gray-500 block font-sans">Primary engine alignment score</span>
        </div>

        {/* Before grid size (baseline / compare run) */}
        <div className="space-y-1">
          <span className="text-[10px] font-mono text-gray-500 uppercase block">Baseline Grid</span>
          <strong className="text-2xl font-bold font-mono text-white">
            {compareRun ? compareRun.selected_table_shape.split(' ')[0] + 'x' + compareRun.selected_table_shape.split(' ')[3] : '2x2'}
          </strong>
          <span className="text-[10px] text-gray-500 block font-sans">Before reconstruction metrics</span>
        </div>

        {/* After grid size */}
        <div className="space-y-1">
          <span className="text-[10px] font-mono text-gray-500 uppercase block">Resolved Grid</span>
          <strong className="text-2xl font-bold font-mono text-[#00f0ff]">
            {activeRun ? activeRun.selected_table_shape.split(' ')[0] + 'x' + activeRun.selected_table_shape.split(' ')[3] : '4x8'}
          </strong>
          <span className="text-[10px] text-gray-500 block font-sans">After alignment heuristics</span>
        </div>

        {/* Latency */}
        <div className="space-y-1">
          <span className="text-[10px] font-mono text-gray-500 uppercase block">Latency (ms)</span>
          <div className="flex items-baseline space-x-2">
            <strong className="text-2xl font-bold font-mono text-white">148</strong>
            {compareRun && (
              <span className="text-xs font-mono font-semibold text-rose-400">
                +22ms
              </span>
            )}
          </div>
          <span className="text-[10px] text-gray-500 block font-sans">TSR spatial segmentation phase</span>
        </div>

      </div>

      {/* Main Work Split */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        {/* Left 1 Column: Candidate Card Previews */}
        <div className="lg:col-span-1 space-y-4">
          <h3 className="text-xs font-mono text-gray-500 uppercase tracking-wider">TSR Candidates ({candidates.length})</h3>
          
          <div className="space-y-3 max-h-[calc(100vh-25rem)] overflow-y-auto pr-1 custom-scrollbar">
            {candidates.map(cand => {
              const isSelected = selectedCandidateId === cand.table_id;
              return (
                <div
                  key={cand.table_id}
                  onClick={() => setSelectedCandidateId(cand.table_id)}
                  className={`bg-[#161b22] border rounded-lg p-3 cursor-pointer transition-all ${
                    isSelected ? 'border-[#58a6ff] ring-1 ring-[#58a6ff]' : 'border-[#30363d] hover:border-gray-500'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs font-bold text-white">{cand.table_id}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold font-mono ${
                      cand.selected
                        ? 'bg-emerald-950 text-emerald-400'
                        : cand.rejection_reason?.includes('overlap')
                          ? 'bg-orange-950/45 text-orange-400'
                          : 'bg-rose-950/45 text-rose-400'
                    }`}>
                      {cand.selected ? 'SELECTED' : cand.rejection_reason?.includes('overlap') ? 'OVERLAP' : 'REJECTED'}
                    </span>
                  </div>

                  {/* Tiny mockup grid representation */}
                  <div className="bg-[#0d1117] p-2 rounded border border-[#30363d] font-mono text-[9px] text-gray-500 space-y-1 mb-2">
                    <div className="flex justify-between border-b border-[#21262d] pb-1 font-bold">
                      <span>Grid: {cand.rows}x{cand.cols}</span>
                      <span>Cov: {cand.x_coverage}%</span>
                    </div>
                    <div className="truncate">Engine: {cand.source_engine}</div>
                    <div className="truncate">Score: {cand.score.toFixed(3)}</div>
                  </div>

                  {cand.rejection_reason && (
                    <div className="text-[10px] text-rose-400 leading-normal line-clamp-2 italic">
                      "{cand.rejection_reason}"
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right 3 Columns: Grid Details and Log Output */}
        <div className="lg:col-span-3 space-y-6">
          
          {/* Active Candidate Diagnostics Table */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
            <div className="p-4 bg-[#0d1117] border-b border-[#30363d] flex items-center justify-between">
              <span className="text-xs font-mono text-gray-400 uppercase">Candidate Diagnostics Grid</span>
              {compareRun && (
                <div className="bg-[#1f242c] text-[10px] text-[#58a6ff] border border-blue-900/60 px-2 py-0.5 rounded font-mono">
                  Diff Mode Enabled (Run {compareRunId?.substring(4, 12)})
                </div>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0d1117] border-b border-[#30363d] text-gray-400 uppercase text-[9px]">
                  <tr>
                    <th className="py-2.5 px-4">Table ID</th>
                    <th className="py-2.5 px-4">Engine</th>
                    <th className="py-2.5 px-4 text-center">Shape</th>
                    <th className="py-2.5 px-4 text-right">X-Cov</th>
                    <th className="py-2.5 px-4 text-right">Y-Cov</th>
                    <th className="py-2.5 px-4 text-right">Cells</th>
                    <th className="py-2.5 px-4 text-right">TSR Score</th>
                    <th className="py-2.5 px-4 text-center">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363d]">
                  {candidates.map((cand) => {
                    const isSelected = selectedCandidateId === cand.table_id;
                    return (
                      <tr
                        key={cand.table_id}
                        onClick={() => setSelectedCandidateId(cand.table_id)}
                        className={`hover:bg-[#1f242c] cursor-pointer transition-colors ${
                          isSelected ? 'bg-[#1f242c]/60' : ''
                        }`}
                      >
                        <td className="py-2.5 px-4 font-bold text-white flex items-center space-x-1.5">
                          <span>{cand.table_id}</span>
                          {cand.selected && <CheckCircle size={12} className="text-emerald-400" />}
                        </td>
                        <td className="py-2.5 px-4 text-gray-300">{cand.source_engine}</td>
                        <td className="py-2.5 px-4 text-center text-gray-300">{cand.rows}x{cand.cols}</td>
                        <td className="py-2.5 px-4 text-right text-gray-400">{cand.x_coverage}%</td>
                        <td className="py-2.5 px-4 text-right text-gray-400">{cand.y_coverage}%</td>
                        <td className="py-2.5 px-4 text-right text-gray-400">{cand.non_empty_cells}/{cand.cell_count}</td>
                        <td className="py-2.5 px-4 text-right text-white font-semibold">{cand.score.toFixed(3)}</td>
                        <td className="py-2.5 px-4 text-center">
                          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                            cand.selected ? 'bg-emerald-950 text-emerald-400' : 'bg-rose-950 text-rose-400'
                          }`}>
                            {cand.selected ? 'PRIMARY' : 'REJECTED'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Candidate Preview Grid */}
          {activeCandidate && (
            <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
              <div className="p-4 bg-[#0d1117] border-b border-[#30363d] flex items-center justify-between">
                <div className="flex items-center space-x-2 text-xs font-mono">
                  <span className="text-gray-500 uppercase">Preview Grid:</span>
                  <strong className="text-white">{activeCandidate.table_id}</strong>
                </div>
                {activeCandidate.rejection_reason && (
                  <div className="text-[10px] text-rose-400 flex items-center space-x-1 font-mono">
                    <Info size={12} />
                    <span>Rejection Reason: {activeCandidate.rejection_reason}</span>
                  </div>
                )}
              </div>

              <div className="p-4 overflow-x-auto">
                <table className="w-full text-left text-xs font-mono border-collapse">
                  <tbody>
                    {activeCandidate.preview_cells.map((row, rIdx) => (
                      <tr key={rIdx}>
                        {row.map((cell, cIdx) => (
                          <td
                            key={cIdx}
                            className={`border border-[#30363d] p-2 text-xs min-w-[100px] truncate max-w-[160px] ${
                              rIdx === 0 ? 'bg-[#0d1117] font-bold text-gray-400 text-[10px]' : 'text-gray-300'
                            }`}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Heuristic selection logs */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
            <div className="p-3 bg-[#0d1117] border-b border-[#30363d] text-xs font-mono text-gray-500 uppercase">
              Entity Resolver Logs (Selection Trace)
            </div>
            <pre className="p-4 text-[11px] font-mono leading-relaxed bg-[#0d1117] overflow-x-auto text-[#8b949e] max-h-36 custom-scrollbar">
              {`[15:10:12.4] [INFO] TSR Engine candidate tables generation initialized. Found (4) candidates.
[15:10:12.5] [INFO] Candidate T_ID_001A score (0.994) matches layout profiles criteria. Selected as candidate.
[15:10:12.6] [WARN] Candidate T_ID_002A (Heuristic_TSR) shares overlap of 92.4% with primary candidate T_ID_001A. Suppressed.
[15:10:12.7] [WARN] Candidate T_ID_001B (TATR) does not match minimal dense rows structure heuristic. Rejection score assigned.
[15:10:12.7] [INFO] Candidate T_ID_003X size (12.0%) is below threshold region box area. Rejection assigned.
[15:10:12.8] [INFO] TSR layout resolver complete. Selected primary table: T_ID_001A.`}
            </pre>
          </div>

        </div>

      </div>
    </div>
  );
};
