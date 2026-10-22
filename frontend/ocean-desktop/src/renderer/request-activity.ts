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
  // Keep a short progress trail without losing another parallel tool still in flight.
  const updated = existing ? calls.map(call => call.callId === next.callId ? next : call) : [...calls, next];
  const recent = new Set(updated.slice(-6).map(call => call.callId));
  return {requestId: activeRequestId, calls: updated.filter(call => call.status === 'running' || recent.has(call.callId))};
}

type UiText = (english: string, chinese: string) => string;

export function toolActivityLabel(activity: ToolActivity, text: UiText): string {
  if (activity.status === 'error') return text('Adjusting after a tool error', '正在处理工具执行错误');
  const running = activity.status === 'running';
  switch (activity.toolName) {
    case 'ocean_expert_run_code': return running ? text('Running analysis', '正在运行分析') : text('Analysis step completed', '分析步骤已完成');
    case 'web_search': return running ? text('Searching the literature', '正在检索文献') : text('Literature search completed', '文献检索已完成');
    case 'jina_reader': return running ? text('Reading a source', '正在阅读资料') : text('Source reading completed', '资料阅读已完成');
    case 'read_file': return running ? text('Reading a file', '正在读取文件') : text('File reading completed', '文件读取已完成');
    case 'ls': case 'glob': case 'grep': return running ? text('Inspecting source files', '正在检查来源文件') : text('Source inspection completed', '来源检查已完成');
    case 'task': return running ? text('Delegating a research question', '正在分派研究问题') : text('Research result returned', '研究结果已返回');
    case 'hand_to_research_team': return running ? text('Handing over to the research team', '正在交给研究团队') : text('Handed over to the research team', '已交给研究团队');
    default: return running ? text('Using a research tool', '正在使用研究工具') : text('Tool step completed', '工具步骤已完成');
  }
}

/** A task snapshot supplies a durable fallback after refresh/reconnect. */
export function workflowActivityLabel(workflow: TaskWorkflow | null | undefined, requestId: string | null, text: UiText): string | null {
  if (!workflow || workflow.request_id !== requestId || !['planning', 'working'].includes(workflow.state)) return null;
  switch (workflow.activity) {
    case 'Expert running code': return text('Running analysis', '正在运行分析');
    case 'Expert interpreting the code result': return text('Reviewing analysis results', '正在检查分析结果');
    case 'Expert adjusting its method after a tool failure': return text('Adjusting after a tool error', '正在处理工具执行错误');
    case 'Searching external scientific evidence': return text('Searching the literature', '正在检索文献');
    case 'Reading a selected scientific source': case 'Interpreting the selected paper': return text('Reading a source', '正在阅读资料');
    case 'Preparing the final answer': return text('Preparing the final answer', '正在整理最终答案');
    default: return text('Working on the request', '正在处理请求');
  }
}
