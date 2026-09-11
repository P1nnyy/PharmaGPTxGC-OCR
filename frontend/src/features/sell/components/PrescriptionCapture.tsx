/**
 * Optional prescription capture.
 *
 * The capture hook only: it photographs a prescription, uploads it, and hands
 * the bill an R2 reference. It deliberately does not maintain the Schedule H1
 * register - that is a separate statutory record with its own retention rules,
 * and stubbing it here would leave something that looks like a register and
 * is not one.
 *
 * `capture="environment"` opens the rear camera directly on a phone, which is
 * the whole point at a counter; on a desktop the same input falls back to a
 * file picker, so one control covers both layouts.
 */

import React from 'react';
import { Camera, Check, Loader2, X } from 'lucide-react';

import { uploadPrescription } from '../api';

export const PrescriptionCapture: React.FC<{
  imageRef: string | null;
  onCaptured: (ref: string | null) => void;
  compact?: boolean;
}> = ({ imageRef, onCaptured, compact = false }) => {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<string | null>(null);

  // The object URL is the only copy the browser keeps; revoking it on unmount
  // keeps a shift's worth of prescription photos out of memory.
  React.useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    const localPreview = URL.createObjectURL(file);
    setPreview(localPreview);
    try {
      const { prescription_image_ref } = await uploadPrescription(file);
      onCaptured(prescription_image_ref);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not attach the prescription.');
      URL.revokeObjectURL(localPreview);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    setError(null);
    onCaptured(null);
  };

  return (
    <div className={compact ? '' : 'space-y-2'}>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) handleFile(file);
          event.target.value = '';
        }}
      />

      {/* Icon-only in the compact (mobile) form. The search field shares that
          row and is the control the counter uses on every sale, so it gets the
          width; a labelled button here squeezed it to about a third of the
          screen. The label survives as the accessible name and the tooltip. */}
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        title="Attach a photo of the prescription to this bill"
        aria-label={imageRef ? 'Prescription attached — tap to replace' : 'Attach prescription photo'}
        className={`flex items-center justify-center gap-1.5 rounded-xl font-semibold border transition-colors cursor-pointer disabled:opacity-50 ${
          compact ? 'w-14 h-14' : 'w-full px-3 py-2.5 text-xs'
        } ${
          imageRef
            ? 'bg-green-50 border-green-200 text-green-700'
            : 'bg-white border-gray-200 text-gray-600 hover:bg-slate-50'
        }`}
      >
        {busy ? (
          <Loader2 size={compact ? 20 : 14} className="animate-spin" />
        ) : imageRef ? (
          <Check size={compact ? 20 : 14} />
        ) : (
          <Camera size={compact ? 20 : 14} />
        )}
        {!compact && (imageRef ? 'Prescription attached' : 'Prescription')}
      </button>

      {preview && imageRef && (
        <div className="relative inline-block">
          <img
            src={preview}
            alt="Captured prescription"
            className="h-20 rounded-lg border border-gray-200 object-cover"
          />
          <button
            onClick={clear}
            aria-label="Remove prescription"
            className="absolute -top-1.5 -right-1.5 bg-white border border-gray-200 rounded-full p-0.5 text-gray-400 hover:text-red-500 shadow-sm cursor-pointer"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {error && <p className="text-[10px] text-red-600 leading-snug">{error}</p>}
    </div>
  );
};
