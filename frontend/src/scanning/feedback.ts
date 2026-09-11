/**
 * Confirming a read without the operator having to look at the screen.
 *
 * At a counter the phone is held over the pack, not in front of the face, so a
 * visual-only confirmation gets missed and the pack gets scanned twice. A short
 * buzz and a click are what tell someone the read landed.
 *
 * Both are best-effort and never throw. `navigator.vibrate` is absent on iOS
 * entirely, and audio is blocked until the page has had a user gesture — which
 * opening the scanner provides, but not always in a way we can rely on.
 */

let audioContext: AudioContext | null = null;

/** A short click. Synthesised rather than shipped as an asset — it is two
 *  oscillator settings, against a file to download, decode and cache. */
function beep(): void {
  try {
    const Context =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Context) return;

    audioContext = audioContext ?? new Context();
    // Safari suspends the context until a gesture; opening the scanner is one.
    if (audioContext.state === 'suspended') void audioContext.resume();

    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.value = 1_040;
    // A quick fade rather than a hard stop, which would click audibly.
    gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, audioContext.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.12);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.13);
  } catch {
    // Audio is a convenience. Losing it must not cost the read.
  }
}

export function confirmRead(): void {
  try {
    navigator.vibrate?.(40);
  } catch {
    // Absent on iOS, and blocked in some embedded webviews.
  }
  beep();
}

/** A different, lower pattern for "scanned, but we do not know what it is". */
export function unknownRead(): void {
  try {
    navigator.vibrate?.([25, 60, 25]);
  } catch {
    // As above.
  }
}
