import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import {
  LayoutDashboard,
  Upload,
  History,
  Package,
  BarChart3,
  Settings,
  Search,
  Bell,
  HelpCircle,
  Menu,
  ChevronDown,
  Trash2 // Destructive database zap icon
} from 'lucide-react';

export const SaaSLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isBackendActive } = useRun();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // States to control Clear Bench workflow
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [toastText, setToastText] = useState<string | null>(null);

  const menuItems = [
    { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { name: 'Upload Invoice', path: '/upload', icon: Upload },
    { name: 'Invoice History', path: '/history', icon: History },
    { name: 'Inventory', path: '/inventory', icon: Package },
    { name: 'Reports', path: '/reports', icon: BarChart3 },
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  // Helper check: does path match current route
  const isActive = (path: string) => {
    if (path === '/dashboard') {
      return location.pathname === '/' || location.pathname.startsWith('/dashboard');
    }
    return location.pathname.startsWith(path);
  };

  // Safe check if any bench data exists to be cleared
  const hasData = () => {
    const runs = localStorage.getItem('ocr_workbench_runs');
    let parsedRuns = [];
    if (runs) {
      try { parsedRuns = JSON.parse(runs); } catch {}
    }
    
    const inventory = localStorage.getItem('pharmaflow_inventory');
    let parsedInventory = [];
    if (inventory) {
      try { parsedInventory = JSON.parse(inventory); } catch {}
    }
    
    let hasDetail = false;
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (
        key.startsWith('ocr_workbench_run_detail_') || 
        key.startsWith('ocr_workbench_image_') || 
        key.startsWith('ocr_workbench_processed_image_')
      )) {
        hasDetail = true;
        break;
      }
    }
    
    return parsedRuns.length > 0 || parsedInventory.length > 0 || hasDetail || sessionStorage.length > 0;
  };

  // Action: Trigger confirmation dialog or show baseline clear state
  const handleClearBenchClick = () => {
    if (!hasData()) {
      setToastText("Bench is already clear.");
      setTimeout(() => setToastText(null), 2000);
      return;
    }
    setShowClearConfirm(true);
  };

  useEffect(() => {
    const handleTrigger = () => {
      handleClearBenchClick();
    };
    window.addEventListener('trigger-clear-bench', handleTrigger);
    return () => {
      window.removeEventListener('trigger-clear-bench', handleTrigger);
    };
  }, []);

  // Action: Confirm cleanup of local storage entries
  const confirmClearBench = () => {
    const keysToRemove: string[] = [];
    const settingsSubstrings = ['setting', 'preference', 'threshold', 'theme'];

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key) continue;

      const lowerKey = key.toLowerCase();
      
      // Keep settings keys untouched
      const isSetting = settingsSubstrings.some(sub => lowerKey.includes(sub));
      if (isSetting) continue;

      // Identify runs, history, drafts, inventory
      const isTestData = [
        'invoice',
        'run',
        'draft',
        'inventory',
        'queue',
        'detail',
        'record',
        'pharmaflow_inventory',
        'ocr_workbench_runs',
        'ocr_workbench_run_detail_'
      ].some(sub => lowerKey.includes(sub));

      if (isTestData) {
        keysToRemove.push(key);
      }
    }

    // Purge test keys
    keysToRemove.forEach(key => localStorage.removeItem(key));
    sessionStorage.clear();

    setShowClearConfirm(false);
    setToastText("Bench cleared. Ready for fresh invoice testing.");
    
    // Redirect to Dashboard and hard reload context state
    setTimeout(() => {
      setToastText(null);
      navigate('/dashboard');
      window.location.reload();
    }, 1500);
  };

  return (
    <div className="flex h-screen bg-[#f4f5fa] text-[#1f2937] font-sans overflow-hidden">
      {/* Toast Alert Banner */}
      {toastText && (
        <div className="fixed top-16 right-6 bg-[#0f172a] text-white border border-gray-800 px-4 py-3 rounded-xl text-xs font-semibold z-50 shadow-xl flex items-center space-x-2 animate-in slide-in-from-top duration-300">
          <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-ping" />
          <span>{toastText}</span>
        </div>
      )}

      {/* Confirmation Dialog Overlay */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs">
          <div className="bg-white rounded-2xl border border-gray-200 p-6 max-w-md w-full mx-4 shadow-xl space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-start space-x-3">
              <div className="p-2 bg-red-50 text-red-600 rounded-xl shrink-0">
                <Trash2 size={22} />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-bold text-[#0f172a]">Clear all local invoice test data?</h3>
                <p className="text-xs text-gray-500 leading-normal">
                  This will remove uploaded invoice history, review drafts, and generated inventory from this browser only. Backend files and extraction settings will not be affected.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-gray-100">
              <button
                onClick={() => setShowClearConfirm(false)}
                className="bg-white hover:bg-slate-50 text-gray-700 font-semibold px-4 py-2 rounded-xl text-xs border border-gray-200 shadow-sm transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={confirmClearBench}
                className="bg-red-600 hover:bg-red-700 text-white font-semibold px-4 py-2 rounded-xl text-xs shadow-md shadow-red-500/10 transition-colors cursor-pointer"
              >
                Clear Bench
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SIDEBAR - DESKTOP */}
      <aside className="hidden md:flex w-64 bg-[#f0f2fa] border-r border-[#e2e8f0] flex-col justify-between shrink-0">
        <div>
          {/* Logo Section */}
          <div className="p-6 border-b border-[#e2e8f0] flex items-center space-x-3">
            <div className="bg-[#1b5dfc] p-2 rounded-lg text-white shadow-md shadow-blue-500/20">
              <Package size={20} className="stroke-[2.5]" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-[#0f172a] leading-none">PharmaFlow</h1>
              <span className="text-[10px] text-gray-500 font-mono">Admin Portal</span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-4 space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);

              return (
                <Link
                  key={item.name}
                  to={item.path}
                  className={`flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
                    active
                      ? 'bg-[#1b5dfc] text-white shadow-md shadow-blue-500/10'
                      : 'text-gray-600 hover:bg-[#e2e8f0] hover:text-[#0f172a]'
                  }`}
                >
                  <Icon size={18} className={active ? 'text-white' : 'text-gray-500'} />
                  <span>{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* User profile & backend status at bottom */}
        <div className="p-4 border-t border-[#e2e8f0] bg-[#eaeef6] space-y-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center shadow-inner">
              PA
            </div>
            <div className="flex-1 min-w-0">
              <h4 className="text-xs font-semibold text-[#0f172a] truncate">Admin User</h4>
              <p className="text-[10px] text-gray-500 truncate">admin@pharmaflow.io</p>
            </div>
            <ChevronDown size={14} className="text-gray-500" />
          </div>

          <div className="pt-2 border-t border-gray-300/50 flex items-center justify-between text-[10px]">
            <span className="text-gray-500 font-mono">Backend Status:</span>
            <div className="flex items-center space-x-1">
              <span className={`w-2 h-2 rounded-full ${isBackendActive ? 'bg-green-500' : 'bg-amber-500 animate-pulse'}`} />
              <span className={`font-semibold ${isBackendActive ? 'text-green-600' : 'text-amber-600'}`}>
                {isBackendActive ? 'Connected' : 'Offline Mode'}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* MOBILE MENU TRIGGER */}
      <div className="md:hidden fixed top-3 left-4 z-50">
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-lg bg-white border border-[#e2e8f0] text-gray-700 shadow-sm focus:outline-none"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* MOBILE OVERLAY MENU */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="fixed inset-0 bg-black/40" onClick={() => setMobileMenuOpen(false)} />
          <aside className="relative w-64 max-w-xs bg-[#f0f2fa] h-full flex flex-col justify-between p-4 z-50">
            <div>
              <div className="p-4 flex items-center space-x-3 border-b border-[#e2e8f0] mb-4">
                <div className="bg-[#1b5dfc] p-2 rounded-lg text-white">
                  <Package size={20} />
                </div>
                <div>
                  <h1 className="text-base font-bold text-[#0f172a]">PharmaFlow</h1>
                  <span className="text-[10px] text-gray-500">Admin Portal</span>
                </div>
              </div>
              <nav className="space-y-1">
                {menuItems.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item.path);
                  return (
                    <Link
                      key={item.name}
                      to={item.path}
                      onClick={() => setMobileMenuOpen(false)}
                      className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
                        active
                          ? 'bg-[#1b5dfc] text-white shadow-sm'
                          : 'text-gray-600 hover:bg-[#e2e8f0]'
                      }`}
                    >
                      <Icon size={18} />
                      <span>{item.name}</span>
                    </Link>
                  );
                })}
              </nav>
            </div>
            <div className="p-4 border-t border-[#e2e8f0] bg-[#eaeef6] rounded-xl">
              <div className="flex items-center space-x-3">
                <div className="w-8 h-8 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center">
                  PA
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-[#0f172a]">Admin User</h4>
                  <p className="text-[9px] text-gray-500">admin@pharmaflow.io</p>
                </div>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* MAIN CONTAINER */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* GLOBAL TOP BAR */}
        <header className="h-16 bg-white border-b border-[#e2e8f0] flex items-center justify-between px-6 shrink-0 z-10">
          {/* Search Bar */}
          <div className="flex items-center space-x-4 flex-1 max-w-md pl-12 md:pl-0">
            <div className="relative w-full">
              <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search invoices, batches, or medicines..."
                className="w-full bg-[#f4f5fa] border border-transparent rounded-full pl-10 pr-4 py-2 text-xs text-gray-700 placeholder-gray-400 focus:outline-none focus:bg-white focus:border-blue-500 transition-all duration-200"
              />
            </div>
          </div>

          {/* Right Header Controls */}
          <div className="flex items-center space-x-4">
            {/* Destructive but Outline Clear Bench action for dev verification */}
            <button
              onClick={handleClearBenchClick}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 hover:border-red-300 transition-all duration-200 cursor-pointer shrink-0 shadow-sm"
              title="Clear all locally stored invoice test runs, history, drafts, and inventory"
            >
              <Trash2 size={13} className="text-red-500" />
              <span>Clear Bench</span>
            </button>

            <button className="p-2 text-gray-500 hover:text-gray-700 hover:bg-[#f4f5fa] rounded-full transition-colors relative">
              <Bell size={18} />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-amber-500 rounded-full" />
            </button>
            <button className="p-2 text-gray-500 hover:text-gray-700 hover:bg-[#f4f5fa] rounded-full transition-colors">
              <HelpCircle size={18} />
            </button>
            
            <div className="h-8 w-px bg-[#e2e8f0] hidden sm:block" />

            {/* Profile widget */}
            <div className="hidden sm:flex items-center space-x-3 cursor-pointer p-1.5 hover:bg-[#f4f5fa] rounded-lg transition-colors" onClick={() => navigate('/settings')}>
              <div className="text-right">
                <span className="text-xs font-semibold text-[#0f172a] block leading-none">Admin User</span>
                <span className="text-[10px] text-gray-500">Pharmacy Central</span>
              </div>
              <div className="w-8 h-8 rounded-full bg-blue-100 border border-blue-200 text-blue-600 font-bold flex items-center justify-center">
                PA
              </div>
            </div>
          </div>
        </header>

        {/* MAIN ROUTE CONTENT */}
        <main className="flex-1 overflow-y-auto p-6 md:p-8 bg-[#f4f5fa] min-w-0">
          <div className="max-w-7xl mx-auto space-y-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};

export default SaaSLayout;
