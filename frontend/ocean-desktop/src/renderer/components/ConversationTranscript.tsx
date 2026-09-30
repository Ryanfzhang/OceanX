import {useEffect, useRef, useState} from 'react';
import {BarChart3, BookOpen, ChevronDown, ChevronRight, MessageSquare, Sparkles, Timer} from 'lucide-react';

import {presentTranscript, type PresentedTranscriptGroup} from '../conversation-presentation.js';
import {agentDisplayName} from '../agent-display-name.js';
import {CompactLogMarkdown, InlineMarkdown, MessageMarkdown, referencedResultKeys, type MarkdownResultLink} from '../message-markdown.js';
import type {PendingInteraction} from '../pending-interaction.js';
import {resultsForRequest, taskResultRefKey, taskResultsForRequest} from '../types.js';
import type {DeliveryManifest, ResearchTask, TaskOutput, TaskResultRecord, TeamSnapshot, TranscriptItem} from '../types.js';
import {useUiLanguage} from '../i18n.js';
import {AgentCollaborationCanvas, timerClock} from './AgentCollaborationCanvas.js';
import {InteractionDrawer} from './InteractionDrawer.js';

function text(item: TranscriptItem): string {
  return `${item.text}${item.interrupted ? ' (interrupted)' : ''}`;
}

function plainInlineMarkdown(value: string): string {
  return value.replace(/[*_~`]/g, '').replace(/\s+/g, ' ').trim();
}

export function taskResultKeys(result: TaskResultRecord): string[] {
  const {task_id: taskId, result_id: resultId, version} = result.result_ref;
  const paddedVersion = String(version).padStart(4, '0');
  const outputPath = typeof result.content?.output_path === 'string' ? result.content.output_path : null;
  const resultKey = typeof result.content?.result_key === 'string' ? result.content.result_key : null;
  return [
    taskResultRefKey(result.result_ref),
    `${taskId}/${resultId}@v${paddedVersion}`,
    `${taskId}/${resultId}`,
    `${resultId}@v${version}`,
    `${resultId}@v${paddedVersion}`,
    resultId,
    ...(resultKey ? [resultKey] : []),
    ...(outputPath ? [outputPath] : []),
    ...(result.execution_output_names ?? []),
  ];
}

function shortExpertRole(profileId: string | null | undefined, semanticRole: string): string {
  if (profileId === 'literature_reproduction_expert') return 'Search';
  if (profileId === 'ocean_process_expert') return 'Ocean';
  if (profileId === 'statistical_inference_expert') return 'Statistics';
  if (profileId === 'scientific_discussion_partner') return 'Discussion';
  return agentDisplayName(profileId, semanticRole).replace(/\s+Expert$/i, '') || 'Expert';
}

function researchNode(value: string | null | undefined): string | null {
  return value?.match(/\bB\d+(?:\.\d+)*\b/)?.[0] ?? null;
}

/** Return stable, task-local aliases while preserving raw Agent ids as link targets. */
export function resultOwnerDisplayAliases(team: TeamSnapshot | null): Map<string, string> {
  const aliases = new Map<string, string>();
  if (!team) return aliases;

  const nodes = new Map<string, string | null>();
  for (const todo of team.todos ?? []) {
    const node = researchNode(todo.question);
    if (!node) continue;
    for (const identity of [todo.expert_key, todo.agent_run_id]) {
      if (!identity) continue;
      const previous = nodes.get(identity);
      nodes.set(identity, previous === undefined || previous === node ? node : null);
    }
  }

  const roleCounts = new Map<string, number>();
  for (const agent of team.agents) {
    if (agent.authority === 'coordinator') continue;
    const role = shortExpertRole(agent.profile_id, agent.semantic_role);
    const ordinal = (roleCounts.get(role) ?? 0) + 1;
    roleCounts.set(role, ordinal);
    const identities = [agent.agent_id, agent.expert_key, agent.agent_run_id]
      .filter((value): value is string => Boolean(value));
    const explicitNode = researchNode(agent.task_goal);
    for (const identity of identities) {
      aliases.set(identity, explicitNode ?? nodes.get(identity) ?? `${role} ${ordinal}`);
    }
  }
  return aliases;
}

function resultKeyLabels(keys: string[], ownerAliases: Map<string, string>): Record<string, string> {
  return Object.fromEntries(keys.flatMap((key) => {
    const separator = key.indexOf('/');
    if (separator < 1 || separator === key.length - 1) return [];
    const alias = ownerAliases.get(key.slice(0, separator));
    return alias ? [[key, `${alias} · ${key.slice(separator + 1)}`]] : [];
  }));
}

function timestamp(value?: string): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function clockDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return hours
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(totalMinutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function completedDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}m ${String(seconds).padStart(2, '0')}s`;
  const hours = Math.floor(totalMinutes / 60);
  return `${hours}h ${String(totalMinutes % 60).padStart(2, '0')}m`;
}

type ResearchLogEntry =
  | {kind: 'coordinator'; item: TranscriptItem; occurredAt: number; ordinal: number}
  | {kind: 'expert'; agent: TeamSnapshot['agents'][number]; title: string; occurredAt: number; ordinal: number};

function expertDisplayName(agent: TeamSnapshot['agents'][number]): string {
  return agentDisplayName(agent.profile_id, agent.semantic_role);
}

export function chronologicalResearchLog(
  process: TranscriptItem[],
  experts: Array<{agent: TeamSnapshot['agents'][number]; title: string}>,
): ResearchLogEntry[] {
  const entries: ResearchLogEntry[] = [
    ...process.map((item, ordinal) => ({
      kind: 'coordinator' as const,
      item,
      occurredAt: timestamp(item.created_at) ?? Number.MAX_SAFE_INTEGER,
      ordinal,
    })),
    ...experts.map(({agent, title}, index) => ({
      kind: 'expert' as const,
      agent,
      title,
      occurredAt: timestamp(agent.updated_at ?? agent.created_at ?? undefined) ?? Number.MAX_SAFE_INTEGER,
      ordinal: process.length + index,
    })),
  ];
  return entries.sort((left, right) => left.occurredAt - right.occurredAt || left.ordinal - right.ordinal);
}

function requestTimeBounds(group: PresentedTranscriptGroup): {startedAt: number | null; endedAt: number | null; finalAt: number | null} {
  const candidates = [...group.userItems, ...group.processItems, ...(group.finalItem ? [group.finalItem] : [])]
    .map((item) => timestamp(item.created_at))
    .filter((value): value is number => value !== null);
  const userCandidates = group.userItems
    .map((item) => timestamp(item.created_at))
    .filter((value): value is number => value !== null);
  const startedAt = userCandidates.length ? Math.min(...userCandidates) : (candidates.length ? Math.min(...candidates) : null);
  const finalAt = timestamp(group.finalItem?.created_at);
  const stoppedAt = !group.active && candidates.length ? Math.max(...candidates) : null;
  return {startedAt, endedAt: finalAt ?? stoppedAt, finalAt};
}

function RequestElapsedTime({group}: {group: PresentedTranscriptGroup}): React.JSX.Element | null {
  const {text: uiText} = useUiLanguage();
  const {startedAt, endedAt, finalAt} = requestTimeBounds(group);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!group.active || startedAt === null) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [group.active, startedAt]);

  if (startedAt === null) return null;
  const elapsed = Math.max(0, (group.active ? now : endedAt ?? startedAt) - startedAt);
  const label = group.active
    ? `${uiText('Running', '运行中')} · ${clockDuration(elapsed)}`
    : finalAt !== null
      ? `${uiText('Completed in', '完成于')} ${completedDuration(elapsed)}`
      : `${uiText('Stopped after', '停止于')} ${completedDuration(elapsed)}`;
  return <p className={`request-elapsed-time${group.active ? ' running' : ''}`}>{label}</p>;
}

function Working({
  group,
  streaming,
  team,
  hiddenProcessItemId = null,
  onOpenReport,
}: {
  group: PresentedTranscriptGroup;
  streaming: string;
  team: TeamSnapshot | null;
  hiddenProcessItemId?: string | null;
  onOpenReport: (path: string, title: string) => void;
}): React.JSX.Element | null {
  const {text: uiText} = useUiLanguage();
  const traceRef = useRef<HTMLDivElement>(null);
  const [canvasCollapsed, setCanvasCollapsed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const process = group.processItems.filter((item) =>
    (item.role === 'assistant' || item.role === 'system') && item.item_id !== hiddenProcessItemId,
  );
  const live = group.active && streaming && text(process.at(-1) ?? {item_id: '', role: 'assistant', text: ''}) !== streaming ? streaming : '';
  const matchingTeam = team && (team.request_id === group.requestId || (group.active && !team.request_id)) ? team : null;
  const reportPaths = new Set<string>();
  const expertResults = group.active ? (matchingTeam?.todos ?? []).flatMap((todo) => {
    if (!todo.report_path) return [];
    reportPaths.add(todo.report_path);
    const participant = matchingTeam?.agents.find((agent) =>
      agent.authority !== 'coordinator'
      && ((todo.expert_key && agent.expert_key === todo.expert_key)
        || (!todo.expert_key && agent.profile_id === todo.profile_id)),
    );
    const reportPreview = todo.report_title
      || (participant?.report_path === todo.report_path ? participant.report_title : null)
      || uiText('Research result', '研究结果');
    const branch = todo.question.match(/\bB\d+(?:\.\d+)*\b/)?.[0];
    const reportTitle = branch && !reportPreview.includes(branch)
      ? `${branch} · ${reportPreview}`
      : reportPreview;
    const agent: TeamSnapshot['agents'][number] = {
      ...(participant ?? {
        semantic_role: agentDisplayName(todo.profile_id, 'Expert'),
        authority: 'expert' as const,
        status: todo.state === 'result_returned' ? 'completed' as const : 'incomplete' as const,
        activity: reportTitle,
      }),
      agent_id: `report:${todo.todo_id}`,
      profile_id: todo.profile_id,
      expert_key: todo.expert_key,
      agent_run_id: todo.agent_run_id,
      task_goal: todo.question,
      report_path: todo.report_path,
      report_title: reportTitle,
      created_at: todo.created_at,
      updated_at: todo.updated_at,
    };
    return [{agent, title: reportTitle}];
  }) : [];
  if (group.active) {
    for (const agent of matchingTeam?.agents ?? []) {
      if (agent.authority === 'coordinator' || !agent.report_path || reportPaths.has(agent.report_path)) continue;
      expertResults.push({agent, title: agent.report_title || uiText('Research result', '研究结果')});
    }
  }
  const researchLog = chronologicalResearchLog(process, expertResults);
  // A native Expert can already be running while the Coordinator has no
  // durable transcript turn or returned report yet.  Keep the activity area
  // visible during that interval and project the current Team activities into
  // it instead of making the whole log disappear.
  const currentActivities = researchLog.length || live ? [] : (matchingTeam?.agents ?? [])
    .filter((agent) => !['completed', 'incomplete', 'blocked', 'failed', 'skipped'].includes(agent.status) && agent.activity.trim())
    .sort((left, right) =>
      (timestamp(left.updated_at ?? left.created_at ?? undefined) ?? Number.MAX_SAFE_INTEGER)
      - (timestamp(right.updated_at ?? right.created_at ?? undefined) ?? Number.MAX_SAFE_INTEGER),
    );
  const showResearchLog = group.active && Boolean(matchingTeam || process.length || live || expertResults.length);
  const hasLiveTrace = group.active && Boolean(researchLog.length || live || currentActivities.length);
  const timing = requestTimeBounds(group);
  useEffect(() => {
    setCanvasCollapsed(false);
  }, [group.active, group.key]);
  useEffect(() => {
    if (traceRef.current) traceRef.current.scrollTop = traceRef.current.scrollHeight;
  }, [process.length, live, expertResults.length]);
  useEffect(() => {
    if (!group.active || timing.startedAt === null) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [group.active, timing.startedAt]);
  if (!group.active && !matchingTeam) return null;
  const status = group.active ? 'working' : matchingTeam?.status ?? 'completed';
  const elapsed = timing.startedAt === null ? null : Math.max(0, (group.active ? now : timing.endedAt ?? timing.startedAt) - timing.startedAt);
  const timerLabel = group.active && elapsed !== null ? timerClock(elapsed) : null;
  return <section className={`working-stream ${group.active ? 'active' : 'completed'} status-${status}${matchingTeam ? ' has-team' : ''}${canvasCollapsed ? ' details-collapsed' : ''}${hasLiveTrace ? ' has-trace' : ''}`}>
    <header className="working-stream-header"><i /><span>{uiText('Team', '团队')}</span>{timerLabel ? <small className="working-stream-timer"><Timer size={12} />{timerLabel}</small> : null}
      {matchingTeam ? <button
        className="working-stream-toggle"
        type="button"
        aria-expanded={!canvasCollapsed}
        aria-label={canvasCollapsed ? uiText('View team', '查看团队') : uiText('Hide team', '收起团队')}
        title={canvasCollapsed ? uiText('View team', '查看团队') : uiText('Hide team', '收起团队')}
        onClick={() => setCanvasCollapsed((value) => !value)}
      >
        {canvasCollapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
      </button> : null}
    </header>
    <div className="working-stream-content">
      {matchingTeam && !canvasCollapsed ? <AgentCollaborationCanvas snapshot={matchingTeam} /> : null}
      {showResearchLog ? <section className="live-research-log" aria-label={uiText('Research activity', '研究动态')}>
        <div className="live-research-log-body" ref={traceRef} aria-live="polite">
          {researchLog.map((entry) => entry.kind === 'coordinator'
            ? <article className={`research-log-entry ${entry.item.role === 'system' ? 'system' : 'coordinator'}`} key={entry.item.item_id}>
              <strong>{entry.item.role === 'system' ? 'OceanX:' : 'Coordinator:'}</strong>
              <div className="research-log-content"><CompactLogMarkdown content={text(entry.item)} /></div>
            </article>
            : <article className="research-log-entry expert-result" key={`result:${entry.agent.agent_id}:${entry.agent.report_path}`}>
              <strong>{expertDisplayName(entry.agent)}:</strong>
              <div className="research-log-content"><button
                  className="research-report-link"
                  type="button"
                  title={entry.agent.report_path!}
                  aria-label={`${uiText('Open report', '打开正文')}: ${plainInlineMarkdown(entry.title)}`}
                  onClick={() => onOpenReport(entry.agent.report_path!, entry.title)}
                ><InlineMarkdown content={entry.title} /></button></div>
            </article>)}
          {currentActivities.map((agent) => <article className="research-log-entry agent-activity" key={`activity:${agent.agent_id}`}>
            <strong>{agent.authority === 'coordinator' ? 'Coordinator:' : `${expertDisplayName(agent)}:`}</strong>
            <div className="research-log-content"><p>{agent.activity}</p></div>
          </article>)}
          {live ? <article className="research-log-entry coordinator streaming"><strong>Coordinator:</strong><div className="research-log-content"><CompactLogMarkdown content={live} /></div></article> : null}
          {!researchLog.length && !live && !currentActivities.length
            ? <article className="research-log-entry coordinator streaming"><strong>Coordinator:</strong><div className="research-log-content"><p>{uiText('Preparing the first research update…', '正在准备第一条研究动态…')}</p></div></article>
            : null}
        </div>
      </section> : null}
    </div>
  </section>;
}

function InlinePaperSelection({
  interaction,
  summary,
  answer,
  onAnswer,
  onSubmit,
}: {
  interaction: PendingInteraction;
  summary: TranscriptItem | null;
  answer: string;
  onAnswer: (answer: string) => void;
  onSubmit: (answer?: string) => void;
}): React.JSX.Element {
  const interactionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    interactionRef.current?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }, [interaction.interactionId]);

  return <article className="message assistant coordinator-checkpoint" ref={interactionRef}>
    {summary ? <MessageMarkdown content={text(summary)} /> : null}
    <InteractionDrawer
      interaction={interaction}
      answer={answer}
      onAnswer={onAnswer}
      onSubmit={onSubmit}
    />
  </article>;
}

export function ConversationTranscript({
  loading,
  transcript,
  streaming,
  activeRequestId,
  task,
  workspacePath,
  outputs,
  manifests,
  taskResults,
  team,
  teamSnapshots = {},
  pendingInteraction = null,
  interactionAnswer = '',
  onInteractionAnswer = () => undefined,
  onInteractionSubmit = () => undefined,
  onOpenResult,
  onOpenTaskResult,
  onOpenTaskResultFile = () => undefined,
  onOpenReport = () => undefined,
}: {
  loading: boolean;
  transcript: TranscriptItem[];
  streaming: string;
  activeRequestId: string | null;
  task: ResearchTask | null;
  workspacePath: string | null;
  outputs: TaskOutput[];
  manifests: DeliveryManifest[];
  taskResults: TaskResultRecord[];
  team: TeamSnapshot | null;
  teamSnapshots?: Readonly<Record<string, TeamSnapshot>>;
  pendingInteraction?: PendingInteraction | null;
  interactionAnswer?: string;
  onInteractionAnswer?: (answer: string) => void;
  onInteractionSubmit?: (answer?: string) => void;
  onOpenResult: (output: TaskOutput) => void;
  onOpenTaskResult: (result: TaskResultRecord, featureId?: string) => void;
  onOpenTaskResultFile?: (result: TaskResultRecord, file: TaskResultRecord['files'][number]) => void;
  onOpenReport?: (path: string, title: string) => void;
}): React.JSX.Element {
  const {text: uiText} = useUiLanguage();
  if (loading) return <div className="empty-state" role="status"><p>{uiText('Loading task…', '正在加载任务…')}</p></div>;
  const groups = presentTranscript(transcript, activeRequestId);
  const hasActive = groups.some((group) => group.active);
  const taskScopedResults = taskResults
    .filter((result) => result.kind === 'interactive_view' || result.kind === 'report');
  // Older self-describing .nc files predate request ownership metadata. Keep
  // them visible after a backend restart by attaching them only to the latest
  // completed exchange instead of silently filtering every figure out.
  const legacyResultGroupKey = [...groups].reverse().find((group) => group.finalItem)?.key ?? null;
  return <>
    {groups.map((group) => {
      const historicalTeam = group.requestId ? teamSnapshots[group.requestId] : null;
      const groupTeam = historicalTeam
        ?? (team && (team.request_id === group.requestId || (group.active && !team.request_id)) ? team : null);
      const groupHasTeam = Boolean(groupTeam);
      const paperSelection = group.active && pendingInteraction?.kind === 'paper_selection'
        ? pendingInteraction
        : null;
      const checkpointSummary = paperSelection
        ? [...group.processItems].reverse().find((item) => item.role === 'assistant' && text(item).trim()) ?? null
        : null;
      const requestResults = [
        ...taskResultsForRequest(taskResults, group.requestId),
        ...(group.key === legacyResultGroupKey
          ? taskResults.filter((result) => !result.origin_request_id)
          : []),
      ];
      const directResults = requestResults
        .filter((result) => result.kind === 'interactive_view' || result.kind === 'report');
      const supplementaryNotebooks = requestResults.flatMap((result) => {
        if (result.kind !== 'file' || result.content.role !== 'supplementary_figure_notebook') return [];
        const declared = typeof result.content.file === 'string' ? result.content.file : null;
        const file = result.files.find((item) => declared && item.path === declared)
          ?? result.files.find((item) => item.path.endsWith('.ipynb'));
        return file ? [{result, file}] : [];
      });
      const skillUpdates = requestResults.filter((result) => result.content.role === 'skill_update');
      const legacyResults = directResults.length ? [] : resultsForRequest(outputs, manifests, group.requestId);
      const final = group.finalItem ? text(group.finalItem) : '';
      const referencedKeys = referencedResultKeys(final);
      const ownerAliases = resultOwnerDisplayAliases(groupTeam);
      // Result references are durable at task scope.  A follow-up report may
      // cite a view produced by an earlier request, so link resolution must
      // not be artificially restricted to the current request group.
      const taskResultLinks: MarkdownResultLink[] = taskScopedResults.map((result) => {
        const keys = taskResultKeys(result);
        return {
          keys,
          keyLabels: resultKeyLabels(keys, ownerAliases),
          label: result.title,
          summary: result.summary,
          kind: result.kind,
          features: Array.isArray(result.content.features) ? result.content.features as Array<{id: string; label: string}> : [],
          onOpen: (featureId) => onOpenTaskResult(result, featureId),
        };
      });
      const taskResultKeySet = new Set(taskResultLinks.flatMap((link) => link.keys));
      const unresolvedByAgent = new Map<string, string[]>();
      for (const key of referencedKeys) {
        if (taskResultKeySet.has(key)) continue;
        const owner = key.split('/')[0];
        if (!owner) continue;
        unresolvedByAgent.set(owner, [...(unresolvedByAgent.get(owner) ?? []), key]);
      }
      const reportFallbackLinks: MarkdownResultLink[] = (groupTeam?.agents ?? []).flatMap((agent) => {
        if (!agent.report_path) return [];
        const identities = [agent.agent_id, agent.expert_key, agent.agent_run_id]
          .filter((value): value is string => Boolean(value));
        const keys = identities.flatMap((identity) => unresolvedByAgent.get(identity) ?? []);
        if (!keys.length) return [];
        const title = agent.report_title || `${expertDisplayName(agent)} report`;
        return [{
          keys: [...new Set(keys)],
          keyLabels: resultKeyLabels(keys, ownerAliases),
          label: title,
          summary: uiText('Open the Expert report that owns this cited output.', '打开拥有该引用结果的 Expert 报告。'),
          kind: 'report' as const,
          onOpen: () => onOpenReport(agent.report_path!, title),
        }];
      });
      const resultLinks = [...taskResultLinks, ...reportFallbackLinks];
      const unreferencedResults = directResults.filter((result) =>
        !taskResultKeys(result).some((key) => referencedKeys.has(key)),
      );
      const hasRecoveredFigures = unreferencedResults.some((result) =>
        result.kind === 'interactive_view' && !result.origin_request_id,
      );
      const links = legacyResults.map(({entry, output}) => ({
        ref: entry.open_ref,
        label: entry.kind === 'interactive_view' ? `Interactive View — ${entry.title}` : `Research Report — ${entry.title}`,
        onOpen: () => onOpenResult(output),
      }));
      return <section className="conversation-exchange" key={group.key}>
        {group.userItems.map((item) => <article className="message user" key={item.item_id}><MessageMarkdown content={text(item)} /></article>)}
        {!group.active || !groupHasTeam ? <RequestElapsedTime group={group} /> : null}
        <Working
          group={group}
          streaming={streaming}
          team={groupTeam}
          hiddenProcessItemId={checkpointSummary?.item_id ?? null}
          onOpenReport={onOpenReport}
        />
        {paperSelection ? <InlinePaperSelection
          interaction={paperSelection}
          summary={checkpointSummary}
          answer={interactionAnswer}
          onAnswer={onInteractionAnswer}
          onSubmit={onInteractionSubmit}
        /> : null}
        {group.finalItem ? <article className="message assistant"><MessageMarkdown content={final} artifactLinks={links} resultLinks={resultLinks} />
          {skillUpdates.length ? <section className="skill-updates" aria-label="OceanX learned from this task">
            <header><Sparkles size={18} /><div><h3>{uiText('OceanX learned from this task', 'OceanX 从本次任务中学习了经验')}</h3><p>{uiText('Skill Curator reviewed these reusable practices after the research round ended.', 'Skill Curator 在研究回合结束后审核了这些可复用经验。')}</p></div></header>
            {skillUpdates.map((result) => <article key={taskResultRefKey(result.result_ref)}>
              <strong>{typeof result.content.skill_name === 'string' ? result.content.skill_name : result.title}</strong>
              <small>{typeof result.content.operation === 'string' && result.content.operation === 'update' ? uiText('Updated', '已更新') : uiText('Created', '已创建')} · {uiText('version', '版本')} {typeof result.content.version === 'number' ? result.content.version : 1}</small>
              <p>{result.summary}</p>
            </article>)}
          </section> : null}
          {supplementaryNotebooks.length ? <section className="supplementary-materials" aria-label={uiText('Supplementary Materials', '补充材料')}>
            <strong>{uiText('Supplementary Materials:', '补充材料：')}</strong>
            <ul>{supplementaryNotebooks.map(({result, file}) => <li key={taskResultRefKey(result.result_ref)}>
              <button className="supplementary-material-link" type="button" onClick={() => onOpenTaskResultFile(result, file)} title={uiText('Open notebook', '打开 notebook')}>
                <strong>{file.path.split(/[\\/]/).filter(Boolean).at(-1) ?? file.path}</strong>
              </button>
            </li>)}</ul>
          </section> : null}
          {unreferencedResults.length || legacyResults.length ? <details className="additional-results" open={hasRecoveredFigures}>
            <summary>{uiText('Additional Results', '其他结果')} ({unreferencedResults.length + legacyResults.length})</summary>
            <div className="message-artifact-actions">
              {unreferencedResults.map((result) => <button key={taskResultRefKey(result.result_ref)} className={`result-${result.kind}`} onClick={() => onOpenTaskResult(result)}>
                {result.kind === 'interactive_view' ? <BarChart3 size={16} /> : <BookOpen size={16} />}
                <span><strong>{result.kind === 'interactive_view' ? uiText('Interactive View', '交互视图') : uiText('Research Report', '研究报告')}</strong><small>{result.title}</small></span>
              </button>)}
              {legacyResults.map(({entry, output}) => <button key={entry.entry_id} className={`result-${entry.kind}`} onClick={() => onOpenResult(output)}>
                {entry.kind === 'interactive_view' ? <BarChart3 size={16} /> : <BookOpen size={16} />}
                <span><strong>{entry.kind === 'interactive_view' ? uiText('Interactive View', '交互视图') : uiText('Research Report', '研究报告')}</strong><small>{entry.title}</small></span>
              </button>)}
            </div>
          </details> : null}
        </article> : null}
      </section>;
    })}
    {activeRequestId && !hasActive ? <>
      <Working group={{key: activeRequestId, requestId: activeRequestId, userItems: [], processItems: [], finalItem: null, active: true}} streaming={streaming} team={team} onOpenReport={onOpenReport} />
    </> : null}
    {!task && !workspacePath ? <div className="empty-state"><MessageSquare size={34} /><p>{uiText('Open a project to begin.', '打开一个项目以开始。')}</p></div> : null}
    {!task && workspacePath ? <div className="empty-state"><MessageSquare size={34} /><p>{uiText('Create or select a research task.', '创建或选择一个研究任务。')}</p></div> : null}
  </>;
}
