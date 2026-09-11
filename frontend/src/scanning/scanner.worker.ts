/// <reference lib="webworker" />
/**
 * Barcode detection, off the main thread.
 *
 * Decoding is heavy enough to be visible: run it on the main thread and the
 * video preview stutters and the search field stops responding to typing —
 * on the one screen where typing must never stutter, because scanning is
 * optional and typing is not.
 *
 * Frames arrive as `ImageBitmap`s already cropped to the scan region by the
 * main thread, which is both cheaper to transfer and faster to decode than a
 * whole frame. They are transferred rather than copied, and closed here, so a
 * dropped frame cannot leak a bitmap per tick.
 */

import { createDetector, type DetectorHandle } from './detector';
import type { ScanFormat } from './formats';

type Incoming =
  | { type: 'init'; formats: ScanFormat[] }
  | { type: 'frame'; bitmap: ImageBitmap };

let detector: DetectorHandle | null = null;
let canvas: OffscreenCanvas | null = null;
let context: OffscreenCanvasRenderingContext2D | null = null;
let busy = false;

const post = (message: unknown) => (self as unknown as Worker).postMessage(message);

self.onmessage = async (event: MessageEvent<Incoming>) => {
  const message = event.data;

  if (message.type === 'init') {
    try {
      detector = await createDetector(message.formats);
      post({ type: 'ready', implementation: detector.implementation });
    } catch (error) {
      post({ type: 'fatal', message: error instanceof Error ? error.message : String(error) });
    }
    return;
  }

  if (message.type === 'frame') {
    const { bitmap } = message;
    // A frame arriving while the previous one is still decoding is dropped
    // rather than queued. A queue here would grow without bound the moment
    // decoding fell behind the frame rate, and every frame in it would be
    // stale by the time it was read.
    if (!detector || busy) {
      bitmap.close();
      return;
    }
    busy = true;
    try {
      if (!canvas || canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        context = canvas.getContext('2d', { willReadFrequently: true });
      }
      context?.drawImage(bitmap, 0, 0);
      bitmap.close();

      const codes = await detector.detect(canvas);
      if (codes.length > 0) {
        post({
          type: 'codes',
          codes: codes
            .filter((code) => typeof code.rawValue === 'string' && code.rawValue.length > 0)
            .map((code) => ({ rawValue: code.rawValue, format: code.format })),
        });
      }
    } catch (error) {
      // One bad frame is not a broken scanner — a half-drawn video frame
      // throws here routinely. Report it and keep going.
      post({ type: 'frame_error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      busy = false;
    }
  }
};
