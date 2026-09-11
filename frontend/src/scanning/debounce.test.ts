import { describe, expect, it } from 'vitest';

import { createReadDebouncer } from './debounce';

describe('createReadDebouncer', () => {
  it('accepts a payload the first time', () => {
    expect(createReadDebouncer().accept('ABC', 1000)).toBe(true);
  });

  it('suppresses the same payload inside the window', () => {
    // A pack held in front of the lens decodes every frame; without this one
    // pack would add eight lines a second.
    const debouncer = createReadDebouncer(2000);
    expect(debouncer.accept('ABC', 1000)).toBe(true);
    expect(debouncer.accept('ABC', 1500)).toBe(false);
    expect(debouncer.accept('ABC', 2999)).toBe(false);
  });

  it('accepts the same payload again once the window has passed', () => {
    // Scanning the same medicine twice in a row is normal at a counter.
    const debouncer = createReadDebouncer(2000);
    expect(debouncer.accept('ABC', 1000)).toBe(true);
    expect(debouncer.accept('ABC', 3000)).toBe(true);
  });

  it('never blocks a different payload', () => {
    const debouncer = createReadDebouncer(2000);
    expect(debouncer.accept('ABC', 1000)).toBe(true);
    expect(debouncer.accept('XYZ', 1001)).toBe(true);
  });

  it('forgets entries that can no longer suppress anything', () => {
    // A long shift would otherwise grow the map for every distinct pack.
    const debouncer = createReadDebouncer(2000);
    for (let i = 0; i < 500; i += 1) debouncer.accept(`code-${i}`, 1000 + i);
    debouncer.accept('later', 100_000);
    expect(debouncer.accept('code-0', 100_001)).toBe(true);
  });

  it('clears on reset', () => {
    const debouncer = createReadDebouncer(2000);
    debouncer.accept('ABC', 1000);
    debouncer.reset();
    expect(debouncer.accept('ABC', 1100)).toBe(true);
  });
});
