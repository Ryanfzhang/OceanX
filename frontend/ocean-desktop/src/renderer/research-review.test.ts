import {describe, expect, it} from 'vitest';

import {parseLabelCandidates, parsePolicyOverview} from './research-review.js';

describe('research review parsing', () => {
  it('keeps only valid label candidates and known labels', () => {
    const items = parseLabelCandidates({labels: [
      {node_id: 'B1.2', question: 'Q', status: 'completed', result: 'R', suggested: 'decision-changing', suggested_source: 'auto', human: null},
      {node_id: '../x', question: 'bad'},
      {node_id: 'B1.3', suggested: 'invented'},
    ]});
    expect(items.map((item) => item.node_id)).toEqual(['B1.2', 'B1.3']);
    expect(items[1].suggested).toBeNull();
  });

  it('parses the available policies', () => {
    const overview = parsePolicyOverview({policies: {active: 'v0', available: [
      {name: 'v0', version: 'policy/v0@x', description: 'baseline'}, {name: ''}]}})!;
    expect(overview.active).toBe('v0');
    expect(overview.available.map((item) => item.name)).toEqual(['v0']);
    expect(parsePolicyOverview({})).toBeNull();
  });
});
