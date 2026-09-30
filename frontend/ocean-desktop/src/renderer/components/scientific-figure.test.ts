import {describe, expect, it} from 'vitest';

import {structuredViewKind} from './InteractiveViewWorkbench.js';
import {
  conciseScientificLabel,
  isScientificPayload,
  normalizeScientificFigure,
  scientificDisplayUnits,
  type ScientificFigurePayload,
} from './scientific-figure.js';

describe('scientific figure normalization', () => {
  it('keeps renderer labels compact while preserving scientific unit notation', () => {
    const label = conciseScientificLabel(
      'annual-harmonic amplitude of the 0.5 m temperature anomaly (monthly means minus 12-month mean)',
    );

    expect(label.length).toBeLessThanOrEqual(52);
    expect(label.endsWith('…')).toBe(true);
    expect(scientificDisplayUnits('degrees_C')).toBe('°C');
    expect(scientificDisplayUnits('day_of_year_2025')).toBe('2025 DOY');
  });

  it.each(['ocean-scientific-view/v1', 'ocean-scientific-figure/v2', 'ocean-scientific-figure/v3'])('does not upgrade %s', (schema_version) => {
    expect(isScientificPayload({schema_version, plot_kind: 'profile', data: {}, axes: {}, layers: [], panels: [{id: 'main'}]})).toBe(false);
  });
  it('repairs ISO date axes that were incorrectly declared linear', () => {
    const payload: ScientificFigurePayload = {
      schema_version: 'ocean-scientific-figure/v4',
      plot_kind: 'hovmoller',
      data: {
        date: ['2025-04-01T00:00:00.000', '2025-05-01T00:00:00.000'],
        depth: [0, 50],
        value: [28, 27, 20, 19],
      },
      panels: [{
        id: 'main',
        axes: {x: {field: 'date', scale: 'linear'}, y: {field: 'depth', scale: 'linear'}},
        layers: [{type: 'field2d', x: 'date', y: 'depth', z: 'value'}],
      }],
    };

    const normalized = normalizeScientificFigure(payload);
    expect(normalized.panels[0]?.axes.x).toMatchObject({scale: 'time', tick_format: 'date'});
  });

  it('labels a field layer by its visual semantics instead of a stale scatter kind', () => {
    const payload: ScientificFigurePayload = {
      schema_version: 'ocean-scientific-figure/v4',
      plot_kind: 'scatter',
      data: {x: [1, 2], y: [1, 2], z: [1, 2, 3, 4]},
      panels: [{
        id: 'main',
        axes: {x: {field: 'x'}, y: {field: 'y'}},
        layers: [{type: 'field2d', x: 'x', y: 'y', z: 'z'}],
      }],
    };

    expect(structuredViewKind(payload)).toBe('density_field');
  });

  it('repairs legacy categorical value plots into one labelled scatter series', () => {
    const payload: ScientificFigurePayload = {
      schema_version: 'ocean-scientific-figure/v4',
      plot_kind: 'categorical',
      data: {case_index: [0, 1, 2], cooling: [-.5, -1, -1.5]},
      panels: [{
        id: 'main',
        axes: {
          x: {field: 'case_index', label: 'case_index'},
          y: {field: 'cooling', label: 'Cooling rate', units: 'K month-1'},
        },
        layers: [{
          type: 'categories', x: 'case_index', y: 'cooling', category: 'cooling',
          labels: {'0': 'h15_dT1', '1': 'h15_dT2', '2': 'h15_dT3'},
        }],
      }],
    };

    const normalized = normalizeScientificFigure(payload);
    expect(normalized.panels[0]?.layers).toMatchObject([{
      type: 'scatter', x: 'case_index_labels', y: 'cooling', label: 'Cooling rate',
    }]);
    expect(normalized.panels[0]?.axes.x).toMatchObject({
      field: 'case_index_labels', scale: 'category', label: 'case index',
    });
    expect(normalized.data.case_index_labels).toEqual(['h15_dT1', 'h15_dT2', 'h15_dT3']);
  });
});
