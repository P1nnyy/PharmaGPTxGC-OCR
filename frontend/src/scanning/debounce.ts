/**
 * Suppressing repeat reads of the same code.
 *
 * A barcode sitting in front of the lens decodes on every frame, so without
 * this a single pack would add eight lines a second. Two seconds is long
 * enough that a re-read is deliberate and short enough that scanning the same
 * medicine twice in a row still works — which happens constantly at a counter.
 *
 * Keyed on the payload rather than on time alone: scanning a *different* pack
 * immediately after one is the normal rhythm of billing and must never be
 * blocked.
 */

export const REPEAT_WINDOW_MS = 2000;

export interface ReadDebouncer {
  /** True if this payload should be acted on now. */
  accept(payload: string, now?: number): boolean;
  /** Forgets everything — used when the scanner reopens. */
  reset(): void;
}

export function createReadDebouncer(windowMs: number = REPEAT_WINDOW_MS): ReadDebouncer {
  const lastSeen = new Map<string, number>();

  return {
    accept(payload: string, now: number = Date.now()): boolean {
      const previous = lastSeen.get(payload);
      if (previous !== undefined && now - previous < windowMs) return false;
      lastSeen.set(payload, now);

      // Entries older than the window can never suppress anything again, and
      // a long shift would otherwise grow this map without limit.
      for (const [key, at] of lastSeen) {
        if (now - at >= windowMs) lastSeen.delete(key);
      }
      return true;
    },
    reset() {
      lastSeen.clear();
    },
  };
}
