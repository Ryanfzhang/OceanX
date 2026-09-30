import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import type {TeamAgent, TeamAgentTranscript} from '../types.js';
import {AgentActivityPanel} from './AgentActivityPanel.js';

const expert: TeamAgent = {
  agent_id: 'agent-1',
  profile_id: 'ocean_process_expert',
  semantic_role: 'Ocean Process & Mechanism Expert',
  authority: 'expert',
  status: 'completed',
  activity: '## Annual Oceanographic Baseline — Gulf of Mexico\n\nCompleted the baseline.',
  agent_run_id: 'wo-1',
};

function transcriptWith(text: string): TeamAgentTranscript {
  return {
    agent_id: 'agent-1',
    agent_run_id: 'wo-1',
    messages: [
      {message_id: 'm1', role: 'coordinator', blocks: [{type: 'text', text}]},
    ],
  };
}

function renderPanel(transcript: TeamAgentTranscript, agent: TeamAgent = expert): string {
  return renderToStaticMarkup(<AgentActivityPanel
    agent={agent}
    profiles={[]}
    todos={[]}
    transcript={transcript}
    loading={false}
    error={null}
  />);
}

describe('AgentActivityPanel', () => {
  it('uses the current profile name when opening an older Expert snapshot', () => {
    const markup = renderPanel(transcriptWith('Completed.'));
    expect(markup).toContain('Ocean Expert');
    expect(markup).not.toContain('Ocean Process &amp; Mechanism Expert');
  });

  it('labels interrupted partial delivery without implying a scientific verdict', () => {
    const markup = renderPanel(transcriptWith('Partial analysis'), {
      ...expert, status: 'incomplete', activity: 'Execution interrupted; saved one result.',
    });
    expect(markup).toContain('Partial result');
    expect(markup).toContain('Execution interrupted');
    expect(markup).not.toContain('>Incomplete<');
  });

  it('keeps an evidence-limit answer completed and execution errors failed', () => {
    const completed = renderPanel(transcriptWith('No independent climatology is available.'), expert);
    expect(completed).toContain('>Completed<');
    expect(completed).not.toContain('Partial result');
    const failed = renderPanel(transcriptWith('API connection failed'), {
      ...expert, status: 'failed', activity: 'API connection failed',
    });
    expect(failed).toContain('>Failed<');
    expect(failed).toContain('API connection failed');
  });

  it('renders native task questions as ordinary messages without a second assignment schema', () => {
    const markup = renderPanel(transcriptWith('分析已完成，结论如下。'));

    expect(markup).toContain('分析已完成，结论如下。');
  });

  it('strips markdown noise from the header activity line', () => {
    const markup = renderPanel(transcriptWith('hello'));

    expect(markup).toContain('Annual Oceanographic Baseline');
    expect(markup).not.toContain('##');
  });

  it('renders saved Coordinator and Expert messages in timestamp order', () => {
    const markup = renderPanel({
      agent_id: 'agent-1',
      agent_run_id: 'wo-1',
      messages: [
        {message_id: 'late', role: 'coordinator', created_at: '2026-09-17T11:20:00Z', blocks: [{type: 'text', text: 'Later follow-up'}]},
        {message_id: 'early', role: 'expert', created_at: '2026-09-17T11:10:00Z', blocks: [{type: 'text', text: 'Earlier result'}]},
      ],
    });

    expect(markup.indexOf('Earlier result')).toBeLessThan(markup.indexOf('Later follow-up'));
  });
});
