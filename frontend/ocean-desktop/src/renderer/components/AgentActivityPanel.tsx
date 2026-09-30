import {Paperclip} from 'lucide-react';

import {MessageMarkdown} from '../message-markdown.js';
import {agentDisplayName} from '../agent-display-name.js';
import type {TeamAgent, TeamAgentProfile, TeamAgentTranscript, TeamAgentTranscriptBlock, TeamTodo} from '../types.js';

const TODO_STATE_LABELS: Record<TeamTodo['state'], string> = {
  pending: 'Waiting',
  queued: 'Queued',
  working: 'Working',
  result_returned: 'Result ready',
  stopped: 'Stopped',
  skipped: 'Skipped',
};

function displayRole(agent: TeamAgent, profiles: TeamAgentProfile[]): string {
  return agentDisplayName(
    agent.profile_id,
    profiles.find((profile) => profile.profile_id === agent.profile_id)?.display_name ?? agent.semantic_role,
  );
}

function statusLabel(status: TeamAgent['status']): string {
  if (status === 'incomplete') return 'Partial result';
  const phrase = status.replaceAll('_', ' ');
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

/** The activity feed can carry markdown headings or result excerpts; the header shows one clean line. */
function activitySummary(activity: string): string {
  return activity.replace(/^[#>\s]+/, '').replace(/[#*_`]/g, '').replace(/\s+/g, ' ').trim();
}

function todosForAgent(agent: TeamAgent, todos: TeamTodo[]): TeamTodo[] {
  if (agent.authority === 'coordinator') return todos;
  const byAgentRun = agent.agent_run_id
    ? todos.filter((todo) => todo.agent_run_id === agent.agent_run_id)
    : [];
  if (byAgentRun.length) return byAgentRun;
  return agent.profile_id
    ? todos.filter((todo) => todo.profile_id === agent.profile_id
      && (todo.expert_key ?? null) === (agent.expert_key ?? null))
    : [];
}

function speakerLabel(
  role: TeamAgentTranscript['messages'][number]['role'],
  selectedRole: string,
  coordinatorSelected: boolean,
): string {
  if (coordinatorSelected) {
    if (role === 'user') return 'You → Coordinator';
    if (role === 'coordinator') return 'Coordinator → You';
  } else {
    if (role === 'coordinator' || role === 'user') return `Coordinator → ${selectedRole}`;
    if (role === 'expert') return `${selectedRole} → Coordinator`;
  }
  if (role === 'tool') return 'Technical activity';
  return role === 'system' ? 'System' : role;
}

function timeLabel(value?: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {hour: '2-digit', minute: '2-digit'}).format(parsed);
}

type HistoryEntry =
  | {
      kind: 'message';
      key: string;
      role: TeamAgentTranscript['messages'][number]['role'];
      text: string;
      createdAt?: string;
    }
  | {
      kind: 'technical';
      key: string;
      createdAt?: string;
      blocks: Array<{key: string; block: Exclude<TeamAgentTranscriptBlock, {type: 'text'}>}>;
    };

function historyEntries(messages: TeamAgentTranscript['messages']): HistoryEntry[] {
  const entries: HistoryEntry[] = [];
  let technical: Array<{key: string; block: Exclude<TeamAgentTranscriptBlock, {type: 'text'}>}> = [];
  let technicalCreatedAt: string | undefined;
  const flushTechnical = () => {
    if (!technical.length) return;
    entries.push({
      kind: 'technical',
      key: `technical-${technical[0]!.key}`,
      createdAt: technicalCreatedAt,
      blocks: technical,
    });
    technical = [];
    technicalCreatedAt = undefined;
  };

  for (const message of messages) {
    message.blocks.forEach((block, index) => {
      const key = `${message.message_id}-${index}`;
      if (block.type !== 'text') {
        technicalCreatedAt ??= message.created_at;
        technical.push({key, block});
        return;
      }
      flushTechnical();
      if (block.text.trim()) {
        entries.push({kind: 'message', key, role: message.role, text: block.text, createdAt: message.created_at});
      }
    });
  }
  flushTechnical();
  if (!entries.every((entry) => entry.createdAt && Number.isFinite(new Date(entry.createdAt).getTime()))) {
    return entries;
  }
  return entries
    .map((entry, index) => ({entry, index}))
    .sort((left, right) => new Date(left.entry.createdAt!).getTime() - new Date(right.entry.createdAt!).getTime()
      || left.index - right.index)
    .map(({entry}) => entry);
}

export function AgentActivityPanel({
  agent,
  profiles,
  todos,
  transcript,
  loading,
  error,
}: {
  agent: TeamAgent | null;
  profiles: TeamAgentProfile[];
  todos: TeamTodo[];
  transcript: TeamAgentTranscript | null;
  loading: boolean;
  error: string | null;
}): React.JSX.Element {
  if (!agent) return <section className="agent-activity empty" aria-label="Agent activity">
    <div><small>Team activity</small><strong>Select an Expert workstream</strong></div>
    <p>Its assignment, progress, and conversation with the Coordinator will appear here.</p>
  </section>;

  const role = displayRole(agent, profiles);
  const activity = activitySummary(agent.activity);
  const selectedTodos = todosForAgent(agent, todos);
  const returned = selectedTodos.filter((todo) => todo.state === 'result_returned').length;
  const matchesSelection = transcript?.agent_id === agent.agent_id
    && (agent.authority === 'coordinator' || transcript.agent_run_id === agent.agent_run_id);
  const messages = matchesSelection ? transcript?.messages ?? [] : [];
  const entries = historyEntries(messages);
  const coordinatorSelected = agent.authority === 'coordinator';
  const conversationLabel = coordinatorSelected ? 'You ↔ Coordinator' : `Coordinator ↔ ${role}`;

  return <section className="agent-activity" aria-label={`${role} activity and conversation`}>
    <header className="agent-activity-header">
      <div>
        <small>{coordinatorSelected ? 'Team overview' : 'Selected agent'}</small>
        <strong>{role}</strong>
        {activity ? <p>{activity}</p> : null}
      </div>
      <span className={`agent-state-pill status-${agent.status}`}>{statusLabel(agent.status)}</span>
    </header>

    <section className="agent-task-strip" aria-label={`${role} assigned work`}>
      <header>
        <strong>{coordinatorSelected ? 'Research tasks' : 'Assigned work'}</strong>
        <small>{selectedTodos.length ? `${returned} of ${selectedTodos.length} results ready` : 'Planning'}</small>
      </header>
      {selectedTodos.length ? <ol>
        {selectedTodos.map((todo) => <li className={`state-${todo.state}`} key={todo.todo_id}>
          <i aria-hidden="true" />
          <span>{todo.question}</span>
          <small>{TODO_STATE_LABELS[todo.state]}</small>
        </li>)}
      </ol> : <p>{agent.task_goal ?? (coordinatorSelected
        ? 'The Coordinator is preparing the research tasks.'
        : 'No separate task has been recorded for this agent yet.')}</p>}
    </section>

    <section className="agent-activity-thread">
      <header><strong>Conversation</strong><small>{conversationLabel}</small></header>
      <div className="agent-activity-log" aria-live="polite">
        {loading ? <p className="agent-activity-state">Loading saved conversation…</p> : null}
        {error ? <p className="agent-activity-state error">{error}</p> : null}
        {!loading && !error && !entries.length ? <p className="agent-activity-state">No saved messages yet.</p> : null}
        {entries.map((entry) => {
          const timestamp = timeLabel(entry.createdAt);
          if (entry.kind === 'message') {
            return <article className={`agent-timeline-message role-${entry.role}`} key={entry.key}>
              <i aria-hidden="true" />
              <div>
                <header><small>{speakerLabel(entry.role, role, coordinatorSelected)}</small>{timestamp ? <time>{timestamp}</time> : null}</header>
                <MessageMarkdown content={entry.text} />
              </div>
            </article>;
          }
          return <details className="agent-technical-activity" key={entry.key}>
            <summary>
              <span>Technical activity</span>
              <small>{entry.blocks.length} record{entry.blocks.length === 1 ? '' : 's'}{timestamp ? ` · ${timestamp}` : ''}</small>
            </summary>
            <div className="agent-technical-records">
              {entry.blocks.map(({key, block}) => {
                if (block.type === 'tool_call') return <article className="agent-tool-record" key={key}>
                  <strong>Used {block.tool_name}</strong>
                  <pre>{JSON.stringify(block.input, null, 2)}</pre>
                </article>;
                if (block.type === 'tool_result') return <article className={`agent-tool-record${block.is_error ? ' error' : ''}`} key={key}>
                  <strong>{block.is_error ? 'Tool error' : 'Tool result'}</strong>
                  <pre>{block.text}</pre>
                </article>;
                return <p className="agent-attachment" key={key}><Paperclip size={13} />{block.source_path || block.media_type}</p>;
              })}
            </div>
          </details>;
        })}
      </div>
    </section>
  </section>;
}
