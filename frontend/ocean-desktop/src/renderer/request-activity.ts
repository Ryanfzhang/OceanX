import type {OceanEvent, TaskWorkflow} from './types.js';

export type ToolActivity = {
  callId: string;
  toolName: string;
  purpose: string;
  /** What the step acts on, in a few words (see stepTarget). */
  target: string;
  status: 'running' | 'completed' | 'error';
};
export type RequestActivity = {requestId: string; calls: ToolActivity[]};

/** Present existing protocol events; never copy code, tool output or raw arguments into chat. */
export function updateRequestActivity(
  previous: RequestActivity | null, event: OceanEvent, activeRequestId: string | null, text: UiText = english,
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
    target: stepTarget(payload.tool_name, input, text) || existing?.target || '',
    status: event.type === 'tool.call.started' ? 'running' : payload.is_error === true ? 'error' : 'completed',
  };
  // Keep a short trail of steps without losing another parallel tool still in flight.
  const updated = existing ? calls.map(call => call.callId === next.callId ? next : call) : [...calls, next];
  const recent = new Set(updated.slice(-6).map(call => call.callId));
  return {requestId: activeRequestId, calls: updated.filter(call => call.status === 'running' || recent.has(call.callId))};
}

type UiText = (english: string, chinese: string) => string;
type Label = readonly [english: string, chinese: string];
const english: UiText = (value) => value;

function fileName(value: unknown): string {
  return typeof value === 'string' ? value.split(/[\\/]/).filter(Boolean).at(-1) ?? '' : '';
}

function shortened(value: unknown, length: number): string {
  if (typeof value !== 'string') return '';
  const line = value.replace(/\s+/g, ' ').trim();
  return line.length > length ? `${line.slice(0, length - 1)}…` : line;
}

/** What a step acts on: a file or folder name, a pattern, a search, a script or a command's start.
 * Never code, file content or output; a file path is cut to its last part. */
export function stepTarget(toolName: string, input: Record<string, unknown>, text: UiText = english): string {
  const path = input.file_path ?? input.path;
  if (toolName === 'read_file' && typeof path === 'string') {
    const figure = /\.figures\/page-(\d+)-figure-\d+\.jpg$/.exec(path);
    if (figure) return text(`the paper's figure on page ${Number(figure[1])}`, `论文第 ${Number(figure[1])} 页的图`);
    if (/\/pdf-text\/[0-9a-f]+(\.v\d+)?\.txt$/.test(path)) return text('the text of the paper', '论文正文');
    return fileName(path);
  }
  if (['write_file', 'edit_file', 'ls'].includes(toolName)) return fileName(path);
  if (toolName === 'glob' || toolName === 'grep') return shortened(input.pattern, 48);
  if (toolName === 'execute' && typeof input.command === 'string') {
    const script = /[\w./-]+\.py\b/.exec(input.command)?.[0];
    if (script) return fileName(script);
    if (/\bpython3?\b/.test(input.command)) return text('inline Python', '一段 Python');
    return shortened(input.command.split('\n')[0], 60);
  }
  if (toolName === 'web_search') return shortened(input.query, 72);
  if (toolName === 'jina_reader') return shortened(input.url, 72);
  if (toolName === 'task') return shortened(input.description, 72);
  if (toolName === 'assign_helper') return shortened(input.task, 72);
  return '';
}

// One label per step; whether it runs, finished or failed is shown beside it, not in the words.
const INSPECTING: Label = ['Inspecting files', '查看文件'];
const STEP_LABELS: Record<string, Label> = {
  ocean_expert_run_code: ['Running analysis', '运行分析'],
  execute: ['Running a command', '运行命令'],
  web_search: ['Searching the literature', '检索文献'],
  jina_reader: ['Reading a source', '阅读资料'],
  read_file: ['Reading a file', '读取文件'],
  write_file: ['Writing a file', '写入文件'],
  edit_file: ['Editing a file', '修改文件'],
  ls: INSPECTING, glob: INSPECTING, grep: INSPECTING,
  task: ['Delegating a research question', '分派研究问题'],
  assign_helper: ['Passing part of the work to a helper', '分派给助手'],
  hand_to_research_team: ['Handing over to the research team', '交给研究团队'],
  update_research_tree: ['Updating the research tree', '更新研究树'],
  write_todos: ['Updating the plan', '更新计划'],
  ocean_resources: ['Checking the available data and tools', '查看可用的数据和工具'],
  ocean_request_paper_selection: ['Asking you to choose papers', '请你选择论文'],
};
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
  const label = STEP_LABELS[toolName];
  if (label) return text(...label);
  const name = toolName.replace(/_/g, ' ').trim();  // a tool without a label is named, not hidden
  return text(`Using ${name}`, `使用 ${name}`);
}

/** The one line for a single agent at work: its latest running step, else what the task records. */
export function currentStep(
  activity: RequestActivity | null, workflow: TaskWorkflow | null | undefined, requestId: string | null, text: UiText,
): string {
  const calls = activity && activity.requestId === requestId ? activity.calls : [];
  const running = calls.filter(call => call.status === 'running').at(-1);
  const detail = running ? running.purpose || running.target : '';
  if (running) return detail ? `${stepLabel(running.toolName, text)} · ${detail}` : stepLabel(running.toolName, text);
  if (calls.length) return text(...(calls.at(-1)!.status === 'error' ? AFTER_ERROR : REVIEWING));
  const recorded = workflow && workflow.request_id === requestId && ['planning', 'working'].includes(workflow.state)
    ? WORKFLOW_LABELS[workflow.activity] : undefined;
  return recorded ? text(...recorded) : text('Working on the request…', '正在处理请求…');
}
