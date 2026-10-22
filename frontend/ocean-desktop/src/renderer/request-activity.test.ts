import {describe, expect, it} from 'vitest';
import {toolActivityLabel, updateRequestActivity, workflowActivityLabel, type RequestActivity} from './request-activity.js';
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
    expect(complete?.calls).toEqual([{callId: 'a', toolName: 'ocean_expert_run_code', purpose: 'Check the regional grid', status: 'completed'}]);
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

  it('labels errors and restores active workflow progress in either language', () => {
    const state = updateRequestActivity(null, end('a', true), 'request-1');
    expect(toolActivityLabel(state!.calls[0]!, (en) => en)).toContain('error');
    expect(toolActivityLabel({...state!.calls[0]!, status: 'running'}, (_, zh) => zh)).toBe('正在运行分析');
    expect(workflowActivityLabel({request_id: 'request-1', state: 'working', activity: 'Expert running code'}, 'request-1', (en) => en)).toBe('Running analysis');
    expect(workflowActivityLabel({request_id: 'request-1', state: 'working', activity: 'Expert running code'}, 'request-1', (_, zh) => zh)).toBe('正在运行分析');
    expect(workflowActivityLabel({request_id: 'request-1', state: 'completed', activity: 'Expert running code'}, 'request-1', (en) => en)).toBeNull();
  });
});
