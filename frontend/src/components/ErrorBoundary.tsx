import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error in Workbench:", error, errorInfo);
  }

  private handleBackToRuns = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/runs';
  };

  private handleReload = () => {
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] text-center p-6 bg-[#0d1117] text-white select-none">
          <div className="max-w-md w-full bg-[#161b22] border border-[#30363d] rounded-xl p-8 shadow-2xl space-y-6 relative overflow-hidden">
            
            {/* Elegant warning icon with subtle red glow */}
            <div className="mx-auto w-16 h-16 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-500 animate-pulse">
              <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
            </div>
            
            <div className="space-y-2">
              <h2 className="text-xl font-bold tracking-tight text-white font-mono">
                Workbench page crashed
              </h2>
              <p className="text-xs text-gray-400 font-sans">
                An unexpected rendering error occurred. Check console for details.
              </p>
            </div>

            {this.state.error && (
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-left max-h-36 overflow-y-auto custom-scrollbar font-mono text-[11px] text-rose-400/80 break-all select-text">
                {this.state.error.toString()}
              </div>
            )}

            <div className="flex items-center justify-center space-x-3 pt-2">
              <button
                onClick={this.handleBackToRuns}
                className="flex-1 bg-[#21262d] hover:bg-[#30363d] text-gray-300 hover:text-white font-medium py-2 px-4 rounded-lg text-xs border border-[#30363d] transition-all cursor-pointer flex items-center justify-center space-x-1.5"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m15 18-6-6 6-6"/>
                </svg>
                <span>Back to Runs</span>
              </button>

              <button
                onClick={this.handleReload}
                className="flex-1 bg-[#238636] hover:bg-[#2ea043] text-white font-semibold py-2 px-4 rounded-lg text-xs border border-[#30363d] transition-all cursor-pointer flex items-center justify-center space-x-1.5 shadow-md shadow-emerald-950/20"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.72 2.78L21 8"/>
                  <polyline points="21 3 21 8 16 8"/>
                </svg>
                <span>Reload Page</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
