import {describe, expect, it} from 'vitest';
import {currentStep, stepLabel, stepTarget, updateRequestActivity, type RequestActivity} from './request-activity.js';
import type {OceanEvent} from './types.js';

const start = (id: string, purpose = 'Check the regional grid'): OceanEvent => ({
  type: 'tool.call.started', request_id: 'request-1', payload: {
    tool_call_id: id, tool_name: 'ocean_expert_run_code',
    input: {purpose, code: 'PRIVATE CODE', api_key: 'PRIVATE KEY'},
  },
});
const end = (id: string, isError = false): OceanEvent => ({
  type: 'tool.call.completed', request_id: 'request-1', payload: {
    tool_call_id: id, tool_name: 'ocean_expert_run_code', is_error: isError,
    output: 'PRIVATE OUTPUT', metadata: {traceback: 'PRIVATE TRACEBACK'},
  },
});

describe('request activity', () => {
  it('keeps a purpose through tool completion without exposing code, arguments or output', () => {
    const running = updateRequestActivity(null, start('a'), 'request-1');
    const complete = updateRequestActivity(running, end('a'), 'request-1');
    expect(complete?.calls).toEqual([{callId: 'a', toolName: 'ocean_expert_run_code', purpose: 'Check the regional grid', target: '', status: 'completed'}]);
    expect(JSON.stringify(complete)).not.toContain('PRIVATE');
  });

  it('keeps parallel work visible when another tool finishes and limits the recent trail', () => {
    let state: RequestActivity | null = updateRequestActivity(null, start('still-running'), 'request-1');
    for (let n = 0; n < 10; n++) {
      state = updateRequestActivity(state, start(String(n)), 'request-1');
      state = updateRequestActivity(state, end(String(n)), 'request-1');
    }
    expect(state?.calls.find(call => call.callId === 'still-running')?.status).toBe('running');
    expect(state?.calls.filter(call => call.status === 'completed')).toHaveLength(6);
  });

  it('isolates requests and ignores unrelated events', () => {
    const previous = updateRequestActivity(null, start('a'), 'request-1');
    expect(updateRequestActivity(previous, end('a'), 'request-2')).toBe(previous);
    expect(updateRequestActivity(previous, {type: 'assistant.delta'}, 'request-1')).toBe(previous);
    const next = updateRequestActivity(previous, {...start('b'), request_id: 'request-2'}, 'request-2');
    expect(next?.calls.map(call => call.callId)).toEqual(['b']);
  });

  it('says in one line what runs now, what follows a result or an error, and what a snapshot records', () => {
    const en = (english: string) => english;
    const zh = (_: string, chinese: string) => chinese;
    const running = updateRequestActivity(null, start('a'), 'request-1');
    expect(currentStep(running, null, 'request-1', en)).toBe('Running analysis · Check the regional grid');
    expect(currentStep(running, null, 'request-1', zh)).toBe('运行分析 · Check the regional grid');
    // Between steps the line keeps what the last step was about.
    expect(currentStep(updateRequestActivity(running, end('a'), 'request-1'), null, 'request-1', en))
      .toBe('Reviewing the result · Check the regional grid');
    expect(currentStep(updateRequestActivity(running, end('a', true), 'request-1'), null, 'request-1', zh))
      .toBe('处理工具错误 · Check the regional grid');
    const plan = updateRequestActivity(null, {type: 'tool.call.completed', request_id: 'request-1', payload: {
      tool_call_id: 'p', tool_name: 'write_todos', input: {}}}, 'request-1');
    expect(currentStep(plan, null, 'request-1', en)).toBe('Reviewing the result');  // a step with nothing to name
    const recorded = {request_id: 'request-1', state: 'working' as const, activity: 'Expert running code'};
    expect(currentStep(null, recorded, 'request-1', zh)).toBe('运行分析');
    expect(currentStep(null, {...recorded, state: 'completed'}, 'request-1', en)).toBe('Working on the request…');
    expect(stepLabel('an_unlisted_tool', en)).toBe('Using an unlisted tool');
  });

  it('names what each step acts on without code, file content or full paths', () => {
    const en = (english: string) => english;
    const zh = (_: string, chinese: string) => chinese;
    const paper = '/srv/ws/.oceanx/cache/pdf-text/31f1e3b0c1609c93.v2';
    expect(stepTarget('read_file', {file_path: `${paper}.txt`, offset: 120}, zh)).toBe('论文正文');
    expect(stepTarget('read_file', {file_path: `${paper}.figures/page-04-figure-1.jpg`}, en)).toBe("the paper's figure on page 4");
    expect(stepTarget('read_file', {file_path: '/srv/ocean-data/cmoms/u_2011.nc'}, en)).toBe('u_2011.nc');
    expect(stepTarget('write_file', {file_path: '/w/agents/a/compute_vorticity.py', content: 'PRIVATE CODE'}, en)).toBe('compute_vorticity.py');
    expect(stepTarget('execute', {command: 'cd /w && python scripts/layer_budget.py --years 2011 2022'}, en)).toBe('layer_budget.py');
    expect(stepTarget('execute', {command: "python - <<'EOF'\nPRIVATE CODE\nEOF"}, zh)).toBe('一段 Python');
    expect(stepTarget('execute', {command: 'ncdump -h u_2011.nc'}, en)).toBe('ncdump -h u_2011.nc');
    expect(stepTarget('glob', {pattern: '**/*.nc'}, en)).toBe('**/*.nc');
    expect(stepTarget('web_search', {query: 'South China Sea three-layer circulation PDO'}, en)).toBe('South China Sea three-layer circulation PDO');
    const read = updateRequestActivity(null, {type: 'tool.call.started', request_id: 'request-1', payload: {
      tool_call_id: 'r', tool_name: 'read_file', input: {file_path: `${paper}.txt`}}}, 'request-1', en);
    expect(currentStep(read, null, 'request-1', en)).toBe('Reading a file · the text of the paper');
  });
});
