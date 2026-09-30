import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';

import type {TeamAgent, TeamAgentProfile, TeamSnapshot, TeamTodo} from '../types.js';
import {agentDisplayName} from '../agent-display-name.js';
import {CoordinatorRoleIcon, ExpertRoleIcon} from './AgentRoleIcons.js';

const useClientLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;

type Point = {x: number; y: number};
type PreviewAnchor = {pointerX: number; pointerY: number; left: number; top: number};
type CanvasAgent = TeamAgent & {
  displayRole: string;
  profile: TeamAgentProfile | null;
  assignmentId?: string;
  researchNodeId?: string;
  nodeLabel?: string;
};

const DEFAULT_CANVAS_WIDTH = 620;
const NODE_WIDTH = 48;
const NODE_HEIGHT = 48;
const EXPERT_ACCENTS = ['#2f80b9', '#2b9a87', '#766fc1', '#bd7b38', '#c45f64', '#587e5e'];
const PROFILE_ACCENTS: Record<string, string> = {
  literature_reproduction_expert: '#2f80b9',
  ocean_process_expert: '#147d78',
  statistical_inference_expert: '#766fc1',
  scientific_discussion_partner: '#bd7b38',
};

function safeId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, '-');
}

function cleanText(value: string | null | undefined): string {
  return (value ?? '').replace(/^[#>\s]+/, '').replace(/[`*_]/g, '').replace(/\s+/g, ' ').trim();
}

function researchNodeId(value: string | null | undefined): string | undefined {
  return value?.match(/(?<![A-Za-z0-9])(B\d+(?:\.\d+)*)(?![A-Za-z0-9])/i)?.[1]?.toUpperCase();
}

function researchParentId(value: string): string | null {
  const separator = value.lastIndexOf('.');
  return separator < 0 ? null : value.slice(0, separator);
}

function todoStatus(todo: TeamTodo, participant: TeamAgent | undefined): TeamAgent['status'] {
  if (todo.state === 'result_returned') return 'completed';
  if (todo.state === 'skipped') return 'skipped';
  if (todo.state === 'stopped') {
    return participant && ['failed', 'incomplete', 'blocked', 'skipped'].includes(participant.status)
      ? participant.status
      : 'incomplete';
  }
  if (participant && ['waiting', 'working', 'planning', 'recovering', 'discussing'].includes(participant.status)) {
    return participant.status;
  }
  return todo.state === 'working' ? 'working' : 'planning';
}

function conciseDispatchId(value: string): string {
  return value.length <= 14 ? value : `${value.slice(0, 6)}…${value.slice(-5)}`;
}

function hierarchyFor(agents: CanvasAgent[]): Map<string, string> {
  const coordinator = agents.find((item) => item.authority === 'coordinator');
  const parents = new Map<string, string>();
  if (!coordinator) return parents;
  const researchAgents = new Map(
    agents.flatMap((agent) => agent.researchNodeId ? [[agent.researchNodeId, agent] as const] : []),
  );
  for (const agent of agents) {
    if (agent.authority === 'coordinator') continue;
    let parentNode = agent.researchNodeId ? researchParentId(agent.researchNodeId) : null;
    let parent = parentNode ? researchAgents.get(parentNode) : undefined;
    while (!parent && parentNode) {
      parentNode = researchParentId(parentNode);
      parent = parentNode ? researchAgents.get(parentNode) : undefined;
    }
    parents.set(agent.agent_id, parent?.agent_id ?? coordinator.agent_id);
  }
  return parents;
}

function positionsFor(agents: CanvasAgent[], width: number): {
  positions: Map<string, Point>;
  height: number;
  width: number;
  parents: Map<string, string>;
} {
  const coordinator = agents.find((item) => item.authority === 'coordinator');
  const members = agents.filter((item) => item.authority !== 'coordinator');
  const positions = new Map<string, Point>();
  const parents = hierarchyFor(agents);
  if (!members.length) {
    if (coordinator) positions.set(coordinator.agent_id, {x: width / 2, y: 62});
    return {positions, height: 102, width, parents};
  }
  const depthById = new Map<string, number>();
  const depthOf = (agentId: string, seen = new Set<string>()): number => {
    if (depthById.has(agentId)) return depthById.get(agentId)!;
    const parent = parents.get(agentId);
    if (!parent || parent === coordinator?.agent_id || seen.has(parent)) return 1;
    seen.add(agentId);
    const depth = depthOf(parent, seen) + 1;
    depthById.set(agentId, depth);
    return depth;
  };
  const sortKey = (agent: CanvasAgent) => agent.researchNodeId
    ? agent.researchNodeId.split('.').map((part) => part.replace(/^B/, '').padStart(5, '0')).join('.')
    : `${agent.created_at ?? ''}\u0000${agent.assignmentId ?? agent.agent_id}`;
  const childrenByParent = new Map<string, CanvasAgent[]>();
  members.forEach((member) => {
    const parentId = parents.get(member.agent_id) ?? coordinator?.agent_id;
    if (!parentId) return;
    childrenByParent.set(parentId, [...(childrenByParent.get(parentId) ?? []), member]);
  });
  childrenByParent.forEach((children) => children.sort((left, right) => sortKey(left).localeCompare(sortKey(right))));

  // A tidy-tree layout: every terminal branch owns one horizontal slot and
  // every parent sits at the centre of its own descendants. This prevents a
  // parent with children from being shifted on top of an adjacent sibling.
  const leafIndexById = new Map<string, number>();
  const visited = new Set<string>();
  let leafCount = 0;
  const placeSubtree = (agent: CanvasAgent, ancestry = new Set<string>()): number => {
    const existing = leafIndexById.get(agent.agent_id);
    if (existing !== undefined) return existing;
    if (ancestry.has(agent.agent_id)) {
      const index = leafCount++;
      leafIndexById.set(agent.agent_id, index);
      return index;
    }
    visited.add(agent.agent_id);
    const nextAncestry = new Set(ancestry).add(agent.agent_id);
    const children = childrenByParent.get(agent.agent_id) ?? [];
    if (!children.length) {
      const index = leafCount++;
      leafIndexById.set(agent.agent_id, index);
      return index;
    }
    const childIndices = children.map((child) => placeSubtree(child, nextAncestry));
    const centre = (Math.min(...childIndices) + Math.max(...childIndices)) / 2;
    leafIndexById.set(agent.agent_id, centre);
    return centre;
  };
  (coordinator ? childrenByParent.get(coordinator.agent_id) ?? [] : []).forEach((root) => placeSubtree(root));
  members.filter((member) => !visited.has(member.agent_id)).sort((left, right) => sortKey(left).localeCompare(sortKey(right))).forEach((member) => placeSubtree(member));

  const horizontalInset = Math.max(22, Math.min(34, width * .045));
  const minimumLeafGap = 92;
  const contentWidth = Math.max(width, horizontalInset * 2 + NODE_WIDTH + Math.max(0, leafCount - 1) * minimumLeafGap);
  const firstX = horizontalInset + NODE_WIDTH / 2;
  const lastX = contentWidth - horizontalInset - NODE_WIDTH / 2;
  const xFor = (leafIndex: number) => leafCount <= 1
    ? contentWidth / 2
    : firstX + leafIndex * ((lastX - firstX) / (leafCount - 1));
  const firstLevelY = 154;
  const levelGap = 104;
  members.forEach((member) => positions.set(member.agent_id, {
    x: xFor(leafIndexById.get(member.agent_id) ?? 0),
    y: firstLevelY + (depthOf(member.agent_id) - 1) * levelGap,
  }));
  if (coordinator) positions.set(coordinator.agent_id, {x: contentWidth / 2, y: 58});
  const maximumDepth = Math.max(...members.map((member) => depthOf(member.agent_id)));
  return {
    positions,
    height: firstLevelY + (maximumDepth - 1) * levelGap + NODE_HEIGHT / 2 + 22,
    width: contentWidth,
    parents,
  };
}

function connectionPath(from: Point, to: Point): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const direction = dx >= 0 ? 1 : -1;
    const startX = from.x + direction * NODE_WIDTH / 2;
    const endX = to.x - direction * NODE_WIDTH / 2;
    const bend = Math.max(30, Math.abs(endX - startX) * .5);
    return `M ${startX} ${from.y} C ${startX + direction * bend} ${from.y}, ${endX - direction * bend} ${to.y}, ${endX} ${to.y}`;
  }
  const direction = dy >= 0 ? 1 : -1;
  const startY = from.y + direction * NODE_HEIGHT / 2;
  const endY = to.y - direction * NODE_HEIGHT / 2;
  const bend = Math.max(26, Math.abs(endY - startY) * .5);
  return `M ${from.x} ${startY} C ${from.x} ${startY + direction * bend}, ${to.x} ${endY - direction * bend}, ${to.x} ${endY}`;
}

function connectionStart(from: Point, to: Point): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const direction = dx >= 0 ? 1 : -1;
    return {x: from.x + direction * NODE_WIDTH / 2, y: from.y};
  }
  const direction = dy >= 0 ? 1 : -1;
  return {x: from.x, y: from.y + direction * NODE_HEIGHT / 2};
}

function connectionEnd(from: Point, to: Point): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const direction = dx >= 0 ? 1 : -1;
    return {x: to.x - direction * NODE_WIDTH / 2, y: to.y};
  }
  const direction = dy >= 0 ? 1 : -1;
  return {x: to.x, y: to.y - direction * NODE_HEIGHT / 2};
}

function statusLabel(status: TeamAgent['status']): string {
  if (status === 'incomplete') return 'Partial result';
  const phrase = status.replaceAll('_', ' ');
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

function authorityLabel(authority: TeamAgent['authority']): string {
  if (authority === 'coordinator') return 'Coordinator';
  if (authority === 'expert') return 'Expert';
  return 'Scientific discussion partner';
}

function stableAccent(agent: CanvasAgent, index: number): string {
  if (agent.authority === 'coordinator') return '#216f9f';
  if (agent.profile_id && PROFILE_ACCENTS[agent.profile_id]) return PROFILE_ACCENTS[agent.profile_id]!;
  return EXPERT_ACCENTS[Math.max(0, index - 1) % EXPERT_ACCENTS.length]!;
}

function legendLabel(agent: CanvasAgent): string {
  return agentDisplayName(agent.profile_id, agent.displayRole);
}

type NodeCopy = {
  objective: string;
  workingOn: string;
};

function assignedTodos(snapshot: TeamSnapshot, agent: CanvasAgent): TeamTodo[] {
  const todos = snapshot.todos ?? [];
  if (agent.authority === 'coordinator') return todos;
  if (agent.assignmentId) return todos.filter((todo) => todo.todo_id === agent.assignmentId);
  const exact = agent.agent_run_id ? todos.filter((todo) => todo.agent_run_id === agent.agent_run_id) : [];
  if (exact.length) return exact;
  return agent.profile_id
    ? todos.filter((todo) => todo.profile_id === agent.profile_id
      && (todo.expert_key ?? null) === (agent.expert_key ?? null))
    : [];
}

function nodeTaskSummary(snapshot: TeamSnapshot, agent: CanvasAgent): NodeCopy {
  const todos = snapshot.todos ?? [];
  if (agent.authority === 'coordinator') {
    return {
      objective: todos.length
        ? `Coordinate ${todos.length} scientific workstream${todos.length === 1 ? '' : 's'} and synthesize their evidence.`
        : 'Frame the research question and coordinate the evidence needed to answer it.',
      workingOn: cleanText(agent.activity) || 'Assessing the research request.',
    };
  }
  const assigned = assignedTodos(snapshot, agent);
  const current = assigned.find((todo) => todo.state === 'working' || todo.state === 'queued' || todo.state === 'pending')
    ?? assigned.at(-1);
  const terminalActivity: Partial<Record<TeamAgent['status'], string>> = {
    completed: 'Work complete; the result has been returned to the Coordinator.',
    incomplete: cleanText(agent.activity) || 'Only part of the work was returned; see the report for details.',
    blocked: 'Reported the material blocker to the Coordinator.',
    failed: 'The workstream stopped before returning a reliable result.',
    skipped: 'This workstream was not needed in the current research path.',
  };
  return {
    objective: cleanText(current?.question ?? agent.task_goal) || 'Awaiting a bounded scientific assignment.',
    workingOn: terminalActivity[agent.status]
      ?? (cleanText(agent.activity)
        || (agent.status === 'waiting' ? 'Waiting for the next research step.' : 'Working through the assigned evidence.')),
  };
}

export function activeRoster(snapshot: TeamSnapshot): CanvasAgent[] {
  const profiles = new Map((snapshot.role_pool ?? []).map((profile) => [profile.profile_id, profile]));
  const coordinator = snapshot.agents.find((agent) => agent.authority === 'coordinator') ?? {
    agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator' as const,
    status: 'working' as const, activity: 'Request received',
  };
  const complete: CanvasAgent[] = [{...coordinator, displayRole: 'Coordinator', profile: null}];
  const participants = snapshot.agents.filter((agent) => agent.authority !== 'coordinator');
  const participantFor = (todo: TeamTodo) => participants.find(
    (agent) => Boolean(todo.agent_run_id) && agent.agent_run_id === todo.agent_run_id,
  ) ?? participants.find(
    (agent) => Boolean(todo.expert_key) && (agent.expert_key === todo.expert_key || agent.agent_id === todo.expert_key),
  ) ?? participants.find((agent) => agent.profile_id === todo.profile_id);
  const representedParticipants = new Set<string>();
  const assignmentNodes = new Map<string, {todo: TeamTodo; participant?: TeamAgent; nodeId?: string}>();
  for (const todo of snapshot.todos ?? []) {
    const participant = participantFor(todo);
    if (participant) representedParticipants.add(participant.agent_id);
    const nodeId = researchNodeId(todo.question)
      ?? researchNodeId(todo.report_path)
      ?? researchNodeId(todo.todo_id);
    // A research-tree node owns one icon. Re-dispatching that same node updates
    // its icon; ordinary tasks remain separate by their native dispatch ID.
    const key = nodeId ? `research:${nodeId}` : `dispatch:${todo.todo_id}`;
    const previous = assignmentNodes.get(key);
    const isActive = ['pending', 'queued', 'working'].includes(todo.state);
    const previousActive = previous && ['pending', 'queued', 'working'].includes(previous.todo.state);
    if (!previous || (isActive && !previousActive) || isActive === previousActive) {
      assignmentNodes.set(key, {todo, participant, nodeId});
    }
  }
  for (const [agentId, {todo, participant, nodeId}] of assignmentNodes) {
    const profile = profiles.get(todo.profile_id) ?? null;
    const displayRole = agentDisplayName(
      todo.profile_id,
      profile?.display_name ?? participant?.semantic_role ?? authorityLabel(participant?.authority ?? 'expert'),
    );
    complete.push({
      agent_id: agentId,
      profile_id: todo.profile_id,
      expert_key: todo.expert_key ?? participant?.expert_key ?? null,
      semantic_role: displayRole,
      authority: participant?.authority ?? profile?.authority ?? 'expert',
      status: todoStatus(todo, participant),
      activity: participant && participant.agent_run_id === todo.agent_run_id
        ? participant.activity
        : todo.report_title ?? (todo.state === 'result_returned' ? 'Result returned' : todo.question),
      agent_run_id: todo.agent_run_id,
      task_goal: todo.question,
      report_path: todo.report_path,
      report_title: todo.report_title,
      created_at: todo.created_at,
      updated_at: todo.updated_at,
      displayRole,
      profile,
      assignmentId: todo.todo_id,
      researchNodeId: nodeId,
      nodeLabel: nodeId ?? conciseDispatchId(todo.todo_id),
    });
  }
  for (const agent of participants) {
    if (representedParticipants.has(agent.agent_id)) continue;
    const profile = agent.profile_id ? profiles.get(agent.profile_id) ?? null : null;
    complete.push({
      ...agent,
      displayRole: agentDisplayName(
        agent.profile_id,
        profile?.display_name ?? (agent.semantic_role || authorityLabel(agent.authority)),
      ),
      profile,
      nodeLabel: conciseDispatchId(agent.agent_id),
    });
  }
  return complete;
}

function previewAnchor(clientX: number, clientY: number): PreviewAnchor {
  const gap = 14;
  return {pointerX: clientX, pointerY: clientY, left: clientX + gap, top: clientY + gap};
}

function fittedPreviewAnchor(anchor: PreviewAnchor, width: number, height: number): Pick<PreviewAnchor, 'left' | 'top'> {
  const gap = 14;
  const padding = 12;
  if (typeof window === 'undefined') return {left: anchor.left, top: anchor.top};
  const availableRight = Math.max(padding, window.innerWidth - width - padding);
  const availableBottom = Math.max(padding, window.innerHeight - height - padding);
  const preferredLeft = anchor.pointerX + gap + width <= window.innerWidth - padding
    ? anchor.pointerX + gap
    : anchor.pointerX - width - gap;
  const preferredTop = anchor.pointerY + gap + height <= window.innerHeight - padding
    ? anchor.pointerY + gap
    : anchor.pointerY - height - gap;
  return {
    left: Math.min(Math.max(padding, preferredLeft), availableRight),
    top: Math.min(Math.max(padding, preferredTop), availableBottom),
  };
}

export function AgentCollaborationCanvas({
  snapshot,
}: {
  snapshot: TeamSnapshot;
}): React.JSX.Element {
  const canvasRef = useRef<HTMLElement>(null);
  const detailPopoverRef = useRef<HTMLElement>(null);
  const [canvasWidth, setCanvasWidth] = useState(DEFAULT_CANVAS_WIDTH);
  const [hoveredAgentId, setHoveredAgentId] = useState<string | null>(null);
  const [detailAnchor, setDetailAnchor] = useState<PreviewAnchor | null>(null);
  const normalized = snapshot;
  const roster = activeRoster(normalized);
  const {positions, height: graphHeight, width: graphWidth, parents} = positionsFor(roster, canvasWidth);
  const legendAgents = [...new Map(
    roster
      .filter((agent) => agent.authority !== 'coordinator')
      .map((agent) => [agent.profile_id ?? agent.displayRole, agent]),
  ).values()];
  const legendHeight = legendAgents.length
    ? 24 + legendAgents.length * 22
    : 0;
  const height = graphHeight + legendHeight;
  const agentById = new Map(roster.map((agent) => [agent.agent_id, agent]));
  const accentById = new Map(roster.map((agent, index) => [agent.agent_id, stableAccent(agent, index)]));
  const colorOf = (agentId: string) => accentById.get(agentId) ?? '#2f80b9';
  const edgeAccent = (fromAgentId: string, toAgentId: string) => {
    const from = agentById.get(fromAgentId);
    const memberId = from?.authority === 'coordinator' ? toAgentId : fromAgentId;
    return accentById.get(memberId) ?? '#2f80b9';
  };
  const gradientId = (kind: 'rel' | 'act', key: string) => `agent-edge-${kind}-${safeId(key)}`;
  const makeEdge = (fromAgentId: string, toAgentId: string, from: Point, to: Point) => ({
    fromAgentId,
    toAgentId,
    start: connectionStart(from, to),
    end: connectionEnd(from, to),
    path: connectionPath(from, to),
    fromColor: colorOf(fromAgentId),
    toColor: colorOf(toAgentId),
    accent: edgeAccent(fromAgentId, toAgentId),
  });
  type CanvasEdge = ReturnType<typeof makeEdge> & {key: string};
  const activePaths: CanvasEdge[] = [];
  const relationshipPaths: CanvasEdge[] = [];
  for (const agent of roster.filter((item) => item.authority !== 'coordinator')) {
    const parentId = parents.get(agent.agent_id);
    if (!parentId) continue;
    const key = `${parentId}:${agent.agent_id}`;
    const from = positions.get(parentId);
    const to = positions.get(agent.agent_id);
    if (!from || !to) continue;
    const edge = {key, ...makeEdge(parentId, agent.agent_id, from, to)};
    if (['planning', 'working', 'discussing', 'recovering'].includes(agent.status)) {
      activePaths.push(edge);
    } else {
      relationshipPaths.push(edge);
    }
  }

  useEffect(() => {
    const element = canvasRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const update = () => setCanvasWidth(Math.max(360, Math.floor(element.clientWidth)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const hoveredAgent = roster.find((agent) => agent.agent_id === hoveredAgentId) ?? null;
  const hoveredCopy = hoveredAgent ? nodeTaskSummary(snapshot, hoveredAgent) : null;
  const darkPopover = Boolean(canvasRef.current?.closest('.theme-dark'));
  useClientLayoutEffect(() => {
    const popover = detailPopoverRef.current;
    if (!popover || !detailAnchor) return;
    const bounds = popover.getBoundingClientRect();
    const fitted = fittedPreviewAnchor(detailAnchor, bounds.width, bounds.height);
    if (Math.abs(fitted.left - detailAnchor.left) < 1 && Math.abs(fitted.top - detailAnchor.top) < 1) return;
    setDetailAnchor((current) => current
      && current.pointerX === detailAnchor.pointerX
      && current.pointerY === detailAnchor.pointerY
      ? {...current, ...fitted}
      : current);
  }, [detailAnchor, hoveredAgentId, hoveredCopy?.objective, hoveredCopy?.workingOn]);
  const detailPopover = hoveredAgent && hoveredCopy && detailAnchor && typeof document !== 'undefined'
    ? createPortal(<aside
      ref={detailPopoverRef}
      className={`agent-node-popover${darkPopover ? ' theme-dark-popover' : ''}`}
      style={{left: detailAnchor.left, top: detailAnchor.top}}
      role="tooltip"
    >
      <header><strong>{hoveredAgent.displayRole}</strong>{hoveredAgent.nodeLabel ? <span>{hoveredAgent.nodeLabel}</span> : null}</header>
      <dl>
        <div><dt>Objective</dt><dd>{hoveredCopy.objective}</dd></div>
        <div><dt>Working on</dt><dd>{hoveredCopy.workingOn}</dd></div>
      </dl>
    </aside>, document.body)
    : null;

  return <section className="agent-canvas" aria-label="Active OceanX Team" ref={canvasRef}>
    <svg
      viewBox={`0 0 ${graphWidth} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="OceanX professional team collaboration topology"
      style={{width: graphWidth, minWidth: '100%'}}
    >
      <defs>
        {relationshipPaths.map((edge) => <linearGradient
          key={gradientId('rel', edge.key)}
          id={gradientId('rel', edge.key)}
          gradientUnits="userSpaceOnUse"
          x1={edge.start.x} y1={edge.start.y} x2={edge.end.x} y2={edge.end.y}
        >
          <stop offset="0%" stopColor={edge.fromColor} />
          <stop offset="100%" stopColor={edge.toColor} />
        </linearGradient>)}
        {activePaths.map((edge) => <linearGradient
          key={gradientId('act', edge.key)}
          id={gradientId('act', edge.key)}
          gradientUnits="userSpaceOnUse"
          x1={edge.start.x} y1={edge.start.y} x2={edge.end.x} y2={edge.end.y}
        >
          <stop offset="0%" stopColor={edge.fromColor} />
          <stop offset="100%" stopColor={edge.toColor} />
        </linearGradient>)}
      </defs>
      <g className="agent-edges">
        {relationshipPaths.map((edge) => <g className="agent-relationship" key={edge.key} data-from-agent={edge.fromAgentId} data-to-agent={edge.toAgentId} style={{'--agent-accent': edge.accent} as React.CSSProperties}>
          <path className="agent-edge completed" d={edge.path} stroke={`url(#${gradientId('rel', edge.key)})`} />
          <circle className="agent-edge-endpoint" cx={edge.end.x} cy={edge.end.y} r="2.6" />
        </g>)}
        {activePaths.map((edge) => <g className="agent-active-exchange" key={edge.key} data-from-agent={edge.fromAgentId} data-to-agent={edge.toAgentId} style={{'--agent-accent': edge.accent} as React.CSSProperties}>
          <path className="agent-edge active" d={edge.path} stroke={`url(#${gradientId('act', edge.key)})`} />
          <path className="agent-edge-flow" d={edge.path} pathLength={100} />
          <circle className="agent-edge-source" cx={edge.start.x} cy={edge.start.y} r="3" />
          <circle className="agent-edge-pulse" cx={edge.end.x} cy={edge.end.y} r="4" />
          <circle className="agent-edge-endpoint" cx={edge.end.x} cy={edge.end.y} r="3" />
          {['0s', '.87s', '1.73s'].map((begin) => <circle className="agent-flow-particle" r="2.4" key={`${edge.key}-${begin}`}>
            <animateMotion dur="2.6s" begin={begin} repeatCount="indefinite" path={edge.path} />
          </circle>)}
        </g>)}
      </g>
      <g className="agent-nodes">
        {roster.map((agent, index) => {
          const point = positions.get(agent.agent_id) ?? {x: graphWidth / 2, y: height / 2};
          const role = agent.displayRole;
          const task = nodeTaskSummary(snapshot, agent);
          const accent = accentById.get(agent.agent_id) ?? '#2f80b9';
          return <g
            key={agent.agent_id}
            className={`agent-node authority-${agent.authority} status-${agent.status}`}
            data-agent-id={agent.agent_id}
            data-research-node={agent.researchNodeId}
            transform={`translate(${point.x}, ${point.y})`}
            style={{animationDelay: `${index * 55}ms`, '--agent-accent': accent} as React.CSSProperties}
            tabIndex={0}
            aria-label={`${agent.nodeLabel ? `${agent.nodeLabel}. ` : ''}${role}. Objective: ${task.objective}. Working on: ${task.workingOn}.`}
            onMouseEnter={(event) => {
              setHoveredAgentId(agent.agent_id);
              setDetailAnchor(previewAnchor(event.clientX, event.clientY));
            }}
            onMouseLeave={() => {
              setHoveredAgentId((current) => current === agent.agent_id ? null : current);
              setDetailAnchor(null);
            }}
            onFocus={(event) => {
              const bounds = event.currentTarget.getBoundingClientRect();
              setHoveredAgentId(agent.agent_id);
              setDetailAnchor(previewAnchor(bounds.right, bounds.top));
            }}
            onBlur={() => {
              setHoveredAgentId((current) => current === agent.agent_id ? null : current);
              setDetailAnchor(null);
            }}
          >
            {agent.authority === 'coordinator' ? <foreignObject className="agent-node-role-object" x={-72} y={-51} width={144} height={23}>
              <div className="agent-node-role" title={role}>{role}</div>
            </foreignObject> : agent.nodeLabel ? <foreignObject className="agent-node-role-object" x={-39} y={-45} width={78} height={18}>
              <div className="agent-node-role agent-node-id" title={agent.assignmentId ?? agent.nodeLabel}>{agent.nodeLabel}</div>
            </foreignObject> : null}
            <rect className="agent-node-card" x={-NODE_WIDTH / 2} y={-NODE_HEIGHT / 2} width={NODE_WIDTH} height={NODE_HEIGHT} rx="13" />
            <foreignObject className="agent-node-copy-object" x={-NODE_WIDTH / 2} y={-NODE_HEIGHT / 2} width={NODE_WIDTH} height={NODE_HEIGHT}>
              <div className="agent-node-copy">
                {agent.authority === 'coordinator' ? <CoordinatorRoleIcon /> : <ExpertRoleIcon />}
                <em title={statusLabel(agent.status)} />
              </div>
            </foreignObject>
          </g>;
        })}
      </g>
    </svg>
    {legendAgents.length ? <aside className="agent-canvas-legend" aria-label="Expert role legend">
      {legendAgents.map((agent, index) => {
        const label = legendLabel(agent);
        return <div key={agent.profile_id ?? agent.displayRole} title={agent.displayRole}>
          <i style={{'--legend-accent': stableAccent(agent, index + 1)} as React.CSSProperties} />
          <strong>{label}</strong>
        </div>;
      })}
    </aside> : null}
    {detailPopover}
  </section>;
}

export function timerClock(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1_000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3_600);
  return hours
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function timerDuration(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1_000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}
