import React, { useState, useEffect } from 'react';
import { ShieldCheck, Cpu, Sliders, Settings, Lock, Check, Save } from 'lucide-react';

interface SaasSettingsState {
  confidenceThreshold: number;
  autoVerifyThreshold: number;
  taxPreference: 'GST' | 'VAT' | 'Other';
}

export const SaaSSettingsPage: React.FC = () => {
  // Navigation tabs
  const [activeTab, setActiveTab] = useState<'extraction' | 'general' | 'company' | 'export'>('extraction');
  
  // Settings State
  const [settings, setSettings] = useState<SaasSettingsState>({
    confidenceThreshold: 85,
    autoVerifyThreshold: 95,
    taxPreference: 'GST'
  });

  const [toastVisible, setToastVisible] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem('pharmaflow_saas_settings');
      if (stored) {
        setSettings(JSON.parse(stored));
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  // Save handler
  const handleSave = () => {
    try {
      localStorage.setItem('pharmaflow_saas_settings', JSON.stringify(settings));
      setToastVisible(true);
      setTimeout(() => setToastVisible(false), 2000);
    } catch (e) {
      alert('Failed to save settings: ' + String(e));
    }
  };

  // Discard changes / reset
  const handleDiscard = () => {
    try {
      const stored = localStorage.getItem('pharmaflow_saas_settings');
      if (stored) {
        setSettings(JSON.parse(stored));
      } else {
        setSettings({
          confidenceThreshold: 85,
          autoVerifyThreshold: 95,
          taxPreference: 'GST'
        });
      }
      alert('Changes discarded.');
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* Toast Alert */}
      {toastVisible && (
        <div className="fixed top-20 right-8 bg-[#1b5dfc] text-white px-4 py-3 rounded-xl text-xs font-semibold z-50 shadow-lg shadow-blue-500/20 flex items-center space-x-2 border border-blue-400/20">
          <Check size={14} className="stroke-[2.5]" />
          <span>System Settings updated successfully!</span>
        </div>
      )}

      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">System Settings</h2>
        <p className="text-gray-500 text-sm">Configure your pharma-data processing engine, extraction accuracy, and corporate compliance preferences.</p>
      </div>

      {/* Inner split layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
        
        {/* Left Sub-nav panel (Col Span 3) */}
        <div className="md:col-span-3 space-y-6">
          <div className="bg-white rounded-2xl border border-[#e2e8f0] p-3 shadow-sm space-y-1">
            {[
              { id: 'general', label: 'General', icon: Settings },
              { id: 'extraction', label: 'Extraction', icon: Cpu },
              { id: 'company', label: 'Company', icon: ShieldCheck },
              { id: 'export', label: 'Export', icon: Sliders }
            ].map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;

              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-semibold transition-all duration-200 cursor-pointer ${
                    active
                      ? 'bg-[#1b5dfc] text-white shadow-md shadow-blue-500/10'
                      : 'text-gray-500 hover:bg-[#f4f5fa] hover:text-[#0f172a]'
                  }`}
                >
                  <Icon size={16} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* System Status card widget */}
          <div className="bg-[#eaeef6] border border-[#cbd5e1] rounded-2xl p-4 space-y-2.5">
            <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider block">System Status</span>
            <div className="flex items-center space-x-1.5 text-xs">
              <span className="w-2.5 h-2.5 bg-[#1b5dfc] rounded-full animate-pulse" />
              <span className="font-bold text-[#0f172a]">ACTIVE ENGINE</span>
            </div>
            <span className="text-[10px] text-gray-500 block font-mono">Version 4.2.0-stable</span>
          </div>
        </div>

        {/* Right Settings Form panel (Col Span 9) */}
        <div className="md:col-span-9 space-y-6">
          
          {activeTab === 'extraction' ? (
            <div className="space-y-6">
              
              {/* 1. Extraction Engine Card */}
              <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-[#0f172a]">Extraction Engine</h3>
                    <p className="text-gray-500 text-[11px] mt-0.5">Primary processing unit for invoice data recognition.</p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="bg-blue-50 text-[#1b5dfc] text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider">
                      Powered by AI
                    </span>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Primary Processor</label>
                  <div className="relative">
                    <input
                      type="text"
                      readOnly
                      value="Azure Document Intelligence"
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl pl-4 pr-10 py-3 text-xs text-gray-500 font-medium cursor-not-allowed outline-none font-mono"
                    />
                    <Lock size={14} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  </div>
                  <p className="text-[10px] text-gray-400 flex items-center space-x-1 pt-1">
                    <InfoIcon size={12} />
                    <span>This engine is managed by your Enterprise License. Contact IT to change providers.</span>
                  </p>
                </div>
              </div>

              {/* 2. Thresholds & Validation Slider Card */}
              <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-6">
                <div>
                  <h3 className="text-sm font-bold text-[#0f172a]">Thresholds &amp; Validation</h3>
                  <p className="text-gray-500 text-[11px] mt-0.5">Manage pipeline flagging tolerances and auto-verification thresholds.</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 border-t border-gray-100 pt-6">
                  {/* Slider 1: Confidence Threshold */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Confidence Threshold</label>
                      <span className="text-base font-extrabold text-[#1b5dfc] font-mono">{settings.confidenceThreshold}%</span>
                    </div>
                    <input
                      type="range"
                      min="50"
                      max="100"
                      value={settings.confidenceThreshold}
                      onChange={(e) => setSettings(prev => ({ ...prev, confidenceThreshold: parseInt(e.target.value) }))}
                      className="w-full h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-[#1b5dfc]"
                    />
                    <p className="text-[10px] text-gray-400 leading-relaxed">
                      Minimum confidence required to suggest field values without a warning flag.
                    </p>
                  </div>

                  {/* Slider 2: Auto-verify Threshold */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Auto-Verify Threshold</label>
                      <span className="text-base font-extrabold text-[#1b5dfc] font-mono">{settings.autoVerifyThreshold}%</span>
                    </div>
                    <input
                      type="range"
                      min="50"
                      max="100"
                      value={settings.autoVerifyThreshold}
                      onChange={(e) => setSettings(prev => ({ ...prev, autoVerifyThreshold: parseInt(e.target.value) }))}
                      className="w-full h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-[#1b5dfc]"
                    />
                    <p className="text-[10px] text-gray-400 leading-relaxed">
                      Threshold for bypassing manual review and marking documents as 'Verified'.
                    </p>
                  </div>
                </div>
              </div>

              {/* 3. Default Tax Preference Card */}
              <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
                <div>
                  <h3 className="text-sm font-bold text-[#0f172a]">Default Tax Preference</h3>
                  <p className="text-gray-500 text-[11px] mt-0.5">Set the global default tax type for newly imported invoices.</p>
                </div>

                <div className="w-64 bg-[#f4f5fa] p-1.5 rounded-xl flex items-center border border-gray-200/50">
                  {(['GST', 'VAT', 'Other'] as const).map((pref) => {
                    const selected = settings.taxPreference === pref;
                    return (
                      <button
                        key={pref}
                        onClick={() => setSettings(prev => ({ ...prev, taxPreference: pref }))}
                        className={`flex-1 text-center py-2 text-xs font-semibold rounded-lg transition-all duration-200 cursor-pointer ${
                          selected
                            ? 'bg-white text-[#1b5dfc] shadow-sm font-bold'
                            : 'text-gray-500 hover:text-gray-800'
                        }`}
                      >
                        {pref}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Form Action Controls */}
              <div className="flex items-center justify-end space-x-3 pt-4 border-t border-gray-200">
                <button
                  onClick={handleDiscard}
                  className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-5 py-2.5 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer"
                >
                  Discard Changes
                </button>
                <button
                  onClick={handleSave}
                  className="bg-[#1b5dfc] hover:bg-[#154ecb] text-white font-semibold px-5 py-2.5 rounded-xl text-xs flex items-center space-x-1.5 shadow-md shadow-blue-500/10 transition-colors cursor-pointer"
                >
                  <Save size={14} />
                  <span>Save Settings</span>
                </button>
              </div>

            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-[#e2e8f0] p-12 text-center text-gray-400 text-xs shadow-sm">
              Tab setting panel content is mock-locked. Switch to <span className="text-blue-500 underline cursor-pointer" onClick={() => setActiveTab('extraction')}>Extraction Settings</span>.
            </div>
          )}

        </div>

      </div>
    </div>
  );
};

// Local component helpers to avoid missing references
const InfoIcon: React.FC<{ size: number; className?: string }> = ({ size, className }) => (
  <svg 
    xmlns="http://www.w3.org/2000/svg" 
    width={size} 
    height={size} 
    viewBox="0 0 24 24" 
    fill="none" 
    stroke="currentColor" 
    strokeWidth="2" 
    strokeLinecap="round" 
    strokeLinejoin="round" 
    className={className}
  >
    <circle cx="12" cy="12" r="10" />
    <path d="M12 16v-4" />
    <path d="M12 8h.01" />
  </svg>
);

export default SaaSSettingsPage;
