import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import {
  FileText,
  Activity,
  Layers,
  Cpu,
  Grid,
  MapPin,
  TrendingUp,
  ShieldCheck,
  FolderOpen,
  Settings as SettingsIcon,
  Bell,
  User,
  Copy,
  Download,
  CheckCircle
} from 'lucide-react';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const {
    runs,
    currentRunId,
    setCurrentRunId,
    currentRun,
    isBackendActive
  } = useRun();

  const location = useLocation();
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);

  const handleCopySummary = async () => {
    if (!currentRunId) return;
    try {
      await apiClient.copyDebugSummary(currentRunId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy summary:', err);
    }
  };

  const handleDownloadArtifacts = () => {
    if (!currentRunId) return;
    apiClient.downloadArtifactBundle(currentRunId);
  };

  const menuItems = [
    { name: 'Runs', path: '/runs', icon: FileText },
    { name: 'Invoice Debugger', path: `/debugger/${currentRunId || ''}`, icon: Cpu, disabled: !currentRunId },
    { name: 'Candidate Tables', path: `/candidate-tables/${currentRunId || ''}`, icon: Layers, disabled: !currentRunId },
    { name: 'OCR Tokens', path: `/ocr-tokens/${currentRunId || ''}`, icon: Activity, disabled: !currentRunId },
    { name: 'Selected Table', path: `/selected-table/${currentRunId || ''}`, icon: Grid, disabled: !currentRunId },
    { name: 'Semantic Mapping', path: `/semantic-mapping/${currentRunId || ''}`, icon: MapPin, disabled: !currentRunId },
    { name: 'Row Math', path: `/row-math/${currentRunId || ''}`, icon: TrendingUp, disabled: !currentRunId },
    { name: 'Quality Gate', path: `/quality-gate/${currentRunId || ''}`, icon: ShieldCheck, disabled: !currentRunId },
    { name: 'Artifacts', path: `/artifacts/${currentRunId || ''}`, icon: FolderOpen, disabled: !currentRunId },
    { name: 'Settings', path: '/settings', icon: SettingsIcon },
  ];

  // Helper to get active page title for breadcrumb
  const getPageTitle = () => {
    const path = location.pathname;
    if (path.includes('/runs')) return 'Runs';
    if (path.includes('/debugger')) return 'Invoice Debugger';
    if (path.includes('/candidate-tables')) return 'Candidate Tables';
    if (path.includes('/ocr-tokens')) return 'OCR Tokens';
    if (path.includes('/selected-table')) return 'Selected Table';
    if (path.includes('/semantic-mapping')) return 'Semantic Mapping';
    if (path.includes('/row-math')) return 'Row Math';
    if (path.includes('/quality-gate')) return 'Quality Gate';
    if (path.includes('/artifacts')) return 'Artifacts';
    if (path.includes('/settings')) return 'Settings';
    return 'Dashboard';
  };

  return (
    <div className="flex h-screen bg-[#0d1117] text-[#c9d1d9] font-sans overflow-hidden">
      
      {/* LEFT PERSISTENT SIDEBAR */}
      <aside className="w-64 bg-[#161b22] border-r border-[#30363d] flex flex-col justify-between shrink-0">
        <div>
          {/* Brand Logo */}
          <div className="p-5 border-b border-[#30363d] flex items-center space-x-3">
            <div className="bg-[#00f0ff] p-1.5 rounded text-[#0d1117]">
              <Cpu size={20} className="stroke-[2.5]" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white leading-none">OCR Workbench</h1>
              <span className="text-[10px] text-gray-500 font-mono">v2.4.1-stable</span>
            </div>
          </div>

          {/* System status */}
          <div className="px-5 py-3 border-b border-[#30363d] flex items-center justify-between text-xs">
            <span className="text-gray-400">System Status</span>
            <div className="flex items-center space-x-1.5">
              <span className={`w-2.5 h-2.5 rounded-full ${isBackendActive ? 'bg-[#2ea44f] animate-pulse' : 'bg-[#d29922]'}`} />
              <span className={`font-mono font-medium ${isBackendActive ? 'text-[#2ea44f]' : 'text-[#d29922]'}`}>
                {isBackendActive ? 'Active' : 'Backend Offline'}
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname.startsWith(item.path.split('/:')[0]);
              const disabled = item.disabled;

              if (disabled) {
                return (
                  <div
                    key={item.name}
                    className="flex items-center space-x-3 px-3 py-2 text-sm text-gray-600 cursor-not-allowed select-none"
                    title="Select a run to unlock this tool"
                  >
                    <Icon size={18} />
                    <span>{item.name}</span>
                  </div>
                );
              }

              return (
                <Link
                  key={item.name}
                  to={item.path}
                  className={`flex items-center space-x-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-[#1f242c] text-[#58a6ff] border-l-2 border-[#58a6ff]'
                      : 'text-gray-400 hover:bg-[#21262d] hover:text-white'
                  }`}
                >
                  <Icon size={18} />
                  <span>{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Persistence indicator at bottom */}
        <div className="p-4 border-t border-[#30363d] bg-[#0d1117] text-[11px] text-gray-500 font-mono">
          <div className="flex items-center justify-between">
            <span>Persistence</span>
            <span className="text-green-500">Active Cluster</span>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span>Device</span>
            <span>Tesla T4 GPU</span>
          </div>
        </div>
      </aside>

      {/* MAIN CONTAINER */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        
        {/* GLOBAL TOP BAR */}
        <header className="h-14 bg-[#161b22] border-b border-[#30363d] flex items-center justify-between px-6 shrink-0 z-10">
          
          {/* Left info: Breadcrumb & Run filename */}
          <div className="flex items-center space-x-4">
            <div className="text-xs text-gray-400 flex items-center space-x-1.5 font-mono">
              <span className="hover:underline cursor-pointer" onClick={() => navigate('/runs')}>Runs</span>
              <span>/</span>
              {currentRun && (
                <>
                  <span className="text-gray-300 font-semibold">{currentRun.filename}</span>
                  <span>/</span>
                </>
              )}
              <span className="text-[#58a6ff] font-semibold">{getPageTitle()}</span>
            </div>

            {/* Run Selection dropdown */}
            {runs.length > 0 && (
              <select
                value={currentRunId || ''}
                onChange={(e) => {
                  const targetRunId = e.target.value;
                  setCurrentRunId(targetRunId);
                  // Dynamic navigation rewrite to change runId in active tool URL
                  const parts = location.pathname.split('/');
                  if (parts.length > 2 && parts[1] !== 'runs' && parts[1] !== 'settings') {
                    navigate(`/${parts[1]}/${targetRunId}`);
                  }
                }}
                className="bg-[#21262d] border border-[#30363d] rounded text-xs px-2 py-1 text-white font-mono focus:outline-none focus:border-[#58a6ff]"
              >
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.filename.length > 15 ? r.filename.substring(0, 15) + '...' : r.filename} ({r.run_id.substring(4, 12)})
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Right info: Metric badges & Action Buttons */}
          <div className="flex items-center space-x-4">
            {currentRun && (
              <div className="hidden lg:flex items-center space-x-3 text-xs border-r border-[#30363d] pr-4">
                
                {/* Safe for ERP badge */}
                <div className="flex items-center space-x-1.5">
                  <span className="text-gray-400">Safe for ERP:</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono tracking-wide ${
                    currentRun.status === 'safe_for_erp'
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                      : currentRun.status === 'needs_review'
                        ? 'bg-amber-950 text-amber-400 border border-amber-800'
                        : 'bg-rose-950 text-rose-400 border border-rose-800'
                  }`}>
                    {currentRun.status === 'safe_for_erp' ? 'SAFE' : currentRun.status === 'needs_review' ? 'REVIEW' : 'FAILED'}
                  </span>
                </div>

                {/* Confidence */}
                <div className="flex items-center space-x-1">
                  <span className="text-gray-400">Confidence:</span>
                  <span className="font-mono text-white font-semibold">{(currentRun.confidence * 100).toFixed(1)}%</span>
                </div>

                {/* Coverage */}
                <div className="flex items-center space-x-1">
                  <span className="text-gray-400">Coverage:</span>
                  <span className="font-mono text-white font-semibold">{(currentRun.token_coverage * 100).toFixed(1)}%</span>
                </div>

                {/* Representability */}
                <div className="flex items-center space-x-1">
                  <span className="text-gray-400">TSR:</span>
                  <span className="font-mono text-white font-semibold">{(currentRun.representability_score * 100).toFixed(1)}%</span>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center space-x-2">
              <button
                onClick={handleCopySummary}
                disabled={!currentRunId}
                className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 font-medium px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                {copied ? <CheckCircle size={14} className="text-emerald-400" /> : <Copy size={14} />}
                <span>{copied ? 'Copied!' : 'Copy Summary'}</span>
              </button>

              <button
                onClick={handleDownloadArtifacts}
                disabled={!currentRunId}
                className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 font-medium px-3 py-1.5 rounded text-xs border border-[#30363d] flex items-center space-x-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                <Download size={14} />
                <span>Bundle</span>
              </button>
            </div>

            {/* Icons */}
            <div className="flex items-center space-x-2 text-gray-400">
              <button className="p-1 hover:text-white transition-colors relative">
                <Bell size={18} />
                <span className="absolute top-1 right-1 w-2 h-2 bg-[#00f0ff] rounded-full" />
              </button>
              <button className="p-1 hover:text-white transition-colors" onClick={() => navigate('/settings')}>
                <User size={18} />
              </button>
            </div>
          </div>
        </header>

        {/* PAGE CONTENT CONTAINER */}
        <main className="flex-1 overflow-y-auto p-6 bg-[#0d1117] min-w-0">
          {children}
        </main>
        
        {/* FOOTER */}
        <footer className="h-7 bg-[#161b22] border-t border-[#30363d] px-6 flex items-center justify-between text-[11px] text-gray-500 font-mono shrink-0">
          <div className="flex items-center space-x-4">
            <span>Pipeline: <strong className="text-gray-400">1240ms latency</strong></span>
            <span>Engine: <strong className="text-[#00f0ff]">ENGINE_V3_STABLE</strong></span>
          </div>
          <div className="flex items-center space-x-4">
            <span className="flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span>Image Validated</span>
            </span>
            <span className="flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span>OCR Complete</span>
            </span>
            <span className="flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
              <span>Quality Gate Warning</span>
            </span>
          </div>
        </footer>

      </div>
    </div>
  );
};
