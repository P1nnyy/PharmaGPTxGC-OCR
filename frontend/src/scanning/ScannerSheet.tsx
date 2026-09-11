/**
 * The scanner, full screen.
 *
 * Everything here is arranged around one rule: scanning is a shortcut, never a
 * requirement. Every state this can end up in — permission declined, no camera,
 * insecure origin, reader failed to load — offers the same way out, which is to
 * close and type the name. None of them is presented as an error the operator
 * has to resolve before they can serve the customer standing in front of them.
 *
 * The viewfinder is drawn from the same `SCAN_REGION` the frame cropper uses,
 * so the box on screen is exactly the area being read.
 */

import React from 'react';
import { Keyboard, Loader2, ScanLine, X } from 'lucide-react';

import { SCAN_REGION } from './region';
import { useScanner } from './useScanner';
import type { ParsedDrugCode } from './parseDrugCode';

export const ScannerSheet: React.FC<{
  onRead: (parsed: ParsedDrugCode, symbology: string) => void;
  onClose: () => void;
  /** Shown under the viewfinder — what the last scan did, so the operator can
   *  keep scanning without looking away at the bill. */
  lastMessage?: string | null;
}> = ({ onRead, onClose, lastMessage }) => {
  // Destructured rather than held as one object: the hook returns a ref
  // alongside plain values, and reading `scanner.status` through it reads as a
  // ref access to both a linter and a person skimming the file.
  const { status, message, hint, videoRef, start, stop } = useScanner(onRead);

  React.useEffect(() => {
    start();
    return stop;
  }, [start, stop]);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const blocked = status === 'denied' || status === 'unavailable' || status === 'error';

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 text-white shrink-0">
        <span className="text-sm font-semibold flex items-center gap-2">
          <ScanLine size={16} /> Scan a pack
        </span>
        <button
          onClick={onClose}
          aria-label="Close scanner"
          className="p-2 -mr-2 text-white/80 hover:text-white cursor-pointer"
        >
          <X size={20} />
        </button>
      </div>

      <div className="relative flex-1 min-h-0 overflow-hidden">
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover"
          playsInline
          muted
        />

        {/* Viewfinder. The cut-out is the exact region being decoded. */}
        {!blocked && (
          <div className="absolute inset-0 pointer-events-none">
            <div
              className="absolute border-2 border-white/90 rounded-2xl shadow-[0_0_0_100vmax_rgba(0,0,0,0.55)]"
              style={{
                width: `${SCAN_REGION.widthRatio * 100}%`,
                height: `${SCAN_REGION.heightRatio * 100}%`,
                left: `${((1 - SCAN_REGION.widthRatio) / 2) * 100}%`,
                top: `${((1 - SCAN_REGION.heightRatio) / 2) * 100}%`,
              }}
            >
              <span className="absolute -top-0.5 -left-0.5 w-7 h-7 border-t-4 border-l-4 border-[#1b5dfc] rounded-tl-2xl" />
              <span className="absolute -top-0.5 -right-0.5 w-7 h-7 border-t-4 border-r-4 border-[#1b5dfc] rounded-tr-2xl" />
              <span className="absolute -bottom-0.5 -left-0.5 w-7 h-7 border-b-4 border-l-4 border-[#1b5dfc] rounded-bl-2xl" />
              <span className="absolute -bottom-0.5 -right-0.5 w-7 h-7 border-b-4 border-r-4 border-[#1b5dfc] rounded-br-2xl" />
            </div>
          </div>
        )}

        {status === 'starting' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 size={28} className="animate-spin text-white/70" />
          </div>
        )}

        {blocked && (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="bg-white rounded-2xl p-5 max-w-sm space-y-3 text-center">
              <p className="text-sm font-bold text-[#0f172a]">{message}</p>
              {hint && (
                <p className="text-xs text-gray-500 leading-normal">{hint}</p>
              )}
              <button
                onClick={onClose}
                className="w-full flex items-center justify-center gap-2 bg-[#1b5dfc] hover:bg-blue-700 text-white font-semibold px-4 py-2.5 rounded-xl text-sm cursor-pointer"
              >
                <Keyboard size={15} /> Type the name instead
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 px-4 py-4 text-center space-y-3">
        <p className="text-xs text-white/70 min-h-[1rem]">
          {lastMessage ?? (status === 'running' ? 'Hold the code inside the box.' : '')}
        </p>
        <button
          onClick={onClose}
          className="inline-flex items-center gap-2 bg-white/10 hover:bg-white/20 text-white font-semibold px-4 py-2.5 rounded-xl text-xs cursor-pointer"
        >
          <Keyboard size={14} /> Type instead
        </button>
      </div>
    </div>
  );
};
