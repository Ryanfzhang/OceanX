import {describe, expect, it} from 'vitest';

import {approvalProblem, decisionPayload, parseLessonOverview, wordCount} from './lesson-review.js';

const overviewResult = {lessons: {
  pending: [{id: 'lp_0123456789ab', kind: 'add', role: 'coordinator', text: 'Test a rival hypothesis before deepening characterisation.', applies_when: 'mechanism questions with two plausible drivers', rationale: 'seen often', created_at: '2026-09-30T00:00:00Z', evidence_tasks: {supporting: [{task_key: 'k1', question: 'Q1'}], counter: []}},
    {id: 'not-a-proposal', kind: 'add'}],
  active: [{id: 'L001', role: 'expert', text: 'Use the 0.03 kg/m3 MLD threshold.', applies_when: 'daily profiles', evidence_tasks: {supporting: [], counter: []}}],
  limits: {max_active_per_role: 1, max_words: 40, max_condition_words: 25, min_support: 3},
  lessons_version: 'lessons@abc', digests: 4, last_consolidated_at: null,
}};

describe('lesson review', () => {
  it('parses the overview defensively', () => {
    const overview = parseLessonOverview(overviewResult)!;
    expect(overview.pending.map((item) => item.id)).toEqual(['lp_0123456789ab']);
    expect(overview.active[0].role).toBe('expert');
    expect(parseLessonOverview({})).toBeNull();
  });

  it('mirrors backend limits before approval', () => {
    const overview = parseLessonOverview(overviewResult)!;
    const proposal = overview.pending[0];
    expect(approvalProblem({text: proposal.text, appliesWhen: proposal.applies_when}, proposal, overview)).toBeNull();
    expect(approvalProblem({text: 'word '.repeat(41), appliesWhen: 'x'}, proposal, overview)).toBe('text-too-long');
    expect(approvalProblem({text: 'ok', appliesWhen: ''}, proposal, overview)).toBe('empty-condition');
    expect(approvalProblem({text: 'ok', appliesWhen: 'x'}, {...proposal, role: 'expert'}, overview)).toBe('role-full');
    expect(wordCount('  two words ')).toBe(2);
  });

  it('sends only edited wording', () => {
    const proposal = parseLessonOverview(overviewResult)!.pending[0];
    expect(decisionPayload(proposal, 'approve', {text: proposal.text, appliesWhen: proposal.applies_when}, '')).toEqual({proposal_id: proposal.id, decision: 'approve'});
    expect(decisionPayload(proposal, 'approve', {text: 'Shorter lesson.', appliesWhen: proposal.applies_when}, 'tightened')).toEqual({proposal_id: proposal.id, decision: 'approve', text: 'Shorter lesson.', reason: 'tightened'});
    expect(decisionPayload(proposal, 'reject', {text: 'ignored', appliesWhen: 'ignored'}, '')).toEqual({proposal_id: proposal.id, decision: 'reject'});
  });
});
