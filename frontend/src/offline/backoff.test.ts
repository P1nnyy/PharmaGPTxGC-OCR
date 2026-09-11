import { describe, expect, it } from 'vitest';

import {
  ATTEMPTS_BEFORE_VISIBLE_FAILURE,
  BASE_DELAY_MS,
  MAX_DELAY_MS,
  backoffDelay,
  isVisiblyFailing,
  nextAttemptAt,
} from './backoff';

const noJitter = () => 0;

describe('backoffDelay', () => {
  it('starts at the base delay', () => {
    expect(backoffDelay(1, noJitter)).toBe(BASE_DELAY_MS);
  });

  it('doubles with each failure', () => {
    expect(backoffDelay(2, noJitter)).toBe(BASE_DELAY_MS * 2);
    expect(backoffDelay(3, noJitter)).toBe(BASE_DELAY_MS * 4);
    expect(backoffDelay(4, noJitter)).toBe(BASE_DELAY_MS * 8);
  });

  it('stops growing at the ceiling', () => {
    // A shop closed over a long weekend must not come back to a delay measured
    // in days.
    expect(backoffDelay(50, noJitter)).toBe(MAX_DELAY_MS);
    expect(backoffDelay(1000, noJitter)).toBe(MAX_DELAY_MS);
  });

  it('never returns a negative or zero delay', () => {
    for (let attempts = 0; attempts < 20; attempts += 1) {
      expect(backoffDelay(attempts, noJitter)).toBeGreaterThan(0);
    }
  });

  it('spreads simultaneous retries with jitter', () => {
    // Several counters behind one router reconnect at the same instant; in
    // lockstep they would arrive as a spike every time.
    const low = backoffDelay(3, () => 0);
    const high = backoffDelay(3, () => 1);
    expect(high).toBeGreaterThan(low);
    expect(high).toBeLessThanOrEqual(MAX_DELAY_MS * 1.25);
  });
});

describe('nextAttemptAt', () => {
  it('is always in the future', () => {
    expect(nextAttemptAt(1, 1_000_000)).toBeGreaterThan(1_000_000);
  });
});

describe('isVisiblyFailing', () => {
  it('stays quiet for the first few attempts', () => {
    // A dropped link is normal and should not raise an alarm.
    expect(isVisiblyFailing(0)).toBe(false);
    expect(isVisiblyFailing(ATTEMPTS_BEFORE_VISIBLE_FAILURE - 1)).toBe(false);
  });

  it('surfaces a persistent failure', () => {
    // "Do not hide failures": past this, a person needs to know.
    expect(isVisiblyFailing(ATTEMPTS_BEFORE_VISIBLE_FAILURE)).toBe(true);
    expect(isVisiblyFailing(99)).toBe(true);
  });
});
