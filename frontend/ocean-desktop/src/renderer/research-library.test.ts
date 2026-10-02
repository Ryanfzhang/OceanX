import {describe, expect, it} from 'vitest';

import {markPayload, parseLibrary, summarizeUpdate} from './research-library.js';

const lesson = {id: 'L001', skill: 'research-trajectory-planning', role: 'coordinator', status: 'active', human: 'right',
  text: 'Test a rival mechanism before deepening one.', applies_when: 'two drivers remain plausible', shown: true,
  tasks_shown: 4, tasks_cited: 1, evidence_tasks: {supporting: [{task_key: 'k1', question: 'Q1'}, {question: 'no key'}], counter: []}};
const libraryResult = {library: {
  skills: [{name: 'research-trajectory-planning', about: 'which follow-ups were worth asking', limit: 4, reader: 'coordinator',
    lessons: [lesson, {id: '../etc', text: 'not a lesson id'}]},
  {name: 'ocean-analysis-design', about: 'baselines', limit: 6, reader: 'expert', lessons: []}],
  retired: [{...lesson, id: 'L002', status: 'retired', human: 'wrong', retired_reason: 'marked wrong by the owner'},
    {...lesson, id: 'L003', status: 'retired', human: null, retired_reason: 'contradicted'}],
  tools: [{name: 'weighted_mean', signature: 'weighted_mean(array, weights, *, dims)', summary: 'Named-dimension mean.', source: 'packaged',
    status: 'listed', shown: true, human: null, stats: {tasks: 12, tasks_called: 5, calls: 9, idle: 0}},
  {name: 'anomaly', signature: 'anomaly(array, baseline, *, dim)', summary: 'Difference from a baseline.', source: 'learned', status: 'retired',
    shown: false, human: 'wrong', reason: 'marked wrong by the owner', code: 'def anomaly(): ...', test: 'assert True', stats: {}},
  {name: 'bad name'}],
  changes: [{at: '2026-10-02T01:00:00+00:00', lesson: 'L001', change: 'added', by: 'meta-agent', reason: 'seen in three tasks'}],
  tool_changes: [{at: '2026-10-02T02:00:00+00:00', tool: 'anomaly', change: 'marked wrong', by: 'desktop user'}, {at: 'x', change: 'no tool'}],
  limits: {max_words: 40, max_condition_words: 25, min_support: 3},
  version: 'lessons@abc+tools@def', digests: 12, last_reviewed_at: '2026-10-02T01:00:00+00:00',
}};

describe('research library', () => {
  it('parses lessons by skill, tools and changes defensively', () => {
    const library = parseLibrary(libraryResult)!;
    expect(library.skills.map((skill) => [skill.name, skill.limit, skill.reader, skill.lessons.length])).toEqual([
      ['research-trajectory-planning', 4, 'coordinator', 1], ['ocean-analysis-design', 6, 'expert', 0]]);
    const [kept] = library.skills[0].lessons;
    expect([kept.id, kept.active, kept.human, kept.tasksShown, kept.tasksCited]).toEqual(['L001', true, 'right', 4, 1]);
    expect(kept.evidence_tasks.supporting).toEqual([{task_key: 'k1', question: 'Q1'}]);
    // Retired lessons are listed newest first, with why they went.
    expect(library.retired.map((item) => [item.id, item.active, item.human, item.retiredReason])).toEqual([
      ['L003', false, null, 'contradicted'], ['L002', false, 'wrong', 'marked wrong by the owner']]);
    expect(library.tools.map((tool) => [tool.name, tool.learned, tool.shown, tool.tasks, tool.tasksCalled, tool.calls])).toEqual([
      ['weighted_mean', false, true, 12, 5, 9], ['anomaly', true, false, 0, 0, 0]]);
    expect(library.tools[1].code).toBe('def anomaly(): ...');
    expect(library.changes.map((change) => [change.kind, change.item, change.change])).toEqual([
      ['tool', 'anomaly', 'marked wrong'], ['lesson', 'L001', 'added']]);
    expect([library.version, library.digests, library.minSupport]).toEqual(['lessons@abc+tools@def', 12, 3]);
    expect(parseLibrary({})).toBeNull();
    expect(parseLibrary({library: {}})).toMatchObject({skills: [], tools: [], changes: [], version: null, minSupport: 3});
  });

  it('summarises what an update did', () => {
    expect(summarizeUpdate({})).toBeNull();
    expect(summarizeUpdate({update: {
      consolidation: {digested: 3}, tool_usage: {tasks_counted: 3, removed: ['small_sample']},
      lessons: {changes: [{lesson: 'L001', change: 'added'}], rejected: [{reason: 'too long'}], skills_reviewed: 6, questions: 4, new_tasks: 3},
      tools: {created: ['area_mean'], rejected: [{name: 'x', reason: 'test failed'}], candidates: 2},
    }})).toEqual({digested: 3, reviewed: true, questions: 4, lessonChanges: 1, toolsAdded: ['area_mean'], toolsRemoved: ['small_sample'], refused: 2});
    // Nothing finished since the last review: the meta-agent was not asked.
    expect(summarizeUpdate({update: {consolidation: {digested: 0}, tool_usage: {removed: []},
      lessons: {changes: [], rejected: [], skills_reviewed: 0, questions: 2, new_tasks: 0}}})).toMatchObject({reviewed: false, questions: 2, lessonChanges: 0});
  });

  it('marks one lesson or tool right or wrong', () => {
    expect(markPayload('lesson', 'L001', 'wrong')).toEqual({kind: 'lesson', id: 'L001', verdict: 'wrong'});
    expect(markPayload('tool', 'weighted_mean', 'right')).toEqual({kind: 'tool', id: 'weighted_mean', verdict: 'right'});
  });
});
