import {describe, expect, it} from 'vitest';

import {BLUE_RED, OCEAN_TEAL, resolveScientificPalette} from './scientific-palettes.js';

describe('scientific palette semantics', () => {
  it('uses Ocean teal for ordinary continuous values', () => {
    expect(resolveScientificPalette(undefined)).toEqual(OCEAN_TEAL);
    expect(resolveScientificPalette('sequential')).toEqual(OCEAN_TEAL);
  });

  it('uses the shared blue-red scale for diverging and grouped values', () => {
    expect(resolveScientificPalette('diverging')).toEqual(BLUE_RED);
    expect(resolveScientificPalette('grouped')).toEqual(BLUE_RED);
  });

  it('honours supported model choices and custom continuous stops', () => {
    expect(resolveScientificPalette('viridis')[0]).toBe('#440154');
    expect(resolveScientificPalette(['#001122', '#AABBCC'])).toEqual(['#001122', '#AABBCC']);
  });
});
