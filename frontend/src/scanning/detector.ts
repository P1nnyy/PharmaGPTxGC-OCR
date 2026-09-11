/**
 * Choosing a barcode implementation.
 *
 * `BarcodeDetector` is a real web API, but it ships only in Chromium — Android
 * Chrome and Chrome/Edge on macOS. Safari does not have it, and *no* browser on
 * iOS has it, because they are all Safari underneath. Code that assumes the API
 * exists does not fail loudly there; it fails at `new BarcodeDetector(...)`
 * inside a worker, where an unhandled rejection is easy to miss entirely. Half
 * the counters this is built for run on iPhones.
 *
 * So the polyfill is the baseline, not the fallback. `barcode-detector/pure`
 * is a spec-compliant implementation over zxing-cpp compiled to WebAssembly,
 * imported from the `/pure` entry point specifically so it does *not* install
 * itself onto `globalThis` — a library quietly defining a standard global is
 * how two of them end up fighting later.
 *
 * The native path is still preferred where it exists, since it is hardware
 * accelerated and costs no download. It is taken only when it supports **every**
 * format asked for: a partial match would silently never detect DataMatrix,
 * which is exactly the symbology a Schedule H2 pack carries.
 */

// The WebAssembly module, served from our own origin.
//
// Left to itself the polyfill fetches this from a public CDN the first time
// anything is scanned. That is a hard dependency on the open internet at the
// exact moment a customer is standing at the counter, on the code path iOS has
// no alternative to — and it fails as an unexplained "reader could not start".
// Importing it through Vite's asset handling fingerprints it into our own
// build instead, so scanning works on a shop's patchy connection and stops
// depending on a third party's uptime.
//
// The version is pinned to the one `barcode-detector` was built against; a
// mismatched module and glue would fail in a far less obvious way.
import zxingWasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url';

import type { ScanFormat } from './formats';

export interface DetectorHandle {
  detect(source: CanvasImageSource | ImageBitmap | OffscreenCanvas): Promise<
    { rawValue: string; format: string }[]
  >;
  implementation: 'native' | 'polyfill';
}

interface BarcodeDetectorLike {
  detect(source: unknown): Promise<{ rawValue: string; format: string }[]>;
}

export async function createDetector(formats: readonly ScanFormat[]): Promise<DetectorHandle> {
  const Native = (globalThis as unknown as {
    BarcodeDetector?: {
      new (options: { formats: readonly string[] }): BarcodeDetectorLike;
      getSupportedFormats?: () => Promise<string[]>;
    };
  }).BarcodeDetector;

  if (Native?.getSupportedFormats) {
    try {
      const supported = await Native.getSupportedFormats();
      // Every format or none. Taking a partial match would mean DataMatrix
      // silently never resolving on a device that looked like it worked.
      if (formats.every((format) => supported.includes(format))) {
        const instance = new Native({ formats });
        return {
          detect: (source) => instance.detect(source),
          implementation: 'native',
        };
      }
    } catch {
      // A native implementation that throws while being asked what it supports
      // is not one to rely on. Fall through to the polyfill.
    }
  }

  const { BarcodeDetector, setZXingModuleOverrides } = await import('barcode-detector/pure');
  setZXingModuleOverrides({
    locateFile: (path: string, prefix: string) =>
      path.endsWith('.wasm') ? zxingWasmUrl : `${prefix}${path}`,
  });
  const instance = new BarcodeDetector({ formats: [...formats] });
  return {
    detect: (source) => instance.detect(source as never) as Promise<{ rawValue: string; format: string }[]>,
    implementation: 'polyfill',
  };
}
