import React, { useState } from 'react';
import { Cpu, Package, Lock } from 'lucide-react';
import { ItemTypesPanel } from './ItemTypesPanel';

/**
 * System settings.
 *
 * What used to be here was a confidence-threshold slider, an auto-verify
 * slider and a GST/VAT/Other toggle, all writing to a localStorage key that
 * nothing in the application ever read — three controls that looked like they
 * configured the pipeline and configured nothing. Alongside them sat three
 * tabs whose panels rendered the words "mock-locked", and a status card
 * reporting a hardcoded version string.
 *
 * They are gone rather than wired up, because thresholds are not what the
 * pipeline actually keys on: extraction confidence comes back per field from
 * Azure and drives the review flags directly. Promising a global dial over
 * that would be a second lie in place of the first.
 */
export const SaaSSettingsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'catalogue' | 'extraction'>('catalogue');

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-[#0f172a] tracking-tight">System Settings</h2>
        <p className="text-gray-500 text-sm">Define the item types your catalogue uses, and review how invoices are read.</p>
      </div>

      {/* Inner split layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
        
        {/* Left Sub-nav panel (Col Span 3) */}
        <div className="md:col-span-3 space-y-6">
          <div className="bg-white rounded-2xl border border-[#e2e8f0] p-3 shadow-sm space-y-1">
            {[
              { id: 'catalogue', label: 'Catalogue', icon: Package },
              { id: 'extraction', label: 'Extraction', icon: Cpu }
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
        </div>

        {/* Right Settings Form panel (Col Span 9) */}
        <div className="md:col-span-9 space-y-6">
          
          {activeTab === 'catalogue' ? (
            <ItemTypesPanel />
          ) : (
            <div className="space-y-6">

              {/* Extraction engine — genuinely fixed, so stated as fact
                  rather than dressed up as a setting. */}
              <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-[#0f172a]">Extraction Engine</h3>
                    <p className="text-gray-500 text-[11px] mt-0.5">Reads invoice tables into line items.</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Processor</label>
                  <div className="relative">
                    <input
                      type="text"
                      readOnly
                      value="Azure Document Intelligence (prebuilt-invoice)"
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl pl-4 pr-10 py-3 text-xs text-gray-500 font-medium cursor-not-allowed outline-none font-mono"
                    />
                    <Lock size={14} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  </div>
                  <p className="text-[10px] text-gray-400 pt-1">
                    Set by the <code className="font-mono">EXTRACTION_ENGINE</code> environment variable on the server.
                  </p>
                </div>
              </div>

            </div>
          )}

        </div>

      </div>
    </div>
  );
};

export default SaaSSettingsPage;
