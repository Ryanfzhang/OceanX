import {describe, expect, it} from 'vitest';

import {revisionFromRequestFailure} from './request-recovery.js';

describe('request failure recovery', () => {
  it('extracts only a valid authoritative workspace conflict revision', () => {
    expect(revisionFromRequestFailure({
      code: 'workspace_revision_conflict',
      details: {current_workspace_revision: 7},
    })).toBe(7);
    expect(revisionFromRequestFailure({
      code: 'model_error',
      details: {current_workspace_revision: 8},
    })).toBeNull();
    expect(revisionFromRequestFailure({
      code: 'workspace_revision_conflict',
      details: {current_workspace_revision: -1},
    })).toBeNull();
  });
});
