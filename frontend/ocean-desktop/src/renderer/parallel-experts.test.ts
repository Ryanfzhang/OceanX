import {describe, expect, it} from 'vitest';

import {
  DEFAULT_PARALLEL_EXPERTS,
  PARALLEL_EXPERTS_CHOICES,
  PARALLEL_EXPERTS_STORAGE_KEY,
  readParallelExperts,
  writeParallelExperts,
} from './parallel-experts.js';

describe('parallel data Experts setting', () => {
  it('offers the values the backend accepts and defaults to two', () => {
    expect(DEFAULT_PARALLEL_EXPERTS).toBe(2);
    expect([...PARALLEL_EXPERTS_CHOICES]).toEqual([1, 2, 3, 4]);
    expect(readParallelExperts({getItem: () => null})).toBe(2);
  });

  it('reads a saved choice and falls back to the default for anything else', () => {
    for (const choice of PARALLEL_EXPERTS_CHOICES) {
      expect(readParallelExperts({getItem: () => String(choice)})).toBe(choice);
    }
    for (const stored of ['0', '5', '2.5', 'many', '', ' 3']) {
      expect(readParallelExperts({getItem: () => stored})).toBe(2);
    }
  });

  it('stores one value for the whole app, not per project or task', () => {
    const saved: Record<string, string> = {};
    const storage = {setItem: (key: string, value: string) => {saved[key] = value;}, getItem: (key: string) => saved[key] ?? null};
    writeParallelExperts(storage, 3);
    expect(saved).toEqual({[PARALLEL_EXPERTS_STORAGE_KEY]: '3'});
    expect(readParallelExperts(storage)).toBe(3);
    writeParallelExperts(storage, 9);  // not a choice: the saved value stays
    expect(readParallelExperts(storage)).toBe(3);
  });

  it('survives a storage that cannot be read', () => {
    expect(readParallelExperts({getItem: () => {throw new Error('blocked');}})).toBe(2);
  });
});
