/**
 * Camera access needs a secure context, and the failure when it is missing is
 * genuinely misleading.
 *
 * `getUserMedia` is simply absent on an insecure origin — `navigator.mediaDevices`
 * is undefined — so the natural way to write the call throws a TypeError, and
 * the natural way to handle that is to report a permissions problem. The user
 * then goes hunting through browser settings for a permission they were never
 * asked for.
 *
 * `localhost` counts as secure, so `npm run dev` on this machine works. What
 * does not work is the case that actually matters for a phone: opening the dev
 * server at `http://192.168.x.x:5173` from a handset on the same network. That
 * is the configuration this check exists to explain.
 */

export type CameraAvailability =
  | { available: true }
  | { available: false; reason: string; hint: string };

export function checkCameraAvailability(): CameraAvailability {
  if (typeof window === 'undefined') {
    return { available: false, reason: 'No browser environment.', hint: '' };
  }

  if (!window.isSecureContext) {
    return {
      available: false,
      reason: 'The camera needs a secure connection (HTTPS).',
      hint:
        `This page is on ${window.location.protocol}//${window.location.host}. ` +
        'Open it over HTTPS — on this project, https://dev.pharmagpt.co serves the ' +
        'same app through the tunnel. Typing the medicine name works either way.',
    };
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    return {
      available: false,
      reason: 'This browser cannot open a camera.',
      hint: 'Search for the medicine by name instead.',
    };
  }

  return { available: true };
}
