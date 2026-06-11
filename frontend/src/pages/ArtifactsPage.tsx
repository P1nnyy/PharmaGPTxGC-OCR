import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useRun } from '../context/RunContext';
import { apiClient } from '../api/client';
import type { Artifact } from '../api/types';
import {
  FileCode,
  Download,
  Copy,
  FolderArchive,
  Check,
  Eye,
  Terminal,
  X,
  ClipboardCheck
} from 'lucide-react';

export const ArtifactsPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const { currentRunId } = useRun();

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [copiedStates, setCopiedStates] = useState<Record<string, 'idle' | 'path' | 'content'>>({});
  const [toastText, setToastText] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastText(msg);
    setTimeout(() => setToastText(null), 2000);
  };

  // Code preview modal state
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  const [previewContent, setPreviewContent] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);

  // Load artifacts
  useEffect(() => {
    const loadArtifacts = async () => {
      const activeId = runId || currentRunId;
      if (!activeId) return;

      try {
        setLoadError(null);
        const data = await apiClient.getArtifacts(activeId);
        setArtifacts(data);
      } catch (err) {
        console.error('Failed to load artifacts:', err);
        setLoadError(err instanceof Error ? err.message : 'Failed to load backend diagnostics.');
      }
    };
    loadArtifacts();
  }, [runId, currentRunId]);

  // Copy path helper
  const handleCopyPath = async (artifact: Artifact) => {
    try {
      await navigator.clipboard.writeText(artifact.path);
      setCopiedStates(prev => ({ ...prev, [artifact.name]: 'path' }));
      setTimeout(() => {
        setCopiedStates(prev => ({ ...prev, [artifact.name]: 'idle' }));
      }, 2000);
    } catch (err) {
      console.error('Failed to copy path:', err);
    }
  };

  // Copy backend JSON content helper
  const handleCopyJSON = async (artifact: Artifact) => {
    try {
      const activeId = runId || currentRunId;
      if (!activeId) return;
      const content = await apiClient.getArtifactContent(activeId, artifact.name);
      await navigator.clipboard.writeText(content);
      setCopiedStates(prev => ({ ...prev, [artifact.name]: 'content' }));
      setTimeout(() => {
        setCopiedStates(prev => ({ ...prev, [artifact.name]: 'idle' }));
      }, 2000);
      showToast('Artifact content copied.');
    } catch (err) {
      console.error('Failed to copy JSON:', err);
      showToast(err instanceof Error ? err.message : 'Failed to copy artifact content.');
    }
  };

  // Download handler
  const handleDownload = async (artifact: Artifact) => {
    const activeId = runId || currentRunId;
    if (!activeId) return;
    try {
      await apiClient.downloadArtifact(activeId, artifact.name);
    } catch (err) {
      console.error('Failed to download artifact:', err);
      showToast(err instanceof Error ? err.message : 'Failed to download artifact.');
    }
  };

  // Global download bundle handler
  const handleDownloadBundle = async () => {
    const activeId = runId || currentRunId;
    if (!activeId) return;
    try {
      await apiClient.downloadArtifactBundle(activeId);
    } catch (err) {
      console.error('Failed to download diagnostics bundle:', err);
      showToast(err instanceof Error ? err.message : 'Diagnostics bundle is not available.');
    }
  };

  // Preview handler
  const handleOpenPreview = async (artifact: Artifact) => {
    setPreviewArtifact(artifact);
    setPreviewLoading(true);
    const activeId = runId || currentRunId;
    if (!activeId) {
      setPreviewContent('No active run selected.');
      setPreviewLoading(false);
      return;
    }

    try {
      const content = await apiClient.getArtifactContent(activeId, artifact.name);
      setPreviewContent(content);
    } catch (err) {
      console.error('Failed to preview artifact:', err);
      setPreviewContent(err instanceof Error ? err.message : 'Failed to read backend artifact.');
    }
    setPreviewLoading(false);
  };

  return (
    <div className="space-y-6">
      {toastText && (
        <div className="fixed top-16 right-6 bg-emerald-950 text-emerald-400 border border-emerald-800 px-4 py-2 rounded text-xs font-semibold z-50 shadow-lg">
          {toastText}
        </div>
      )}
      
      {/* Title */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">Workspace Debug Artifacts</h2>
          <p className="text-gray-400 text-sm">Download intermediate JSON matrices, csv layouts, image boundaries, and the full diagnostic zip bundle.</p>
        </div>

        <button
          onClick={handleDownloadBundle}
          disabled={!(runId || currentRunId) || !artifacts.some(artifact => artifact.name === 'full_diagnostics_bundle.zip')}
          className="bg-[#2ea44f] hover:bg-[#2c974b] text-white font-medium px-4 py-2 rounded text-xs transition-colors flex items-center space-x-2 shrink-0 cursor-pointer disabled:opacity-40"
        >
          <FolderArchive size={16} />
          <span>Download Diagnostics Bundle</span>
        </button>
      </div>

      {/* Artifacts Cards Grid */}
      {loadError && (
        <div className="bg-red-950/30 border border-red-900 text-red-300 rounded-lg p-4 text-sm">
          {loadError}
        </div>
      )}
      {!loadError && artifacts.length === 0 && (
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-8 text-center text-gray-400 text-sm">
          No backend diagnostics available for this run.
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {artifacts.map(art => {
          const isCopiedPath = copiedStates[art.name] === 'path';
          const isCopiedJSON = copiedStates[art.name] === 'content';
          
          return (
            <div
              key={art.name}
              className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 flex flex-col justify-between space-y-4 hover:border-gray-500 transition-colors font-mono text-xs"
            >
              <div className="space-y-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center space-x-2 text-[#58a6ff]">
                    {art.type === 'zip' ? <FolderArchive size={20} /> : <FileCode size={20} />}
                    <span className="font-bold text-white truncate max-w-[180px]" title={art.name}>{art.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500 uppercase">{art.type}</span>
                </div>
                
                <p className="text-[10px] text-gray-500 break-all leading-normal">
                  Path: <span className="text-gray-400">{art.path}</span>
                </p>
              </div>

              <div className="space-y-3 pt-3 border-t border-[#21262d]">
                <div className="flex justify-between text-[10px] text-gray-500">
                  <span>Size: {art.size}</span>
                  <span>Created: {new Date(art.created_at).toLocaleTimeString()}</span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  
                  {art.type !== 'zip' && art.type !== 'image' ? (
                    <button
                      onClick={() => handleOpenPreview(art)}
                      className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 py-1.5 rounded border border-[#30363d] flex items-center justify-center space-x-1.5 cursor-pointer"
                    >
                      <Eye size={12} />
                      <span>View Code</span>
                    </button>
                  ) : (
                    <div className="text-gray-600 bg-gray-900 border border-gray-800 rounded py-1.5 text-center select-none font-sans text-[10px]">
                      No Preview
                    </div>
                  )}

                  <button
                    onClick={() => handleDownload(art)}
                    className="bg-[#21262d] hover:bg-[#30363d] text-gray-300 py-1.5 rounded border border-[#30363d] flex items-center justify-center space-x-1.5 cursor-pointer"
                  >
                    <Download size={12} />
                    <span>Download</span>
                  </button>

                  <button
                    onClick={() => handleCopyPath(art)}
                    className="bg-[#21262d] hover:bg-[#30363d] text-gray-400 py-1.5 rounded border border-[#30363d] flex items-center justify-center space-x-1.5 cursor-pointer"
                  >
                    {isCopiedPath ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    <span>{isCopiedPath ? 'Copied Path' : 'Copy Path'}</span>
                  </button>

                  {art.type === 'json' ? (
                    <button
                      onClick={() => handleCopyJSON(art)}
                      className="bg-[#21262d] hover:bg-[#30363d] text-gray-400 py-1.5 rounded border border-[#30363d] flex items-center justify-center space-x-1.5 cursor-pointer"
                    >
                      {isCopiedJSON ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                      <span>{isCopiedJSON ? 'Copied JSON' : 'Copy JSON'}</span>
                    </button>
                  ) : (
                    <div className="text-gray-600 bg-gray-900 border border-gray-800 rounded py-1.5 text-center select-none font-sans text-[10px]">
                      No JSON
                    </div>
                  )}

                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Code preview slide over modal */}
      {previewArtifact && (
        <div className="fixed inset-0 bg-[#0b0f17]/80 flex items-center justify-end z-50">
          <div className="bg-[#161b22] border-l border-[#30363d] w-full max-w-2xl h-screen flex flex-col justify-between shadow-2xl">
            
            {/* Header */}
            <div className="p-4 bg-[#0d1117] border-b border-[#30363d] flex items-center justify-between font-mono text-xs">
              <div className="flex items-center space-x-2 text-[#58a6ff]">
                <Terminal size={16} />
                <strong className="text-white text-sm">{previewArtifact.name}</strong>
              </div>
              <button
                onClick={() => setPreviewArtifact(null)}
                className="text-gray-400 hover:text-white p-1 cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>

            {/* Code pane */}
            <div className="flex-1 p-5 overflow-auto bg-[#0d1117] font-mono text-xs leading-relaxed select-text custom-scrollbar">
              {previewLoading ? (
                <div className="text-gray-500 py-10 text-center">Reading workspace bytes...</div>
              ) : (
                <pre className="text-emerald-400 whitespace-pre-wrap">{previewContent}</pre>
              )}
            </div>

            {/* Footer */}
            <div className="p-4 bg-[#161b22] border-t border-[#30363d] flex justify-end space-x-2 text-xs font-mono">
              <button
                onClick={async () => {
                  await navigator.clipboard.writeText(previewContent);
                  showToast('Code copied to clipboard.');
                }}
                className="bg-[#21262d] hover:bg-[#30363d] text-white px-3 py-1.5 rounded border border-[#30363d] flex items-center space-x-1.5 cursor-pointer"
              >
                <ClipboardCheck size={14} />
                <span>Copy Content</span>
              </button>
              <button
                onClick={() => void handleDownload(previewArtifact)}
                className="bg-[#2ea44f] hover:bg-[#2c974b] text-white px-3 py-1.5 rounded cursor-pointer flex items-center space-x-1.5"
              >
                <Download size={14} />
                <span>Download File</span>
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
};
