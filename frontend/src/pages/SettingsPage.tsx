import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { ShieldCheck, Eye, Cpu, Sliders } from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const { settings, updateSettings, clearWorkbenchState } = useRun();
  const navigate = useNavigate();
  const [toastText, setToastText] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastText(msg);
    setTimeout(() => setToastText(null), 2000);
  };

  const toggleSetting = (key: keyof typeof settings) => {
    updateSettings({ [key]: !settings[key] });
  };

  return (
    <div className="space-y-6">
      {toastText && (
        <div className="fixed top-16 right-6 bg-emerald-950 text-emerald-400 border border-emerald-800 px-4 py-2 rounded text-xs font-semibold z-50 shadow-lg">
          {toastText}
        </div>
      )}
      
      {/* Title */}
      <div>
        <h2 className="text-2xl font-bold text-white tracking-tight">Workbench Preferences &amp; Configurations</h2>
        <p className="text-gray-400 text-sm">Configure visual rendering, toggle pipeline execution heuristic modes, and customize overlay defaults.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Card 1: Visual Rendering Settings */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider font-mono flex items-center space-x-2 border-b border-[#30363d] pb-2">
            <Eye size={16} className="text-[#00f0ff]" />
            <span>Visual overlays &amp; colors</span>
          </h3>

          <div className="space-y-3">
            {[
              {
                title: 'Show BBox Labels',
                desc: 'Overlay descriptive labels on bounding box rect hover tags.',
                key: 'showLabels'
              },
              {
                title: 'Show Confidence Colors',
                desc: 'Color-code table cells according to OCR confidence levels.',
                key: 'confidenceColors'
              },
              {
                title: 'Compact Table Mode',
                desc: 'Compress padding across spreadsheet rows and candidate listings.',
                key: 'compactMode'
              },
              {
                title: 'Enable Diff Mode',
                desc: 'Enable baseline comparison rendering metrics across pages.',
                key: 'diffMode'
              }
            ].map(item => (
              <div key={item.key} className="flex items-center justify-between p-2 rounded hover:bg-[#1f242c]/20">
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-white block">{item.title}</span>
                  <span className="text-[10px] text-gray-500 block">{item.desc}</span>
                </div>
                <input
                  type="checkbox"
                  checked={settings[item.key as keyof typeof settings]}
                  onChange={() => toggleSetting(item.key as keyof typeof settings)}
                  className="w-4 h-4 accent-[#58a6ff] cursor-pointer"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Card 2: Pipeline Engine & TSR Heuristics config */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider font-mono flex items-center space-x-2 border-b border-[#30363d] pb-2">
            <Cpu size={16} className="text-purple-400" />
            <span>TSR &amp; Reconstruction engine</span>
          </h3>

          <div className="space-y-3">
            {[
              {
                title: 'Enable Heuristic TSR',
                desc: 'Enforce custom rule-based alignments alongside ML engine layouts.',
                key: 'heuristicTsr'
              },
              {
                title: 'PPStructure Shadow Mode',
                desc: 'Execute secondary PPStructure engines in shadow thread audits.',
                key: 'shadowMode'
              },
              {
                title: 'Enable Candidate Comparison',
                desc: 'Calculate grid shape scores and latencies between algorithms.',
                key: 'candidateComparison'
              }
            ].map(item => (
              <div key={item.key} className="flex items-center justify-between p-2 rounded hover:bg-[#1f242c]/20">
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-white block">{item.title}</span>
                  <span className="text-[10px] text-gray-500 block">{item.desc}</span>
                </div>
                <input
                  type="checkbox"
                  checked={settings[item.key as keyof typeof settings]}
                  onChange={() => toggleSetting(item.key as keyof typeof settings)}
                  className="w-4 h-4 accent-purple-500 cursor-pointer"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Card 3: Default Overlay States */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 md:col-span-2">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider font-mono flex items-center space-x-2 border-b border-[#30363d] pb-2">
            <Sliders size={16} className="text-amber-500" />
            <span>Default Overlay Activation States</span>
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { title: 'Default OCR Blocks', key: 'overlayOCRBlocks' },
              { title: 'Default Row Boxes', key: 'overlayRowBoxes' },
              { title: 'Default Col Lines', key: 'overlayColBoundaries' },
              { title: 'Default Selected Table', key: 'overlaySelectedTable' },
              { title: 'Default Candidate Tables', key: 'overlayCandidateTables' },
              { title: 'Default Orphans Highlight', key: 'overlayOrphans' },
              { title: 'Default Low Confidence', key: 'overlayLowConfidence' }
            ].map(item => (
              <div key={item.key} className="flex items-center justify-between p-2.5 rounded bg-[#0d1117] border border-[#30363d]">
                <span className="text-[11px] font-mono font-semibold text-gray-300">{item.title}</span>
                <input
                  type="checkbox"
                  checked={settings[item.key as keyof typeof settings]}
                  onChange={() => toggleSetting(item.key as keyof typeof settings)}
                  className="w-3.5 h-3.5 accent-amber-500 cursor-pointer"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Card 4: Danger Zone / System State Reset */}
        <div className="bg-[#161b22] border border-red-900/40 rounded-lg p-5 space-y-4 md:col-span-2">
          <h3 className="text-sm font-semibold text-red-400 uppercase tracking-wider font-mono flex items-center space-x-2 border-b border-red-900/40 pb-2">
            <span>Danger Zone / Reset State</span>
          </h3>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <span className="text-xs font-bold text-white block">Clear Workbench State</span>
              <span className="text-[10px] text-gray-500 block">
                This will delete all locally stored invoice runs and diagnostic details.
              </span>
            </div>
            <button
              onClick={() => {
                const clearSettings = window.confirm("Do you also want to clear your workbench settings/preferences?");
                clearWorkbenchState(clearSettings);
                showToast("Workbench state cleared successfully.");
                setTimeout(() => {
                  navigate('/runs');
                }, 1000);
              }}
              className="bg-red-950 hover:bg-red-900 text-red-400 border border-red-800 px-4 py-2 rounded text-xs font-bold transition-colors cursor-pointer"
            >
              Clear Workbench State
            </button>
          </div>
        </div>

      </div>

      {/* Developer tool guidelines alert */}
      <div className="bg-[#1f242c]/40 border border-blue-900/60 rounded-lg p-4 flex items-start space-x-3 text-xs">
        <ShieldCheck size={18} className="text-[#58a6ff] shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h4 className="font-bold text-white font-sans">Debug Environment Safeguards</h4>
          <p className="text-gray-400 font-sans leading-normal">
            These workbench settings are stored locally in browser storage and apply strictly to this developer interface. Changes here do not impact production parsing latency, LLM extraction configurations, or validation thresholds.
          </p>
        </div>
      </div>

    </div>
  );
};
