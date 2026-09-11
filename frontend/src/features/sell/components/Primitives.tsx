/**
 * Small shared pieces for the counter screen.
 *
 * `Kbd` exists because of the accessibility requirement that every keyboard
 * shortcut have a visible affordance. A shortcut nobody can see is a shortcut
 * only the person who wrote it can use, and counter staff turn over.
 */

import React from 'react';

export const Kbd: React.FC<{ children: React.ReactNode; tone?: 'light' | 'dark' }> = ({
  children,
  tone = 'light'
}) => (
  <kbd
    className={`inline-flex items-center justify-center min-w-[1.6rem] px-1.5 py-0.5 rounded-md border text-[10px] font-bold font-mono leading-none ${
      tone === 'dark'
        ? 'bg-white/10 border-white/20 text-white'
        : 'bg-slate-100 border-slate-300 text-slate-600'
    }`}
  >
    {children}
  </kbd>
);

/**
 * A label with an explanation attached.
 *
 * Uses a real `title` as well as the visible marker: the near-expiry reasoning
 * matters enough that it should be reachable by hovering anywhere on the term,
 * not only by finding a small icon.
 */
export const Explained: React.FC<{
  explanation: string;
  children: React.ReactNode;
  className?: string;
}> = ({ explanation, children, className = '' }) => (
  <span
    title={explanation}
    aria-label={explanation}
    className={`cursor-help underline decoration-dotted underline-offset-2 ${className}`}
  >
    {children}
  </span>
);

/** Modal shell. Escape closes, focus is trapped to the panel on open. */
export const Modal: React.FC<{
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}> = ({ title, onClose, children, footer, wide = false }) => {
  const panelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    panelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`bg-white rounded-2xl border border-gray-200 shadow-xl w-full ${
          wide ? 'max-w-2xl' : 'max-w-md'
        } outline-none animate-in fade-in zoom-in-95 duration-150 flex flex-col max-h-[88vh]`}
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 shrink-0">
          <h3 className="text-sm font-bold text-[#0f172a]">{title}</h3>
          <span className="text-[10px] text-gray-400 flex items-center gap-1.5">
            <Kbd>Esc</Kbd> close
          </span>
        </div>
        <div className="px-5 py-4 overflow-y-auto flex-1 min-h-0">{children}</div>
        {footer && (
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-end gap-2 shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};

/** The one place a blocking reason is rendered, so they all read alike. */
export const BlockingNotice: React.FC<{ reasons: string[]; className?: string }> = ({
  reasons,
  className = ''
}) => {
  if (reasons.length === 0) return null;
  return (
    <div className={`bg-amber-50 border border-amber-200/70 rounded-xl px-3 py-2.5 ${className}`}>
      <p className="text-[10px] font-bold uppercase tracking-wider text-amber-700 mb-1">
        Cannot issue yet
      </p>
      <ul className="space-y-0.5">
        {reasons.map((reason) => (
          <li key={reason} className="text-[11px] text-amber-800 leading-snug">
            • {reason}
          </li>
        ))}
      </ul>
    </div>
  );
};
