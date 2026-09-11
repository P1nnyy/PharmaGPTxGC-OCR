/**
 * Camera, frame loop and worker, wired together.
 *
 * The loop runs at eight frames a second rather than on `requestAnimationFrame`.
 * Sixty decode attempts a second is not sixty times more likely to read a
 * barcode than eight — a pack is held still for the better part of a second —
 * it just drains the battery and heats the phone until the camera throttles
 * itself. Eight is comfortably faster than a human can present the next pack.
 *
 * Frames are cropped to the scan region on this side with `createImageBitmap`,
 * which does the crop in the browser's own code, then transferred to the worker
 * rather than copied.
 *
 * Every failure path here ends somewhere the counter can still bill from.
 * Scanning is a shortcut, never a requirement, so a denied permission produces
 * a sentence explaining what to do and leaves the search field focused — not a
 * blocking error.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { createReadDebouncer } from './debounce';
import { confirmRead } from './feedback';
import { SCAN_FORMATS } from './formats';
import { parseDrugCode, type ParsedDrugCode } from './parseDrugCode';
import { scanRect } from './region';
import { checkCameraAvailability } from './secureContext';

/** Eight frames a second. See the note above. */
const FRAME_INTERVAL_MS = 125;

export type ScannerStatus =
  | 'idle'
  | 'starting'
  | 'running'
  | 'denied'
  | 'unavailable'
  | 'error';

export interface ScannerState {
  status: ScannerStatus;
  /** A sentence to show the operator. Never a stack trace. */
  message: string | null;
  hint: string | null;
  implementation: 'native' | 'polyfill' | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  start: () => void;
  stop: () => void;
}

export function useScanner(onRead: (parsed: ParsedDrugCode, format: string) => void): ScannerState {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const timerRef = useRef<number | null>(null);
  const debouncer = useRef(createReadDebouncer());
  // Held in a ref so the frame loop never closes over a stale callback. Kept
  // in step from an effect rather than assigned during render, which would be
  // a write to a ref in the render phase.
  const onReadRef = useRef(onRead);
  useEffect(() => {
    onReadRef.current = onRead;
  }, [onRead]);

  const [status, setStatus] = useState<ScannerStatus>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [implementation, setImplementation] = useState<'native' | 'polyfill' | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    workerRef.current?.terminate();
    workerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    debouncer.current.reset();
    setStatus('idle');
  }, []);

  const start = useCallback(async () => {
    const availability = checkCameraAvailability();
    if (!availability.available) {
      setStatus('unavailable');
      setMessage(availability.reason);
      setHint(availability.hint);
      return;
    }

    setStatus('starting');
    setMessage(null);
    setHint(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        // The rear camera. Without this a phone opens the selfie camera, which
        // cannot be pointed at anything on the counter.
        video: { facingMode: 'environment' },
        audio: false,
      });
    } catch (error) {
      const name = (error as DOMException)?.name;
      const denied = name === 'NotAllowedError' || name === 'SecurityError';
      setStatus(denied ? 'denied' : 'error');
      setMessage(
        denied
          ? 'Camera access was declined.'
          : name === 'NotFoundError'
            ? 'No camera on this device.'
            : 'The camera could not be opened.',
      );
      setHint('Search for the medicine by name instead — billing works exactly the same.');
      return;
    }

    streamRef.current = stream;
    const video = videoRef.current;
    if (!video) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    video.srcObject = stream;
    // iOS refuses to play an inline video that is not muted, and refuses to
    // play it fullscreen-less unless playsInline is set.
    video.muted = true;
    video.playsInline = true;
    try {
      await video.play();
    } catch {
      // Autoplay rejection still leaves a usable stream in most browsers.
    }

    const worker = new Worker(new URL('./scanner.worker.ts', import.meta.url), {
      type: 'module',
    });
    workerRef.current = worker;

    worker.onmessage = (event: MessageEvent) => {
      const data = event.data;
      if (data?.type === 'ready') {
        setImplementation(data.implementation);
        setStatus('running');
        return;
      }
      if (data?.type === 'fatal') {
        setStatus('error');
        setMessage('The barcode reader could not start.');
        setHint('Search for the medicine by name instead.');
        return;
      }
      if (data?.type === 'codes') {
        for (const code of data.codes as { rawValue: string; format: string }[]) {
          if (!debouncer.current.accept(code.rawValue)) continue;
          confirmRead();
          onReadRef.current(parseDrugCode(code.rawValue), code.format);
          // One read per frame. Two barcodes in view would otherwise add two
          // lines from a single deliberate scan.
          break;
        }
      }
    };

    worker.postMessage({ type: 'init', formats: [...SCAN_FORMATS] });

    timerRef.current = window.setInterval(async () => {
      const element = videoRef.current;
      const activeWorker = workerRef.current;
      if (!element || !activeWorker) return;
      // readyState below HAVE_CURRENT_DATA means there is no frame to grab yet.
      if (element.readyState < 2 || element.videoWidth === 0) return;

      const rect = scanRect(element.videoWidth, element.videoHeight);
      try {
        const bitmap = await createImageBitmap(element, rect.x, rect.y, rect.width, rect.height);
        activeWorker.postMessage({ type: 'frame', bitmap }, [bitmap]);
      } catch {
        // A frame grabbed mid-teardown throws; the next tick will be fine.
      }
    }, FRAME_INTERVAL_MS);
  }, []);

  // Camera and worker are both expensive to leave running, and a phone will
  // keep the torch-adjacent camera indicator lit until the tracks are stopped.
  useEffect(() => stop, [stop]);

  return { status, message, hint, implementation, videoRef, start, stop };
}
