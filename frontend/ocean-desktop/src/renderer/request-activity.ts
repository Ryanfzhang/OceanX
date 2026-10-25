import type {OceanEvent, TaskWorkflow} from './types.js';

export type ToolActivity = {
  callId: string;
  toolName: string;
  purpose: string;
  status: 'running' | 'completed' | 'error';
};
export type RequestActivity = {requestId: string; calls: ToolActivity[]};

/** Present existing protocol events; never copy code, tool output or raw arguments into chat. */
export function updateRequestActivity(
  previous: RequestActivity | null, event: OceanEvent, activeRequestId: string | null,
): RequestActivity | null {
  if (!activeRequestId || event.request_id !== activeRequestId
      || !['tool.call.started', 'tool.call.completed'].includes(event.type ?? '')) return previous;
  const payload = event.payload ?? {};
  if (typeof payload.tool_call_id !== 'string' || typeof payload.tool_name !== 'string') return previous;
  const calls = previous?.requestId === activeRequestId ? previous.calls : [];
  const existing = calls.find(call => call.callId === payload.tool_call_id);
  const input = payload.input && typeof payload.input === 'object' ? payload.input as Record<string, unknown> : {};
  const purpose = typeof input.purpose === 'string' ? input.purpose.replace(/\s+/g, ' ').trim().slice(0, 240) : '';
  const next: ToolActivity = {
    callId: payload.tool_call_id, toolName: payload.tool_name,
    purpose: purpose || existing?.purpose || '',
    status: event.type === 'tool.call.started' ? 'running' : payload.is_error === true ? 'error' : 'completed',
  };
  // Keep a short trail of steps without losing another parallel tool still in flight.
  const updated = existing ? calls.map(call => call.callId === next.callId ? next : call) : [...calls, next];
  const recent = new Set(updated.slice(-6).map(call => call.callId));
  return {requestId: activeRequestId, calls: updated.filter(call => call.status === 'running' || recent.has(call.callId))};
}

type UiText = (english: string, chinese: string) => string;
type Label = readonly [english: string, chinese: string];

// One label per step; whether it runs, finished or failed is shown beside it, not in the words.
const INSPECTING: Label = ['Inspecting files', '查看文件'];
const STEP_LABELS: Record<string, Label> = {
  ocean_expert_run_code: ['Running analysis', '运行分析'],
  web_search: ['Searching the literature', '检索文献'],
  jina_reader: ['Reading a source', '阅读资料'],
  read_file: ['Reading a file', '读取文件'],
  ls: INSPECTING, glob: INSPECTING, grep: INSPECTING,
  task: ['Delegating a research question', '分派研究问题'],
  hand_to_research_team: ['Handing over to the research team', '交给研究团队'],
};
const OTHER_TOOL: Label = ['Using a research tool', '使用研究工具'];
const REVIEWING: Label = ['Reviewing the result', '查看结果'];
const AFTER_ERROR: Label = ['Adjusting after a tool error', '处理工具错误'];
// What a task snapshot records, for the line after a refresh or reconnect.
const WORKFLOW_LABELS: Record<string, Label> = {
  'Expert running code': STEP_LABELS.ocean_expert_run_code!,
  'Expert interpreting the code result': REVIEWING,
  'Expert adjusting its method after a tool failure': AFTER_ERROR,
  'Searching external scientific evidence': STEP_LABELS.web_search!,
  'Reading a selected scientific source': STEP_LABELS.jina_reader!,
  'Interpreting the selected paper': STEP_LABELS.jina_reader!,
  'Preparing the final answer': ['Preparing the final answer', '整理最终答案'],
};

export function stepLabel(toolName: string, text: UiText): string {
  return text(...(STEP_LABELS[toolName] ?? OTHER_TOOL));
}

/** The one line for a single agent at work: its latest running step, else what the task records. */
export function currentStep(
  activity: RequestActivity | null, workflow: TaskWorkflow | null | undefined, requestId: string | null, text: UiText,
): string {
  const calls = activity && activity.requestId === requestId ? activity.calls : [];
  const running = calls.filter(call => call.status === 'running').at(-1);
  if (running) return running.purpose ? `${stepLabel(running.toolName, text)} · ${running.purpose}` : stepLabel(running.toolName, text);
  if (calls.length) return text(...(calls.at(-1)!.status === 'error' ? AFTER_ERROR : REVIEWING));
  const recorded = workflow && workflow.request_id === requestId && ['planning', 'working'].includes(workflow.state)
    ? WORKFLOW_LABELS[workflow.activity] : undefined;
  return recorded ? text(...recorded) : text('Working on the request…', '正在处理请求…');
}
