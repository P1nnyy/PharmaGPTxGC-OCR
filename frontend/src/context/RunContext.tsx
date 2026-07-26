import React, { createContext, useContext, useState, useEffect } from 'react';
import type { RunSummary } from '../api/types';
import { apiClient } from '../api/client';

interface WorkbenchSettings {
  showLabels: boolean;
  confidenceColors: boolean;
  diffMode: boolean;
  shadowMode: boolean;
  heuristicTsr: boolean;
  candidateComparison: boolean;
  compactMode: boolean;
  overlayOCRBlocks: boolean;
  overlayRowBoxes: boolean;
  overlayColBoundaries: boolean;
  overlaySelectedTable: boolean;
  overlayCandidateTables: boolean;
  overlayOrphans: boolean;
  overlayLowConfidence: boolean;
}

const defaultSettings: WorkbenchSettings = {
  showLabels: true,
  confidenceColors: true,
  diffMode: false,
  shadowMode: false,
  heuristicTsr: true,
  candidateComparison: false,
  compactMode: false,
  overlayOCRBlocks: true,
  overlayRowBoxes: false,
  overlayColBoundaries: true,
  overlaySelectedTable: true,
  overlayCandidateTables: false,
  overlayOrphans: true,
  overlayLowConfidence: true
};

interface RunContextType {
  runs: RunSummary[];
  currentRunId: string | null;
  setCurrentRunId: (id: string | null) => void;
  compareRunId: string | null;
  setCompareRunId: (id: string | null) => void;
  currentRun: RunSummary | null;
  compareRun: RunSummary | null;
  settings: WorkbenchSettings;
  updateSettings: (settings: Partial<WorkbenchSettings>) => void;
  isBackendActive: boolean;
  isLoading: boolean;
  error: string | null;
  
  // OCR Workbench Actions
  refreshRuns: () => Promise<void>;
  uploadInvoiceFile: (file: File) => Promise<RunSummary>;
  triggerOCR: () => Promise<void>;
  triggerReconstruction: () => Promise<void>;
  flagAnomaly: (note: string) => void;
  anomalies: Record<string, string>; // runId -> note
  clearWorkbenchState: (clearSettings?: boolean) => void;
}

const RunContext = createContext<RunContextType | undefined>(undefined);

export const RunProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [isBackendActive, setIsBackendActive] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [anomalies, setAnomalies] = useState<Record<string, string>>({});
  
  const [settings, setSettings] = useState<WorkbenchSettings>(() => {
    const saved = localStorage.getItem('ocr_workbench_settings');
    if (saved) {
      try {
        return { ...defaultSettings, ...JSON.parse(saved) };
      } catch {
        return defaultSettings;
      }
    }
    return defaultSettings;
  });

  const clearWorkbenchState = async (clearSettings = false) => {
    apiClient.clearWorkbenchRunStorage();
    try {
      await apiClient.clearBackendCache();
    } catch (e) {
      console.error('Failed to clear backend cache:', e);
    }
    if (clearSettings) {
      localStorage.removeItem('ocr_workbench_settings');
      setSettings(defaultSettings);
    }
    sessionStorage.clear();
    setRuns([]);
    setCurrentRunId(null);
    setCompareRunId(null);
  };

  // Check health and load runs on mount
  useEffect(() => {
    const init = async () => {
      setIsLoading(true);
      try {
        const health = await apiClient.checkHealth();
        setIsBackendActive(health.status === 'ok');
        
        const data = await apiClient.getRuns();
        setRuns(data);
        if (data.length > 0) {
          if (currentRunId && !data.some(r => r.run_id === currentRunId)) {
            apiClient.clearWorkbenchRunStorage();
            setCurrentRunId(null);
            setCompareRunId(null);
          } else if (!currentRunId) {
            setCurrentRunId(data[0].run_id);
          }
        } else {
          setCurrentRunId(null);
          setCompareRunId(null);
        }
      } catch (err: any) {
        setError(err.message || 'Initialization failed');
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, []);

  // Sync settings to localStorage
  useEffect(() => {
    localStorage.setItem('ocr_workbench_settings', JSON.stringify(settings));
  }, [settings]);

  const updateSettings = (newSettings: Partial<WorkbenchSettings>) => {
    setSettings(prev => ({ ...prev, ...newSettings }));
  };

  const currentRun = runs.find(r => r.run_id === currentRunId) || null;
  const compareRun = runs.find(r => r.run_id === compareRunId) || null;

  // Actions
  const refreshRuns = async () => {
    const data = await apiClient.getRuns();
    setRuns(data);
  };

  const uploadInvoiceFile = async (file: File): Promise<RunSummary> => {
    setIsLoading(true);
    try {
      const newRun = await apiClient.uploadInvoice(file);
      if (!newRun) {
        throw new Error('Upload failed or backend is offline.');
      }
      // Refresh list
      const data = await apiClient.getRuns();
      setRuns(data);
      setCurrentRunId(newRun.run_id);
      return newRun;
    } catch (err: any) {
      setError(err.message || 'Upload failed');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const triggerOCR = async () => {
    if (!currentRunId) return;
    setIsLoading(true);
    try {
      await apiClient.runOCR(currentRunId);
      // Refresh list
      const data = await apiClient.getRuns();
      setRuns(data);
    } catch (err: any) {
      const errMsg = err.message || 'OCR re-run failed';
      setError(errMsg);
      throw new Error(errMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const triggerReconstruction = async () => {
    if (!currentRunId) return;
    setIsLoading(true);
    try {
      await apiClient.rerunReconstruction(currentRunId);
      // Refresh list
      const data = await apiClient.getRuns();
      setRuns(data);
    } catch (err: any) {
      const errMsg = err.message || 'Reconstruction failed';
      setError(errMsg);
      throw new Error(errMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const flagAnomaly = (note: string) => {
    if (!currentRunId) return;
    setAnomalies(prev => ({
      ...prev,
      [currentRunId]: note
    }));
  };

  return (
    <RunContext.Provider
      value={{
        runs,
        currentRunId,
        setCurrentRunId,
        compareRunId,
        setCompareRunId,
        currentRun,
        compareRun,
        settings,
        updateSettings,
        isBackendActive,
        isLoading,
        error,
        refreshRuns,
        uploadInvoiceFile,
        triggerOCR,
        triggerReconstruction,
        flagAnomaly,
        anomalies,
        clearWorkbenchState
      }}
    >
      {children}
    </RunContext.Provider>
  );
};

export const useRun = () => {
  const context = useContext(RunContext);
  if (context === undefined) {
    throw new Error('useRun must be used within a RunProvider');
  }
  return context;
};
