import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { QualityGate, RunSummary } from '../api/types';
import { ShieldAlert, ShieldCheck, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

export const QualityGatePage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [qualityGate, setQualityGate] = useState<QualityGate | null>(null);

  // Load quality gate data
  useEffect(() => {
    const loadGateData = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        const runData = await apiClient.getRun(activeId);
        setActiveRun(runData);

        const data = await apiClient.getQualityGate(activeId);
        setQualityGate(data);
      } catch (err) {
        console.error('Failed to load quality gate details:', err);
      }
    };
    loadGateData();
  }, [runId, currentRunId]);

  return (
    <div className="space-y-6">
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Quality Gate &amp; ERP Readiness</h2>
        <p className="text-gray-400 text-sm">Verify the final pipeline validation gate, analyze safety reasons, and trace structural compliance scores.</p>
      </div>

      {qualityGate && activeRun && (
        <div className="space-y-6">
          
          {/* Large Decision Card Banner */}
          <div className={`border rounded-lg p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 shadow-xl ${
            qualityGate.safe_for_erp
              ? 'bg-emerald-950/20 border-emerald-800 text-emerald-400'
              : qualityGate.status_effective === 'failed'
                ? 'bg-rose-950/20 border-rose-800 text-rose-400'
                : 'bg-amber-950/20 border-amber-800 text-amber-400'
          }`}>
            <div className="flex items-start space-x-4">
              <div className={`p-3 rounded-lg ${
                qualityGate.safe_for_erp
                  ? 'bg-emerald-900 text-emerald-300'
                  : qualityGate.status_effective === 'failed'
                    ? 'bg-rose-900 text-rose-300'
                    : 'bg-amber-900 text-amber-300'
              }`}>
                {qualityGate.safe_for_erp ? <ShieldCheck size={28} /> : <ShieldAlert size={28} />}
              </div>
              
              <div className="space-y-1">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-widest block">Quality Verification Verdict</span>
                <h3 className="text-xl font-bold font-sans tracking-tight text-white">
                  {qualityGate.safe_for_erp
                    ? '✓ SAFE FOR ERP INGESTION'
                    : qualityGate.status_effective === 'failed'
                      ? '❌ PIPELINE INGESTION FAILURE'
                      : '⚠ MANUAL CLASSIFICATION RECONCILIATION NEEDED'}
                </h3>
                <p className="text-xs text-gray-400 max-w-2xl leading-relaxed">
                  {qualityGate.safe_for_erp
                    ? 'All compliance checkpoints resolved. Spatial tables are fully representable, row mathematical parameters strictly balance within tolerance, and confidence is above safety thresholds.'
                    : qualityGate.status_effective === 'failed'
                      ? 'Ingestion blocked: Core components failed validation. Pipeline OCR confidence fell below critical safety thresholds or contains conflicting structures.'
                      : 'This document layout contains minor mapping errors or missing footer keys (such as subtotal) that requires manual review before exporting to ERP systems.'}
                </p>
              </div>
            </div>

            {/* Ingestion badge */}
            <div className="shrink-0">
              <span className={`px-4 py-2 rounded font-mono font-bold text-xs border tracking-wider ${
                qualityGate.safe_for_erp
                  ? 'bg-emerald-950 text-emerald-400 border-emerald-800'
                  : qualityGate.status_effective === 'failed'
                    ? 'bg-rose-950 text-rose-400 border-rose-800'
                    : 'bg-amber-950 text-amber-400 border-amber-800'
              }`}>
                {qualityGate.status_effective.replace(/_/g, ' ').toUpperCase()}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Left 2 Columns: Compliance checklist */}
            <div className="lg:col-span-2 space-y-4">
              <h3 className="text-xs font-mono text-gray-500 uppercase tracking-wider">Gate Checklist Items</h3>
              
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg divide-y divide-[#30363d]">
                {qualityGate.checklist.map((item, idx) => {
                  return (
                    <div key={idx} className="p-4 flex items-start justify-between gap-4 hover:bg-[#1f242c]/25 transition-colors">
                      <div className="flex items-start space-x-3">
                        <div className="mt-0.5 shrink-0">
                          {item.status === 'pass' ? (
                            <CheckCircle2 size={16} className="text-emerald-400" />
                          ) : item.status === 'warning' ? (
                            <AlertTriangle size={16} className="text-amber-400" />
                          ) : (
                            <XCircle size={16} className="text-rose-400" />
                          )}
                        </div>
                        <div className="space-y-0.5">
                          <h4 className="text-xs font-bold text-white font-sans">{item.name}</h4>
                          <p className="text-[11px] text-gray-400 leading-normal font-sans">{item.explanation}</p>
                        </div>
                      </div>

                      <span className={`px-2 py-0.5 rounded text-[9px] font-mono font-bold border shrink-0 ${
                        item.status === 'pass'
                          ? 'bg-emerald-950/20 text-emerald-400 border-emerald-900/40'
                          : item.status === 'warning'
                            ? 'bg-amber-950/20 text-amber-400 border-amber-900/40'
                            : 'bg-rose-950/20 text-rose-400 border-rose-900/40'
                      }`}>
                        {item.status.toUpperCase()}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right 1 Column: Decision logs & metrics summaries */}
            <div className="lg:col-span-1 space-y-6">
              
              {/* Compliance Scores */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs">
                <h3 className="text-xs font-mono text-gray-500 uppercase tracking-wider border-b border-[#30363d] pb-2">Compliance metrics</h3>
                
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Invoice Confidence:</span>
                    <strong className="text-white">{(activeRun.confidence * 100).toFixed(1)}%</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">TSR Representability:</span>
                    <strong className="text-white">{(activeRun.representability_score * 100).toFixed(1)}%</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Token Coverage Score:</span>
                    <strong className="text-white">{(activeRun.token_coverage * 100).toFixed(1)}%</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Footer Rescue:</span>
                    <span className="text-gray-300">{qualityGate.footer_status}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Row math reconciliation:</span>
                    <span className={`font-semibold ${qualityGate.row_math_status === 'pass' ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {qualityGate.row_math_status.toUpperCase()}
                    </span>
                  </div>
                </div>
              </div>

              {/* Ingestion block reasons list */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 font-mono text-xs">
                <h3 className="text-xs font-mono text-rose-400 uppercase tracking-wider border-b border-[#30363d] pb-2 flex items-center space-x-1.5">
                  <ShieldAlert size={14} />
                  <span>Reasons trace logs</span>
                </h3>
                
                <div className="space-y-3 leading-relaxed text-gray-300 font-sans text-xs">
                  {qualityGate.reasons.map((r, i) => (
                    <div key={i} className="flex items-start space-x-2">
                      <span className="text-rose-400 font-bold font-mono mt-0.5">•</span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              </div>

            </div>

          </div>

        </div>
      )}

    </div>
  );
};
