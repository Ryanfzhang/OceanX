import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import type {ArtifactVersion, DeliveryManifest, ResultDocument, TaskOutput, TaskResultRecord, TeamAgentTranscript, TeamSnapshot} from '../types.js';
import {AgentActivityPanel} from './AgentActivityPanel.js';
import {activeRoster, AgentCollaborationCanvas} from './AgentCollaborationCanvas.js';
import {ConversationTranscript} from './ConversationTranscript.js';
import {InteractiveViewWorkbench} from './InteractiveViewWorkbench.js';
import {normalizeScientificFigure} from './scientific-figure.js';
import {clampScientificDomain, scientificAxisExtent, scientificScatterAppearance} from './ScientificView.js';
import {boundsForContext, displayContextFor, mapFitPadding, ResultWorkbench, sampleSpatialGrid, shouldFitRegion, spatialRasterDimensions, usableMapViewport} from './SpatialWorkbench.js';

describe('research workbench layout', () => {
  it('keeps sparse scientific scatter points legible without saturating dense clouds', () => {
    expect(scientificScatterAppearance({radius: 1.2, opacity: .25}, 8)).toEqual({radius: 3.4, opacity: .84});
    expect(scientificScatterAppearance({radius: 1.2, opacity: .25}, 5_000)).toEqual({radius: 1.2, opacity: .25});
  });

  it('keeps same-capability native Expert threads as separate participants', () => {
    const snapshot: TeamSnapshot = {
      revision: 1,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'},
        {agent_id: 'thread-horizontal', profile_id: 'ocean_process_expert', semantic_role: 'Ocean Process Expert', authority: 'expert', status: 'working', activity: 'Horizontal structure', agent_run_id: 'run-horizontal'},
        {agent_id: 'thread-vertical', profile_id: 'ocean_process_expert', semantic_role: 'Ocean Process Expert', authority: 'expert', status: 'working', activity: 'Vertical structure', agent_run_id: 'run-vertical'},
      ],
      dependencies: [],
      interactions: [],
      todos: [],
      role_pool: [],
    };

    expect(activeRoster(snapshot).map((agent) => agent.agent_id)).toEqual([
      'coordinator', 'thread-horizontal', 'thread-vertical',
    ]);
    expect(activeRoster(snapshot).map((agent) => agent.displayRole)).toEqual([
      'Coordinator', 'Ocean Expert', 'Ocean Expert',
    ]);
  });

  it('repairs old short profile scatters into a continuous sampled curve', () => {
    const normalized = normalizeScientificFigure({
      schema_version: 'ocean-scientific-figure/v4',
      plot_kind: 'profile',
      data: {temperature: [28, 20, 10], depth: [0, 200, 1_000]},
      panels: [{
        id: 'profile',
        axes: {x: {field: 'temperature'}, y: {field: 'depth', reverse: true}},
        layers: [{type: 'scatter', x: 'temperature', y: 'depth'}],
      }],
    });

    expect(normalized.panels[0]?.layers[0]?.type).toBe('line');
  });

  it('keeps a profile colour variable while replacing disconnected markers', () => {
    const normalized = normalizeScientificFigure({
      schema_version: 'ocean-scientific-figure/v4',
      plot_kind: 'profile',
      data: {density: [22, 25, 27], depth: [0, 200, 1_000], salinity: [35, 35.5, 34.9]},
      panels: [{
        id: 'profile',
        axes: {x: {field: 'density'}, y: {field: 'depth', reverse: true}},
        layers: [{type: 'scatter', x: 'density', y: 'depth', color: 'salinity', style: {radius: 3}}],
      }],
    });

    const layer = normalized.panels[0]?.layers[0];
    expect(layer?.type).toBe('line');
    expect(layer && 'color' in layer ? layer.color : null).toBe('salinity');
    expect(layer?.style?.radius).toBeUndefined();
  });

  it('upsamples continuous spatial grids without interpolating across masked land', () => {
    const payload = {
      schema_version: 'ocean-interactive-spatial/v1' as const,
      view_kind: 'spatial_map' as const,
      variable: 'theta', units: '°C',
      longitude: [-2, -1, 0], latitude: [0, 1, 2],
      values: [[null, 10, 20], [null, 20, 30], [null, 30, 40]],
      bounds: [-2, 0, 0, 2] as [number, number, number, number],
      rendering: {kind: 'continuous' as const, interpolation: 'linear' as const},
    };

    expect(spatialRasterDimensions(payload)).toEqual({width: 48, height: 48});
    expect(sampleSpatialGrid(payload, -1.75, 1, 'linear')).toBeNull();
    expect(sampleSpatialGrid(payload, -.5, 1.5, 'linear')).toBeCloseTo(30);
  });
  it('keeps the collaboration topology responsive instead of using a fixed-width canvas', () => {
    const snapshot: TeamSnapshot = {
      revision: 1,
      status: 'working',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'},
        {agent_id: 'data', semantic_role: 'Data Expert', authority: 'expert', status: 'working', activity: 'Inspecting metadata', agent_run_id: 'work_1'},
      ],
      dependencies: [],
      interactions: [{
        interaction_id: 'interaction_1',
        from_agent_id: 'coordinator',
        to_agent_id: 'data',
        kind: 'delegation',
        summary: 'Inspect the dataset metadata',
        state: 'active',
      }],
      role_pool: [],
    };

    const markup = renderToStaticMarkup(<AgentCollaborationCanvas snapshot={snapshot} />);

    expect(markup).toContain('preserveAspectRatio="xMidYMid meet"');
    expect(markup).not.toContain('style="height:');
    expect(markup).toContain('Coordinator');
    expect(markup).toContain('Data Expert');
    expect(markup).toContain('width="48" height="48"');
    expect(markup).not.toContain('agent-canvas-conversation');
  });

  it('keeps three parallel Experts visible in the collaboration topology', () => {
    const snapshot: TeamSnapshot = {
      revision: 2,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating three workstreams'},
        {agent_id: 'physical', semantic_role: 'Physical Oceanographer', authority: 'expert', status: 'working', activity: 'Analyzing circulation', agent_run_id: 'work_physical'},
        {agent_id: 'biogeo', semantic_role: 'Biogeochemistry Expert', authority: 'expert', status: 'working', activity: 'Analyzing oxygen', agent_run_id: 'work_biogeo'},
        {agent_id: 'statistics', semantic_role: 'Statistical Inference Expert', authority: 'expert', status: 'working', activity: 'Testing uncertainty', agent_run_id: 'work_statistics'},
      ],
      dependencies: [],
      interactions: [
        {interaction_id: 'interaction_physical', from_agent_id: 'coordinator', to_agent_id: 'physical', kind: 'delegation', summary: 'Analyze circulation', state: 'active'},
        {interaction_id: 'interaction_biogeo', from_agent_id: 'coordinator', to_agent_id: 'biogeo', kind: 'delegation', summary: 'Analyze oxygen', state: 'active'},
        {interaction_id: 'interaction_statistics', from_agent_id: 'coordinator', to_agent_id: 'statistics', kind: 'delegation', summary: 'Test uncertainty', state: 'active'},
      ],
      role_pool: [],
    };

    const markup = renderToStaticMarkup(<AgentCollaborationCanvas snapshot={snapshot} />);

    expect(markup).toContain('Physical Oceanographer');
    expect(markup).toContain('Biogeochemistry Expert');
    expect(markup).toContain('Statistical Inference Expert');
    expect(markup.match(/class="agent-edge active"/g)).toHaveLength(3);
    expect(markup.match(/agent-role-icon-expert/g)).toHaveLength(3);
    expect(markup.match(/agent-role-icon-coordinator/g)).toHaveLength(1);
    expect(new Set([...markup.matchAll(/--agent-accent:([^;"]+)/g)].map((match) => match[1])).size).toBeGreaterThanOrEqual(4);
  });

  it('shows every backend assignment and preserves a waiting Expert state', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_canvas_progress',
      revision: 4,
      status: 'completed',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Synthesizing returned evidence'},
        {agent_id: 'physical', profile_id: 'physical', semantic_role: 'Physical Oceanographer', authority: 'expert', status: 'completed', activity: 'Returned circulation evidence', agent_run_id: 'work_physical'},
        {agent_id: 'statistics', profile_id: 'statistics', semantic_role: 'Statistical Inference Expert', authority: 'expert', status: 'waiting', activity: 'Waiting to start', agent_run_id: 'work_statistics'},
      ],
      todos: [
        {
          todo_id: 'circulation', question: 'Resolve the complete annual and seasonal Loop Current structure across the study region.', depends_on: [], profile_id: 'physical', expected_outputs: ['answer'],
          state: 'result_returned', agent_run_id: 'work_physical', report_path: '/task/physics/report.md',
        },
        {
          todo_id: 'uncertainty', question: 'Test the uncertainty after the physical analysis is available.', depends_on: ['circulation'], profile_id: 'statistics', expected_outputs: ['answer'],
          state: 'pending', agent_run_id: 'work_statistics',
        },
      ],
      role_pool: [
        {profile_id: 'physical', display_name: 'Physical Oceanographer', authority: 'expert', category: 'science', summary: 'Physical interpretation'},
        {profile_id: 'statistics', display_name: 'Statistical Inference Expert', authority: 'expert', category: 'methods', summary: 'Statistical inference'},
      ],
      dependencies: [],
      interactions: [],
    };

    const markup = renderToStaticMarkup(<AgentCollaborationCanvas snapshot={snapshot} />);

    expect(markup).toContain('Physical Oceanographer');
    expect(markup).toContain('Objective: Resolve the complete annual and seasonal Loop Current structure');
    expect(markup).not.toContain('coherent Loop Current extension and its vertical signature');
    expect(markup).toContain('Statistical Inference Expert');
    expect(markup).toContain('status-waiting');
    expect(markup).toContain('Test the uncertainty');
    expect(markup).not.toContain('role="button"');
  });

  it('renders the selected agent complete history in the fixed canvas panel', () => {
    const agent = {agent_id: 'physical', semantic_role: 'Physical Oceanographer', authority: 'expert' as const, status: 'working' as const, activity: 'Analyzing circulation', agent_run_id: 'work_physical'};
    const transcript: TeamAgentTranscript = {
      agent_id: agent.agent_id,
      agent_run_id: agent.agent_run_id,
      messages: [
        {message_id: 'message_1', role: 'coordinator', blocks: [{type: 'text', text: 'Analyze the circulation evidence.'}]},
        {message_id: 'message_2', role: 'expert', blocks: [{type: 'tool_call', tool_call_id: 'tool_1', tool_name: 'ocean_execute_code', input: {script: 'analysis.py'}}]},
        {message_id: 'message_3', role: 'expert', blocks: [{type: 'text', text: 'The Loop Current signal is resolved.'}]},
      ],
    };

    const markup = renderToStaticMarkup(<AgentActivityPanel agent={agent} profiles={[]} todos={[]} transcript={transcript} loading={false} error={null} />);

    expect(markup).toContain('Analyze the circulation evidence.');
    expect(markup).toContain('ocean_execute_code');
    expect(markup).toContain('The Loop Current signal is resolved.');
    expect(markup).toContain('Technical activity');
    expect(markup).toContain('Coordinator → Physical Oceanographer');
    expect(markup).toContain('Physical Oceanographer → Coordinator');
    expect(markup).not.toContain('>Back<');
  });

  it('keeps a unified result workbench mounted when no result is selected', () => {
    const markup = renderToStaticMarkup(<ResultWorkbench />);

    expect(markup).toContain('aria-label="Result workbench"');
    expect(markup).not.toContain('Result Workbench</strong>');
    expect(markup).not.toContain('Charts Open Here Too');
    expect(markup).toContain('Preparing map');
  });

  it('opens non-spatial time series in the same result workbench', () => {
    const document: ResultDocument = {
      key: 'task_1/result_fixture@v1',
      title: 'Seasonal chlorophyll cycle',
      content: {view_kind: 'time_series'},
      summary: 'Monthly chlorophyll and mixed-layer depth.',
    };
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={document}
      loading={false}
      data={{
        plot_kind: 'time_series',
        schema_version: 'ocean-scientific-figure/v4',
        data: {month: ['Jan', 'Feb', 'Mar'], chlorophyll: [.2, .3, .25]},
        panels: [{id: 'main', axes: {x: {field: 'month', scale: 'category'}, y: {field: 'chlorophyll', units: 'mg m-3'}}, layers: [{type: 'line', x: 'month', y: 'chlorophyll'}]}],
        spatial_context: {
          region_key: 'gulf-region',
          bounds: [-98, 18, -77, 32],
          fit_policy: 'region_change',
          features: {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              properties: {label: 'Region A'},
              geometry: {type: 'Point', coordinates: [-90, 25]},
            }],
          },
        },
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('aria-label="Result workbench"');
    expect(markup).toContain('result-chart-surface');
    expect(markup).toContain('spatial-workbench-body with-figure');
    expect(markup).toContain('Study area');
    expect(markup).toContain('Region A');
    expect(markup).toContain('chlorophyll');
    expect(markup).toContain('result-drawer-header');
    expect(markup).toContain('scientific-compact');
    expect(markup).toContain('class="spatial-split-rule"');
    expect(markup).toContain('aria-label="Give figure more room"');
  });

  it('keeps a bounds-only analysis spatially grounded without inventing a land-covering mask', () => {
    const document: ResultDocument = {
      key: 'task_1/bounded_profile@v1',
      title: 'Area-mean temperature profile',
      content: {view_kind: 'profile'},
      summary: 'A profile linked to the source-data footprint.',
    };
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={document}
      loading={false}
      data={{
        schema_version: 'ocean-scientific-figure/v4',
        plot_kind: 'profile',
        title: 'Area-mean temperature profile',
        data: {temperature: [27.2, 12.4], depth: [0.49, 5727.9]},
        panels: [{id: 'main',
        axes: {
          x: {field: 'temperature', label: 'Potential temperature', units: '°C'},
          y: {field: 'depth', label: 'Depth', units: 'm', reverse: true},
        },
        layers: [{type: 'line', x: 'temperature', y: 'depth', label: 'Annual mean'}],
        }],
        spatial_context: {
          region_key: 'dataset:gulf',
          bounds: [-98.5, 16.5, -77, 32],
          fit_policy: 'region_change',
        },
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('Analysis extent');
    expect(markup).toContain('98.5°W–77.0°W · 16.5°N–32.0°N');
    expect(markup).toContain('valid ocean cells remain masked');
    expect(markup).not.toContain('Study area');
    expect(markup).toContain('result-drawer-header');
  });

  it('gives a non-spatial scientific figure the full workbench instead of showing an unrelated map', () => {
    const document: ResultDocument = {
      key: 'task_1/non_spatial@v1',
      title: 'Seasonal anomaly',
      content: {view_kind: 'time_series'},
      summary: 'A scientific figure without spatial context.',
    };
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={document}
      loading={false}
      data={{
        plot_kind: 'time_series',
        schema_version: 'ocean-scientific-figure/v4',
        data: {month: ['Jan', 'Feb', 'Mar'], anomaly: [-.2, .1, .3]},
        panels: [{id: 'main', axes: {x: {field: 'month', scale: 'category'}, y: {field: 'anomaly', units: '°C'}}, layers: [{type: 'line', x: 'month', y: 'anomaly'}]}],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('spatial-workbench-body with-figure figure-only');
    expect(markup).toContain('result-chart-surface');
    expect(markup).not.toContain('Study area');
  });

  it('shows every compact category label instead of hiding alternating observations', () => {
    const labels = ['Jun–Sep', 'Jun–Oct', 'Jul–Oct', 'May–Oct', 'Apr–Mar', 'Jan–Dec', 'Dec–Feb', 'Aug–Nov'];
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={{key: 'task_1/windows@v1', title: 'Window sensitivity', content: {view_kind: 'scatter'}}}
      loading={false}
      data={{
        plot_kind: 'categorical',
        schema_version: 'ocean-scientific-figure/v4',
        data: {window: labels, contrast: [-.05, -.12, .1, .19, .53, .7, .72, .76]},
        panels: [{
          id: 'main',
          axes: {x: {field: 'window', scale: 'category'}, y: {field: 'contrast', units: '°C'}},
          layers: [{type: 'scatter', x: 'window', y: 'contrast'}],
        }],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    labels.forEach((label) => expect(markup).toContain(label));
    expect(markup.match(/scientific-category-tick/g)).toHaveLength(labels.length);
    expect(markup).toContain('scientific-zero-reference');
  });

  it('uses a shared local domain and identity line for same-unit comparison scatters', () => {
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={{key: 'task_1/depth-comparison@v1', title: 'Half-amplitude depth', content: {view_kind: 'scatter'}}}
      loading={false}
      data={{
        plot_kind: 'scatter',
        schema_version: 'ocean-scientific-figure/v4',
        data: {reference_depth: [52, 60, 70], bay_depth: [45, 46, 48]},
        panels: [{
          id: 'main',
          axes: {
            x: {field: 'reference_depth', label: 'Reference half depth', units: 'm'},
            y: {field: 'bay_depth', label: 'Bay half depth', units: 'm'},
          },
          layers: [{type: 'scatter', x: 'reference_depth', y: 'bay_depth'}],
        }],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('scientific-identity-reference');
    expect(markup).not.toMatch(/class="scientific-tick">0<\/text>/);
  });

  it('shows a saved PNG when interactive rendering is unavailable', () => {
    const document: ResultDocument = {
      key: 'task_1/result_fallback@v1',
      title: 'Temperature section',
      content: {
        view_kind: 'section',
        render_status: 'preview',
        render_message: 'The generic renderer rejected this payload.',
      },
      summary: 'A durable result with a static fallback.',
    };
    const markup = renderToStaticMarkup(<ResultWorkbench
      document={document}
      loading={false}
      data={null}
      previewUrl="ocean-artifact://resource/preview-token"
      downloadUrl="ocean-artifact://resource/data-token"
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('result-fallback-surface');
    expect(markup).toContain('Static preview');
    expect(markup).toContain('ocean-artifact://resource/preview-token');
    expect(markup).toContain('Download result');
    expect(markup).not.toContain('Unsupported result payload');
  });

  it('uses bounds only for camera fitting and never fabricates a region mask', () => {
    const display = displayContextFor({
      region_key: 'bounded-analysis',
      bounds: [-98, 18, -77, 32],
      fit_policy: 'region_change',
    });

    expect(display).toBeNull();
  });

  it('keeps the camera for related views and derives bounds from generic GeoJSON context', () => {
    const context = {
      region_key: 'same-scientific-region',
      fit_policy: 'region_change' as const,
      features: {
        type: 'FeatureCollection' as const,
        features: [{
          type: 'Feature' as const,
          properties: {label: 'Region A'},
          geometry: {
            type: 'Polygon' as const,
            coordinates: [[[-92, 20], [-80, 20], [-80, 30], [-92, 30], [-92, 20]]],
          },
        }],
      },
    };

    expect(boundsForContext(context)).toEqual([-92, 20, -80, 30]);
    expect(shouldFitRegion(null, context)).toBe(true);
    expect(shouldFitRegion('same-scientific-region', context)).toBe(false);
    expect(shouldFitRegion('another-region', context)).toBe(true);
  });

  it('fits maps only after layout and scales camera padding to the viewport', () => {
    expect(usableMapViewport(0, 640)).toBe(false);
    expect(usableMapViewport(31, 640)).toBe(false);
    expect(usableMapViewport(640, 320)).toBe(true);
    expect(mapFitPadding(640, 120)).toBe(16);
    expect(mapFitPadding(640, 320)).toBe(25);
    expect(mapFitPadding(1_200, 900)).toBe(48);
  });

  it('renders section payloads as an inspectable continuous field surface', () => {
    const artifact: ArtifactVersion = {
      ref: {artifact_id: 'interactive_view_section', version: 1},
      artifact_type: 'interactive_view',
      title: 'Seasonal section',
      content: {view_kind: 'section'},
      summary: 'Temperature section.',
    };
    const markup = renderToStaticMarkup(<InteractiveViewWorkbench
      artifact={artifact}
      loading={false}
      data={{
        plot_kind: 'section',
        schema_version: 'ocean-scientific-figure/v4',
        data: {distance: [0, 10], depth: [0, 50], temperature: [24, 22, 18, 15]},
        panels: [{id: 'main', axes: {x: {field: 'distance', units: 'km'}, y: {field: 'depth', label: 'depth', units: 'm', reverse: true}}, layers: [{type: 'field2d', x: 'distance', y: 'depth', z: 'temperature'}]}],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('Section · Seasonal section');
    expect(markup).toContain('scientific-figure');
    expect(markup).toContain('scientific-field');
    expect(markup).toContain('scientific-colorbar');
    expect(markup).toContain('depth (m)');
  });

  it('renders computed categories with visible labels instead of implying clusters from colour fields', () => {
    const artifact: ArtifactVersion = {
      ref: {artifact_id: 'interactive_categories', version: 1},
      artifact_type: 'interactive_view',
      title: 'Classified samples',
      content: {view_kind: 'scatter'},
      summary: 'Three computed sample groups.',
    };
    const markup = renderToStaticMarkup(<InteractiveViewWorkbench
      artifact={artifact}
      loading={false}
      data={{
        schema_version: 'ocean-scientific-figure/v4',
        plot_kind: 'scatter',
        title: 'Classified samples',
        data: {x: [1, 2, 3, 4], y: [1, 2, 3, 4], group: ['a', 'a', 'b', 'c']},
        panels: [{
          id: 'groups',
          axes: {x: {field: 'x', label: 'X'}, y: {field: 'y', label: 'Y'}},
          layers: [{
            type: 'categories', x: 'x', y: 'y', category: 'group',
            labels: {a: 'Upper water', b: 'Intermediate water', c: 'Deep water'},
          }],
        }],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('Upper water');
    expect(markup).toContain('Intermediate water');
    expect(markup).toContain('Deep water');
    expect(markup.match(/class="scientific-panel-legend"/g)).toHaveLength(1);
  });

  it('renders layered publication-style scientific views without a plot-specific component', () => {
    const artifact: ArtifactVersion = {
      ref: {artifact_id: 'interactive_view_ts', version: 1},
      artifact_type: 'interactive_view',
      title: 'Water-mass structure',
      content: {view_kind: 'ts_diagram'},
      summary: 'T–S structure with density context.',
    };
    const markup = renderToStaticMarkup(<InteractiveViewWorkbench
      artifact={artifact}
      loading={false}
      data={{
        schema_version: 'ocean-scientific-figure/v4',
        plot_kind: 'ts_diagram',
        title: 'Water-mass structure',
        data: {salinity: [35.1, 35.6], temperature: [12, 24], depth: [500, 20]},
        panels: [{id: 'main',
        axes: {
          x: {field: 'salinity', label: 'Practical salinity', range: [34.8, 36]},
          y: {field: 'temperature', label: 'Potential temperature', units: '°C'},
        },
        layers: [
          {type: 'contour', label: 'σ₀', paths: [{level: 26, points: [[35, 10], [35.8, 22]]}], style: {color: '#929ca2'}},
          {type: 'scatter', x: 'salinity', y: 'temperature', color: 'depth', color_scale: 'log', label: 'Samples', style: {palette: 'depth'}},
          {type: 'annotation', items: [{x: 35.6, y: 24, text: '20 m'}]},
        ],
        display: {colorbar_label: 'Depth (m)'},
        }],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('Water-mass structure');
    expect(markup).toContain('scientific-contour-label');
    expect(markup).toContain('20 m');
    expect(markup).toContain('Chart zoom controls');
    expect(markup).toContain('Depth (m)');
  });

  it('renders a 150k-sample scientific scatter without exceeding the browser argument stack', () => {
    const sampleCount = 150_000;
    const salinity = Array.from({length: sampleCount}, (_, index) => 34.5 + (index % 2_000) / 1_000);
    const temperature = Array.from({length: sampleCount}, (_, index) => 4 + (index % 2_500) / 100);
    const depth = Array.from({length: sampleCount}, (_, index) => 1 + index % 4_000);
    const markup = renderToStaticMarkup(<InteractiveViewWorkbench
      artifact={{
        ref: {artifact_id: 'interactive_large_ts', version: 1},
        artifact_type: 'interactive_view',
        title: 'Large T-S sample',
        content: {view_kind: 'ts_diagram'},
        summary: 'A dense water-column sample.',
      }}
      loading={false}
      data={{
        schema_version: 'ocean-scientific-figure/v4',
        plot_kind: 'ts_diagram',
        data: {salinity, temperature, depth},
        panels: [{id: 'main',
        axes: {
          x: {field: 'salinity', label: 'Salinity', units: 'psu'},
          y: {field: 'temperature', label: 'Temperature', units: '°C'},
        },
        layers: [{type: 'scatter', x: 'salinity', y: 'temperature', color: 'depth', color_scale: 'log'}],
        }],
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('Large T-S sample');
    expect(markup).toContain('class="scientific-scatter-canvas"');
    expect(markup).toContain('data-point-count="150000"');
    expect(markup).not.toContain('r="2.35"');
  });

  it('renders a generic multi-panel scientific figure without plot-kind branches', () => {
    const artifact: ArtifactVersion = {
      ref: {artifact_id: 'interactive_figure_generic', version: 1},
      artifact_type: 'interactive_view',
      title: 'Coupled evidence',
      content: {view_kind: 'time_series'},
      summary: 'Two related views composed from the same generic layer grammar.',
    };
    const markup = renderToStaticMarkup(<InteractiveViewWorkbench
      artifact={artifact}
      loading={false}
      data={{
        schema_version: 'ocean-scientific-figure/v4',
        plot_kind: 'time_series',
        title: 'Coupled evidence',
        subtitle: 'Shared data, independent axes and layers',
        data: {
          month: ['Apr', 'May', 'Jun'],
          estimate: [12, 18, 15],
          lower: [10, 16, 13],
          upper: [14, 20, 17],
          x: [0, 1], y: [0, 1], u: [.2, -.1], v: [.1, .25],
        },
        layout: {columns: 2},
        panels: [
          {
            id: 'estimate', label: 'a', title: 'Estimate and interval',
            axes: {x: {field: 'month', scale: 'category'}, y: {field: 'estimate', label: 'Value'}},
            layers: [
              {type: 'band', x: 'month', y0: 'lower', y1: 'upper', label: 'Interval'},
              {type: 'line', x: 'month', y: 'estimate', label: 'Estimate', style: {radius: 2.4}},
            ],
          },
          {
            id: 'vectors', label: 'b', title: 'Vector evidence',
            axes: {x: {field: 'x'}, y: {field: 'y'}},
            layers: [
              {type: 'vector', x: 'x', y: 'y', u: 'u', v: 'v', label: 'Direction'},
              {type: 'annotation', items: [{x: 1, y: 1, text: 'Observed', arrow: true}]},
            ],
          },
        ],
        caption: 'Figure-level caption remains attached to the complete evidence object.',
      }}
      previewUrl={null}
      error={null}
      onClose={() => undefined}
    />);

    expect(markup).toContain('scientific-columns-2');
    expect(markup).not.toContain('scientific-auto-hero');
    expect(markup).toContain('Estimate and interval');
    expect(markup).toContain('Vector evidence');
    expect(markup).not.toContain('>Direction<');
    expect(markup.match(/class="scientific-panel-legend"/g)).toHaveLength(1);
    expect(markup).toContain('Observed');
    expect(markup).toContain('Figure-level caption');
  });

  it('uses scientific axis semantics instead of generic padding for nonnegative depth', () => {
    const extent = scientificAxisExtent([0.49, 5727.9], {
      field: 'depth',
      label: 'Depth',
      units: 'm',
      reverse: true,
    });

    expect(extent[0]).toBe(0);
    expect(extent[1]).toBeGreaterThan(5727.9);
  });

  it('keeps zoomed and panned scientific views inside their data domain', () => {
    expect(clampScientificDomain([-2030, 3784], [0, 5814])).toEqual([0, 5814]);
    expect(clampScientificDomain([-500, 2000], [0, 5814])).toEqual([0, 2500]);
    expect(clampScientificDomain([5000, 7000], [0, 5814])).toEqual([3814, 5814]);
  });

  it('shows a Workbench action when a request manifest delivers an interactive view', () => {
    const output: TaskOutput = {
      artifact: {
        ref: {artifact_id: 'interactive_view_delivered', version: 1},
        artifact_type: 'interactive_view',
        title: 'Delivered seasonal view',
      },
      relation: 'primary',
      origin_request_id: 'req_delivered',
    };
    const manifest: DeliveryManifest = {
      request_id: 'req_delivered',
      entries: [{
        entry_id: 'delivery_0123456789abcdef01234567',
        kind: 'interactive_view',
        title: 'Delivered seasonal view',
        open_ref: output.artifact.ref,
        artifact_type: 'interactive_view',
        placement: 'inline',
        capabilities: ['open'],
        openable: true,
      }],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[
        {item_id: 'user_delivered', role: 'user', text: 'Show the seasonal result', request_id: 'req_delivered'},
        {item_id: 'assistant_delivered', role: 'assistant', text: 'The result is ready.', request_id: 'req_delivered'},
      ]}
      streaming=""
      activeRequestId={null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[output]}
      manifests={[manifest]}
      taskResults={[]}
      team={null}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('Interactive View');
    expect(markup).toContain('Delivered seasonal view');
    expect(markup).toContain('result-interactive_view');
  });

  it('shows the Coordinator aggregate outcome in the Team Canvas header', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_incomplete',
      revision: 3,
      status: 'incomplete',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'completed', activity: 'Returned the available evidence'},
        {agent_id: 'data', semantic_role: 'Data Expert', authority: 'expert', status: 'incomplete', activity: 'Returned a useful partial result', agent_run_id: 'work_1'},
      ],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'data', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[
        {item_id: 'user_1', role: 'user', text: 'Inspect the data', request_id: 'req_incomplete'},
        {item_id: 'assistant_1', role: 'assistant', text: 'The bounded evidence is incomplete.', request_id: 'req_incomplete'},
      ]}
      streaming=""
      activeRequestId={null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('<span>Team</span>');
    expect(markup).toContain('Partial result');
    expect(markup).not.toContain('>Incomplete<');
    expect(markup).toContain('status-incomplete');
  });

  it('keeps the completed Canvas between its duration divider and final answer', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_supplement',
      revision: 4,
      status: 'completed',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'completed', activity: 'Task completed'},
        {agent_id: 'data', semantic_role: 'Data Expert', authority: 'expert', status: 'completed', activity: 'Evidence returned', agent_run_id: 'work_supplement'},
      ],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'data', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const supplement: TaskResultRecord = {
      result_ref: {task_id: 'task_supplement', result_id: 'result_notebook', version: 1},
      workspace_id: 'ws_supplement',
      kind: 'file',
      title: 'Analysis notebook',
      summary: 'One editable notebook for this analysis.',
      created_at: '2026-08-28T10:00:10Z',
      origin_request_id: 'req_supplement',
      content: {role: 'supplementary_figure_notebook', file: 'analysis.ipynb'},
      files: [{
        path: 'analysis.ipynb',
        mime_type: 'application/x-ipynb+json',
        size: 512,
        sha256: 'a'.repeat(64),
      }],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[
        {item_id: 'user_supplement', role: 'user', text: 'Analyze the field.', request_id: 'req_supplement', created_at: '2026-08-28T10:00:00Z'},
        {item_id: 'answer_supplement', role: 'assistant', text: 'The scientific conclusion is ready.', request_id: 'req_supplement', created_at: '2026-08-28T10:19:39Z'},
      ]}
      streaming=""
      activeRequestId={null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[supplement]}
      team={null}
      teamSnapshots={{req_supplement: snapshot}}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
      onOpenTaskResultFile={() => undefined}
    />);

    expect(markup.indexOf('Analyze the field.')).toBeLessThan(markup.indexOf('Completed in 19m 39s'));
    expect(markup.indexOf('Completed in 19m 39s')).toBeLessThan(markup.indexOf('agent-canvas'));
    expect(markup.indexOf('agent-canvas')).toBeLessThan(markup.indexOf('The scientific conclusion is ready.'));
    expect(markup.indexOf('The scientific conclusion is ready.')).toBeLessThan(markup.indexOf('Supplementary Materials'));
    expect(markup.match(/Completed in 19m 39s/g)).toHaveLength(1);
    expect(markup).not.toContain('Analysis notebook');
    expect(markup).not.toContain('One editable notebook for this analysis.');
    expect(markup).toContain('supplementary-material-link');
    expect(markup).toContain('<section class="supplementary-materials"');
    expect(markup).toContain('<strong>Supplementary Materials:</strong><ul><li>');
    expect(markup).toContain('<strong>analysis.ipynb</strong>');
  });

  it('shows skill revisions on the task exchange that caused them', () => {
    const update: TaskResultRecord = {
      result_ref: {task_id: 'task_skill', result_id: 'result_skill', version: 1},
      workspace_id: 'ws_skill',
      kind: 'table',
      title: 'Skill updated: robust-contour-rendering',
      summary: 'Prefer gridded rendering for dense spatial fields.',
      created_at: '2026-08-28T10:00:10Z',
      origin_request_id: 'req_skill',
      content: {role: 'skill_update', skill_name: 'robust-contour-rendering', operation: 'update', version: 2},
      files: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[
        {item_id: 'user_skill', role: 'user', text: 'Render this field.', request_id: 'req_skill'},
        {item_id: 'answer_skill', role: 'assistant', text: 'The field is ready.', request_id: 'req_skill'},
      ]}
      streaming=""
      activeRequestId={null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[update]}
      team={null}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('OceanX learned from this task');
    expect(markup).toContain('robust-contour-rendering');
    expect(markup).toContain('version 2');
  });

  it('uses the answer area for Todo progress only until the final answer arrives', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_progress',
      revision: 2,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'},
        {agent_id: 'physical', semantic_role: 'Physical Oceanographer', authority: 'expert', status: 'working', activity: 'Analyzing circulation', agent_run_id: 'work_physical'},
      ],
      todos: [
        {todo_id: 'circulation', question: 'Resolve the circulation structure.', depends_on: [], profile_id: 'physical', expected_outputs: ['answer'], state: 'working', agent_run_id: 'work_physical', session_round: 1},
        {todo_id: 'synthesis', question: 'Synthesize the physical interpretation.', depends_on: ['circulation'], profile_id: 'physical', expected_outputs: ['answer'], state: 'pending'},
      ],
      dependencies: [],
      interactions: [],
      role_pool: [],
    };
    const common = {
      loading: false,
      streaming: '',
      task: null,
      workspacePath: '/tmp/workspace',
      outputs: [] as TaskOutput[],
      manifests: [] as DeliveryManifest[],
      taskResults: [],
      team: snapshot,
      onOpenResult: () => undefined,
      onOpenTaskResult: () => undefined,
    };
    const activeMarkup = renderToStaticMarkup(<ConversationTranscript
      {...common}
      transcript={[{item_id: 'user_progress', role: 'user', text: 'Analyze the circulation.', request_id: 'req_progress', created_at: '2026-08-25T10:00:00Z'}]}
      activeRequestId="req_progress"
    />);
    const finalMarkup = renderToStaticMarkup(<ConversationTranscript
      {...common}
      team={{...snapshot, status: 'completed'}}
      transcript={[
        {item_id: 'user_progress', role: 'user', text: 'Analyze the circulation.', request_id: 'req_progress', created_at: '2026-08-25T10:00:00Z'},
        {item_id: 'answer_progress', role: 'assistant', text: 'Final evidence-backed answer.', request_id: 'req_progress', created_at: '2026-08-25T10:00:51Z'},
      ]}
      activeRequestId={null}
    />);

    expect(activeMarkup).toContain('Objective');
    expect(activeMarkup).toContain('Resolve the circulation structure.');
    expect(activeMarkup).not.toContain('circulation</code>');
    expect(activeMarkup).not.toContain('round 1');
    expect(activeMarkup).not.toContain('Physical Oceanographer activity and conversation');
    expect(activeMarkup).not.toContain('Show team map');
    expect(activeMarkup).toContain('aria-label="Active OceanX Team"');
    expect(activeMarkup).not.toContain('Final evidence-backed answer.');
    expect(finalMarkup).toContain('Final evidence-backed answer.');
    expect(finalMarkup).not.toContain('Research Tasks');
    expect(finalMarkup).toContain('Hide team');
    expect(finalMarkup).toContain('aria-label="Active OceanX Team"');
    expect(finalMarkup).toContain('Resolve the circulation structure.');
    expect(finalMarkup).not.toContain('Coordinator activity and conversation');
  });

  it('shows temporary Coordinator updates and file-derived report titles below the canvas', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_live_log',
      revision: 3,
      status: 'working',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Reviewing returned evidence'},
        {
          agent_id: 'physical',
          profile_id: 'physical',
          semantic_role: 'Physical Oceanographer',
          authority: 'expert',
          status: 'waiting',
          activity: 'Waiting for Coordinator feedback',
          agent_run_id: 'work_physical',
          report_path: '/task/physics/report.md',
          report_title: '**Result:** Seasonal Loop Current structure',
        },
      ],
      todos: [{
        todo_id: 'seasonal_structure',
        question: 'Compare the seasonal Loop Current structure.',
        depends_on: [],
        profile_id: 'physical',
        expected_outputs: ['answer'],
        state: 'result_returned',
        agent_run_id: 'work_physical',
        report_path: '/task/physics/report.md',
      }],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'physical', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const common = {
      loading: false,
      streaming: '',
      task: null,
      workspacePath: '/tmp/workspace',
      outputs: [] as TaskOutput[],
      manifests: [] as DeliveryManifest[],
      taskResults: [],
      team: snapshot,
      onOpenResult: () => undefined,
      onOpenTaskResult: () => undefined,
    };
    const items = [
      {item_id: 'user_live_log', role: 'user' as const, text: 'Compare the seasonal structure.', request_id: 'req_live_log'},
      {item_id: 'coordinator_live_log', role: 'assistant' as const, text: 'I am **comparing** the returned seasonal evidence before deciding whether a refinement is needed.\n\n- Seasonal amplitude\n- Peak timing', request_id: 'req_live_log'},
    ];
    const activeMarkup = renderToStaticMarkup(<ConversationTranscript
      {...common}
      transcript={items}
      activeRequestId="req_live_log"
    />);
    const finalMarkup = renderToStaticMarkup(<ConversationTranscript
      {...common}
      team={{...snapshot, status: 'completed'}}
      transcript={[...items, {item_id: 'answer_live_log', role: 'assistant', text: 'The final seasonal conclusion [work_physical/raw-analysis].', request_id: 'req_live_log'}]}
      activeRequestId={null}
    />);

    expect(activeMarkup).not.toContain('Live research log');
    expect(activeMarkup).not.toContain('Temporary');
    expect(activeMarkup).toContain('<strong>Coordinator:</strong>');
    expect(activeMarkup).toContain('<div class="research-log-content"><span class="compact-log-markdown">');
    expect(activeMarkup).toContain('class="compact-log-markdown"');
    expect(activeMarkup).toContain('<strong>comparing</strong>');
    expect(activeMarkup).toContain('<span class="compact-log-list-item">Seasonal amplitude</span>');
    expect(activeMarkup).not.toContain('<li>Seasonal amplitude</li>');
    expect(activeMarkup).not.toContain('**comparing**');
    expect(activeMarkup).toContain('Seasonal Loop Current structure');
    expect(activeMarkup).toContain('<strong>Result:</strong>');
    expect(activeMarkup).not.toContain('**Result:**');
    expect(activeMarkup).toContain('class="research-report-link"');
    expect(activeMarkup).toContain('/task/physics/report.md');
    expect(finalMarkup).toContain('The final seasonal conclusion ');
    expect(finalMarkup).toContain('Physical Oceanographer 1 · raw-analysis');
    expect(finalMarkup).toContain('aria-label="Open Result: Seasonal Loop Current structure"');
    expect(finalMarkup).toContain('title="work_physical/raw-analysis —');
    expect(finalMarkup).not.toContain('Live research log');
    expect(finalMarkup).not.toContain('I am comparing the returned seasonal evidence');
  });

  it('keeps the activity log below the canvas while the first Expert result is pending', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_pending_log',
      revision: 2,
      status: 'working',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Waiting for the literature evidence'},
        {agent_id: 'literature', profile_id: 'literature_reproduction_expert', semantic_role: 'Literature Expert', authority: 'expert', status: 'working', activity: 'Searching the relevant literature', agent_run_id: 'work_literature'},
      ],
      todos: [{
        todo_id: 'literature-scope', question: 'Map the mechanism literature.', depends_on: [],
        profile_id: 'literature_reproduction_expert', expected_outputs: ['answer'],
        state: 'working', agent_run_id: 'work_literature',
      }],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'literature', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[{item_id: 'user_pending_log', role: 'user', text: 'Research this question.', request_id: snapshot.request_id}]}
      streaming=""
      activeRequestId={snapshot.request_id ?? null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('class="live-research-log"');
    expect(markup).toContain('Waiting for the literature evidence');
    expect(markup).toContain('Searching the relevant literature');
    expect(markup.indexOf('aria-label="Active OceanX Team"')).toBeLessThan(markup.indexOf('class="live-research-log"'));
  });

  it('shows every research-node assignment even when the backend reuses one Expert identity', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_assignment_reports',
      revision: 6,
      status: 'working',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Expanding the frontier'},
        {
          agent_id: 'ocean-b1', profile_id: 'ocean_process_expert', expert_key: 'ocean-b1',
          semantic_role: 'Ocean Expert', authority: 'expert', status: 'completed',
          activity: 'B1.2 result returned', agent_run_id: 'call-b12',
          report_path: '/task/reports/B1.2/report.md', report_title: 'B1.2 transport result',
        },
      ],
      todos: [
        {
          todo_id: 'call-b11', question: 'B1.1: establish anomaly', depends_on: [],
          profile_id: 'ocean_process_expert', expert_key: 'ocean-b1', expected_outputs: [],
          state: 'result_returned', agent_run_id: 'call-b11',
          report_path: '/task/reports/B1.1/report.md', report_title: 'Established the anomaly',
          created_at: '2026-09-18T10:00:00Z', updated_at: '2026-09-18T10:05:00Z',
        },
        {
          todo_id: 'call-b12', question: 'B1.2: test transport', depends_on: [],
          profile_id: 'ocean_process_expert', expert_key: 'ocean-b1', expected_outputs: [],
          state: 'result_returned', agent_run_id: 'call-b12',
          report_path: '/task/reports/B1.2/report.md', report_title: 'Found no transport signal',
          created_at: '2026-09-18T10:06:00Z', updated_at: '2026-09-18T10:11:00Z',
        },
      ],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'ocean-b1', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[{item_id: 'user_assignment_reports', role: 'user', text: 'Research the anomaly.', request_id: snapshot.request_id}]}
      streaming=""
      activeRequestId={snapshot.request_id ?? null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup.match(/agent-role-icon-expert/g)).toHaveLength(2);
    expect(markup).toContain('data-research-node="B1.1"');
    expect(markup).toContain('data-research-node="B1.2"');
    expect(markup).toContain('B1.1 · Established the anomaly');
    expect(markup).toContain('B1.2 · Found no transport signal');
    expect(markup).toContain('/task/reports/B1.1/report.md');
    expect(markup).toContain('/task/reports/B1.2/report.md');
  });

  it('embeds paper selection after the Coordinator checkpoint without ending the request', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_paper_checkpoint',
      revision: 4,
      status: 'working',
      strategy: 'single_delegate',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Waiting for the paper selection'},
        {agent_id: 'literature', semantic_role: 'Literature Expert', authority: 'expert', status: 'completed', activity: 'Returned the candidate shortlist', agent_run_id: 'work_literature'},
      ],
      dependencies: [{from_agent_id: 'coordinator', to_agent_id: 'literature', kind: 'delegation'}],
      interactions: [],
      role_pool: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[
        {item_id: 'user_papers', role: 'user', text: 'Develop a testable hypothesis.', request_id: 'req_paper_checkpoint'},
        {item_id: 'coordinator_papers', role: 'assistant', text: '## The Vertical Structure of a Loop Current Eddy\n\n**Citation:** Example et al. (2018)\n\n**Evidence inspected:** Abstract.\n\n**What it reports:** The abstract reports the vertical displacement diagnostic and the observed water-mass response.\n\n**Use in this task:** Compare the reported displacement with the task profiles.\n\n**Boundary:** The full methods and sensitivity analysis have not yet been reviewed.', request_id: 'req_paper_checkpoint'},
      ]}
      streaming=""
      activeRequestId="req_paper_checkpoint"
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      pendingInteraction={{
        interactionId: 'int_paper_checkpoint',
        kind: 'paper_selection',
        question: 'Choose the papers OceanX should use for hypothesis development.',
        options: [{
          paperId: 'paper_eddy',
          title: 'The Vertical Structure of a Loop Current Eddy',
          topic: 'Eddy vertical structure and water-mass displacement',
          evidenceScope: 'abstract',
          evidenceSummary: 'The abstract reports the vertical displacement diagnostic.',
          validationTarget: 'Compare the reported displacement with the task profiles.',
          citation: 'Example et al. (2018)',
        }],
      }}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('status-working');
    expect(markup.indexOf('vertical displacement diagnostic')).toBeLessThan(markup.indexOf('Choose papers'));
    expect(markup).toContain('The full methods and sensitivity analysis have not yet been reviewed.');
    expect(markup.match(/vertical displacement diagnostic/g)).toHaveLength(1);
    expect(markup).toContain('Use selected papers and continue');
    expect(markup.match(/Compare the reported displacement with the task profiles\./g)).toHaveLength(1);
    expect(markup).not.toContain('Completed in');
  });

  it('shows ordinary follow-up dispatches as separate Coordinator children', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_role_singleton',
      revision: 5,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'},
        {agent_id: 'literature-thread', profile_id: 'literature_reproduction_expert', semantic_role: 'Literature Expert', authority: 'expert', status: 'working', activity: 'Reading selected papers', agent_run_id: 'work_reading'},
      ],
      todos: [
        {todo_id: 'prior-reading', question: 'Search papers.', depends_on: [], profile_id: 'literature_reproduction_expert', expert_key: 'literature-thread', expected_outputs: [], state: 'result_returned', agent_run_id: 'work_searching'},
        {todo_id: 'literature-thread', question: 'Read selected papers.', depends_on: [], profile_id: 'literature_reproduction_expert', expected_outputs: ['answer'], state: 'working', agent_run_id: 'work_reading'},
      ],
      dependencies: [],
      interactions: [],
      role_pool: [],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[{item_id: 'user_role_singleton', role: 'user', text: 'Review the papers.', request_id: 'req_role_singleton'}]}
      streaming=""
      activeRequestId="req_role_singleton"
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    expect(markup).toContain('<strong>Search Expert</strong>');
    expect(markup).not.toContain('Evidence &amp; reproduction');
    expect(markup.match(/agent-role-icon-expert/g)).toHaveLength(2);
    expect(markup).toContain('data-from-agent="coordinator" data-to-agent="dispatch:prior-reading"');
    expect(markup).toContain('data-from-agent="coordinator" data-to-agent="dispatch:literature-thread"');
    expect(markup).toContain('Reading selected papers');
  });

  it('renders delegated research nodes as the research-tree hierarchy', () => {
    const snapshot: TeamSnapshot = {
      request_id: 'req_research_hierarchy',
      revision: 8,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Expanding the research tree'},
        {
          agent_id: 'ocean-b1', profile_id: 'ocean_process_expert', expert_key: 'ocean-b1',
          semantic_role: 'Ocean Expert', authority: 'expert', status: 'working',
          activity: 'Resolving the nested mechanism', agent_run_id: 'run-b111',
        },
        {
          agent_id: 'statistics-b1', profile_id: 'statistical_inference_expert', expert_key: 'statistics-b1',
          semantic_role: 'Statistic Expert', authority: 'expert', status: 'working',
          activity: 'Testing the sibling diagnostic', agent_run_id: 'run-b112',
        },
      ],
      todos: [
        {
          todo_id: 'call-parent', question: 'B1.1: establish the parent mechanism.', depends_on: [],
          profile_id: 'ocean_process_expert', expert_key: 'ocean-b1', expected_outputs: [],
          state: 'result_returned', agent_run_id: 'run-b11', report_path: '/task/reports/B1.1/report.md',
        },
        {
          todo_id: 'call-child-ocean', question: 'B1.1.1: resolve the nested process.', depends_on: [],
          profile_id: 'ocean_process_expert', expert_key: 'ocean-b1', expected_outputs: [],
          state: 'working', agent_run_id: 'run-b111',
        },
        {
          todo_id: 'call-child-statistics', question: 'B1.1.2: test the nested diagnostic.', depends_on: [],
          profile_id: 'statistical_inference_expert', expert_key: 'statistics-b1', expected_outputs: [],
          state: 'working', agent_run_id: 'run-b112',
        },
        {
          todo_id: 'call-sibling', question: 'B1.2: constrain the sibling explanation.', depends_on: [],
          profile_id: 'literature_reproduction_expert', expert_key: 'literature-b1', expected_outputs: [],
          state: 'result_returned', agent_run_id: 'run-b12', report_path: '/task/reports/B1.2/report.md',
        },
      ],
      dependencies: [],
      interactions: [],
      role_pool: [],
    };

    const markup = renderToStaticMarkup(<AgentCollaborationCanvas snapshot={snapshot} />);

    expect(markup.match(/agent-role-icon-expert/g)).toHaveLength(4);
    expect(markup).toContain('data-from-agent="coordinator" data-to-agent="research:B1.1"');
    expect(markup).toContain('data-from-agent="research:B1.1" data-to-agent="research:B1.1.1"');
    expect(markup).toContain('data-from-agent="research:B1.1" data-to-agent="research:B1.1.2"');
    expect(markup).toContain('data-from-agent="coordinator" data-to-agent="research:B1.2"');
    expect(markup).toContain('data-research-node="B1.1.1"');
    expect(markup).toContain('data-research-node="B1.1.2"');
  });

  it('reserves separate horizontal space for adjacent research subtrees', () => {
    const todo = (node: string, profileId = 'ocean_process_expert'): NonNullable<TeamSnapshot['todos']>[number] => ({
      todo_id: `call-${node}`,
      question: `${node}: investigate this branch.`,
      depends_on: [],
      profile_id: profileId,
      expected_outputs: [],
      state: 'working',
      agent_run_id: `run-${node}`,
    });
    const snapshot: TeamSnapshot = {
      request_id: 'req_wide_research_hierarchy',
      revision: 9,
      status: 'working',
      strategy: 'parallel_team',
      agents: [{agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'}],
      todos: [
        todo('B1.2', 'statistical_inference_expert'),
        todo('B1.3'),
        todo('B1.7'),
        todo('B1.8'),
        todo('B1.8.1'),
        todo('B1.9'),
        {todo_id: 'call_general_00875', question: 'Run a general literature check.', depends_on: [], profile_id: 'literature_reproduction_expert', expected_outputs: [], state: 'working'},
      ],
      dependencies: [],
      interactions: [],
      role_pool: [],
    };

    const markup = renderToStaticMarkup(<AgentCollaborationCanvas snapshot={snapshot} />);
    const nodeX = (agentId: string) => Number(markup.match(new RegExp(`data-agent-id="${agentId.replace('.', '\\.') }"[^>]*transform="translate\\(([-.0-9]+),`))?.[1]);
    const firstLevel = ['research:B1.2', 'research:B1.3', 'research:B1.7', 'research:B1.8', 'research:B1.9', 'dispatch:call_general_00875']
      .map(nodeX)
      .sort((left, right) => left - right);

    expect(firstLevel.every(Number.isFinite)).toBe(true);
    expect(firstLevel.slice(1).every((x, index) => x - firstLevel[index]! >= 70)).toBe(true);
  });

  it('shows parallel same-profile Experts as separate stable canvas nodes', () => {
    const expert = (expertKey: string, agentRunId: string, taskGoal: string): TeamSnapshot['agents'][number] => ({
      agent_id: `job_${expertKey}`,
      profile_id: 'ocean_process_expert',
      expert_key: expertKey,
      semantic_role: 'Ocean Expert',
      authority: 'expert',
      status: 'working',
      activity: 'Investigating the assigned question',
      agent_run_id: agentRunId,
      task_goal: taskGoal,
    });
    const snapshot: TeamSnapshot = {
      request_id: 'req_parallel_same_profile',
      revision: 1,
      status: 'working',
      strategy: 'parallel_team',
      agents: [
        {agent_id: 'coordinator', semantic_role: 'Coordinator', authority: 'coordinator', status: 'working', activity: 'Coordinating'},
        expert('horizontal_analyst', 'work_horizontal', 'Resolve horizontal structure.'),
        expert('vertical_analyst', 'work_vertical', 'Resolve vertical structure.'),
        expert('water_mass_analyst', 'work_water_mass', 'Resolve T-S water masses.'),
      ],
      todos: [
        {todo_id: 'horizontal', question: 'Resolve horizontal structure.', depends_on: [], profile_id: 'ocean_process_expert', expert_key: 'horizontal_analyst', expected_outputs: ['answer'], state: 'working', agent_run_id: 'work_horizontal'},
        {todo_id: 'vertical', question: 'Resolve vertical structure.', depends_on: [], profile_id: 'ocean_process_expert', expert_key: 'vertical_analyst', expected_outputs: ['answer'], state: 'working', agent_run_id: 'work_vertical'},
        {todo_id: 'water_mass', question: 'Resolve T-S water masses.', depends_on: [], profile_id: 'ocean_process_expert', expert_key: 'water_mass_analyst', expected_outputs: ['answer'], state: 'working', agent_run_id: 'work_water_mass'},
      ],
      dependencies: [
        {from_agent_id: 'coordinator', to_agent_id: 'job_horizontal_analyst', kind: 'delegation'},
        {from_agent_id: 'coordinator', to_agent_id: 'job_vertical_analyst', kind: 'delegation'},
        {from_agent_id: 'coordinator', to_agent_id: 'job_water_mass_analyst', kind: 'delegation'},
      ],
      interactions: [],
      role_pool: [{
        profile_id: 'ocean_process_expert',
        display_name: 'Ocean Expert',
        authority: 'expert',
        category: 'science',
        summary: 'Interprets physical ocean processes.',
      }],
    };
    const markup = renderToStaticMarkup(<ConversationTranscript
      loading={false}
      transcript={[{item_id: 'user_parallel_same_profile', role: 'user', text: 'Run three analyses.', request_id: snapshot.request_id}]}
      streaming=""
      activeRequestId={snapshot.request_id ?? null}
      task={null}
      workspacePath="/tmp/workspace"
      outputs={[]}
      manifests={[]}
      taskResults={[]}
      team={snapshot}
      onOpenResult={() => undefined}
      onOpenTaskResult={() => undefined}
    />);

    const legendMarkup = markup.match(/<aside class="agent-canvas-legend"[^>]*>(.*?)<\/aside>/)?.[1] ?? '';
    expect(legendMarkup.match(/<strong>Ocean Expert<\/strong>/g)).toHaveLength(1);
    expect(markup).not.toContain('Physical mechanisms');
    expect(markup.match(/agent-role-icon-expert/g)).toHaveLength(3);
  });
});
