/**
 * How long to wait before trying a bill again.
 *
 * Exponential, jittered, and capped — but it never gives up. A bill in the
 * outbox was printed and handed to a customer; there is no attempt count at
 * which the right answer becomes "discard it". So the delay grows to a ceiling
 * and stays there, retrying quietly until the shop's line comes back, whether
 * that is in ten seconds or on Monday.
 *
 * The jitter matters more than it looks in a pharmacy chain: several counters
 * losing the same router come back at the same instant, and without jitter they
 * would retry in lockstep and hit the server as one spike every time.
 */

export const BASE_DELAY_MS = 2_000;
/** Five minutes. Long enough not to hammer a dead link, short enough that a
 *  shop which reconnects does not wait noticeably. */
export const MAX_DELAY_MS = 5 * 60_000;
/** Beyond this many failures the entry is shown as failing, so a problem that
 *  needs a person is visible rather than retried forever in silence. */
export const ATTEMPTS_BEFORE_VISIBLE_FAILURE = 3;

/** Delay before attempt number `attempts + 1`. */
export function backoffDelay(attempts: number, random: () => number = Math.random): number {
  const exponential = Math.min(BASE_DELAY_MS * 2 ** Math.max(0, attempts - 1), MAX_DELAY_MS);
  // Full jitter over the top quarter: keeps ordering roughly intact while
  // still spreading a thundering herd.
  const jitter = exponential * 0.25 * random();
  return Math.round(Math.min(exponential + jitter, MAX_DELAY_MS * 1.25));
}

export function nextAttemptAt(attempts: number, now: number = Date.now()): number {
  return now + backoffDelay(attempts);
}

/** True once an entry has failed often enough that a person should be told. */
export function isVisiblyFailing(attempts: number): boolean {
  return attempts >= ATTEMPTS_BEFORE_VISIBLE_FAILURE;
}
