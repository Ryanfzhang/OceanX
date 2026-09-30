export type ScientificScalar = number | string | null;
import type {ResultCategory, ResultFeature} from './result-features.js';

export type ScientificAxis = {
  field: string;
  label?: string;
  units?: string;
  scale?: 'linear' | 'log' | 'time' | 'category';
  range?: [number, number];
  reverse?: boolean;
  tick_count?: number;
  tick_format?: 'auto' | 'number' | 'date' | 'month' | 'longitude' | 'latitude';
  precision?: number;
  grid?: boolean;
};

export type ScientificLayerStyle = {
  color?: string;
  opacity?: number;
  width?: number;
  dash?: string;
  radius?: number;
  fill?: string;
  fill_opacity?: number;
  palette?: string | string[];
  marker?: 'circle' | 'square' | 'triangle' | 'diamond';
};

export type XYLayer = {
  id?: string;
  type: 'scatter' | 'line';
  x: string;
  y: string;
  color?: string;
  color_scale?: 'linear' | 'log';
  color_domain?: [number, number];
  label?: string;
  style?: ScientificLayerStyle;
};

export type BandLayer = {
  id?: string;
  type: 'band';
  x: string;
  y0: string;
  y1: string;
  label?: string;
  style?: ScientificLayerStyle;
};

export type HeatmapLayer = {
  id?: string;
  type: 'heatmap';
  x: string;
  y: string;
  z: string;
  color_scale?: 'linear' | 'log';
  color_domain?: [number, number];
  label?: string;
  style?: ScientificLayerStyle;
};

export type Field2DLayer = {
  categories?: ResultCategory[];
  id?: string;
  type: 'field2d';
  x: string;
  y: string;
  z: string;
  render?: 'filled_contour' | 'smooth' | 'cells';
  interpolation?: 'linear' | 'nearest';
  levels?: number | number[];
  color_scale?: 'linear' | 'log';
  color_domain?: [number, number];
  label?: string;
  style?: ScientificLayerStyle;
};

export type CategoriesLayer = {
  id?: string;
  type: 'categories';
  x: string;
  y: string;
  category: string;
  labels?: Record<string, string>;
  show_labels?: boolean;
  label?: string;
  style?: ScientificLayerStyle;
};

export type ContourPath = {level: number; points: Array<[number, number]>; label?: string};
export type ContourLayer = {
  id?: string;
  type: 'contour';
  paths: ContourPath[];
  label?: string;
  style?: ScientificLayerStyle;
};

export type AnnotationLayer = {
  id?: string;
  type: 'annotation';
  items: Array<{
    x: number;
    y: number;
    text: string;
    dx?: number;
    dy?: number;
    arrow?: boolean;
    align?: 'start' | 'middle' | 'end';
  }>;
  style?: ScientificLayerStyle;
};

export type ReferenceLayer = {
  id?: string;
  type: 'reference';
  axis: 'x' | 'y';
  value: number;
  label?: string;
  style?: ScientificLayerStyle;
};

export type VectorLayer = {
  id?: string;
  type: 'vector';
  x: string;
  y: string;
  u: string;
  v: string;
  scale?: number;
  label?: string;
  style?: ScientificLayerStyle;
};

export type ScientificLayer =
  | XYLayer
  | BandLayer
  | HeatmapLayer
  | Field2DLayer
  | CategoriesLayer
  | ContourLayer
  | AnnotationLayer
  | ReferenceLayer
  | VectorLayer;

export type ScientificPanelDisplay = {
  legend?: boolean;
  legend_position?: 'top' | 'bottom' | 'inside';
  colorbar?: boolean;
  colorbar_label?: string;
  aspect_ratio?: number;
};

export type ScientificPanel = {
  id: string;
  label?: string;
  title?: string;
  subtitle?: string;
  axes: {x: ScientificAxis; y: ScientificAxis};
  layers: ScientificLayer[];
  grid?: {column?: number; row?: number; column_span?: number; row_span?: number};
  display?: ScientificPanelDisplay;
};

export type ScientificTheme = {
  ink?: string;
  muted?: string;
  grid?: string;
  paper?: string;
  series?: string[];
};

export type ScientificFigurePayload = {
  features?: ResultFeature[];
  schema_version: 'ocean-scientific-figure/v4';
  plot_kind: string;
  title?: string;
  subtitle?: string;
  caption?: string;
  data: Record<string, ScientificScalar[]>;
  layout?: {columns?: 1 | 2 | 3; gap?: number};
  panels: ScientificPanel[];
  theme?: ScientificTheme;
  spatial_context?: unknown;
};

export type ScientificPayload = ScientificFigurePayload;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function isScientificPayload(value: unknown): value is ScientificPayload {
  if (!isRecord(value) || typeof value.plot_kind !== 'string' || !isRecord(value.data)) return false;
  if (value.schema_version === 'ocean-scientific-figure/v4') {
    return Array.isArray(value.panels) && value.panels.length > 0;
  }
  return false;
}

const ISO_TIME = /^\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+Z?)?$/;

const DISPLAY_UNITS: Record<string, string> = {
  degrees_C: '°C',
  degree_C: '°C',
  degC: '°C',
  'degrees_C m': '°C·m',
  'degree_C m': '°C·m',
  'degC m': '°C·m',
  degrees_north: '°N',
  degrees_east: '°E',
};

export function conciseScientificLabel(value: string, maxLength = 52): string {
  const normalized = value
    .replace(/degrees_C|degree_C|degC/g, '°C')
    .replaceAll('_', ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (normalized.length <= maxLength) return normalized;
  const available = Math.max(12, maxLength - 1);
  const candidate = normalized.slice(0, available + 1);
  const boundary = candidate.lastIndexOf(' ');
  return `${candidate.slice(0, boundary >= available * .62 ? boundary : available).trimEnd()}…`;
}

export function scientificDisplayUnits(value?: string): string {
  const units = value?.trim() ?? '';
  if (units.startsWith('day_of_year_')) return `${units.slice('day_of_year_'.length)} DOY`;
  return DISPLAY_UNITS[units] ?? units.replaceAll('_', ' ');
}

function inferredAxis(axis: ScientificAxis, data: Record<string, ScientificScalar[]>): ScientificAxis {
  if (axis.scale === 'time' || axis.scale === 'category' || axis.scale === 'log') return axis;
  const values = (data[axis.field] ?? []).filter((value): value is string => typeof value === 'string');
  if (values.length < 2 || !values.every((value) => ISO_TIME.test(value) && Number.isFinite(Date.parse(value)))) return axis;
  return {...axis, scale: 'time', tick_format: axis.tick_format ?? 'date'};
}

export function normalizeScientificFigure(payload: ScientificPayload): ScientificFigurePayload {
  const data = {...payload.data};
  const normalizeLayers = (layers: ScientificLayer[]): ScientificLayer[] => layers.map((original) => {
    const layer: ScientificLayer = original.type === 'heatmap' ? {
      ...original,
      type: 'field2d',
      render: 'filled_contour',
      interpolation: 'linear',
      levels: 18,
    } : original;



    // A short ordered vertical profile is a continuous sampled curve.  Treating
    // it as an unconnected cloud loses the scientific relationship.  Large or
    // colour-coded profile samples remain scatter by design.
    if (
      payload.plot_kind === 'profile'
      && layer.type === 'scatter'
      && (data[layer.x]?.length ?? 0) >= 2
      && (data[layer.x]?.length ?? 0) <= 1_000
    ) {
      const style = {...layer.style};
      delete style.radius;
      delete style.marker;
      return {
        ...layer,
        type: 'line',
        style: {...style, width: layer.style?.width ?? 2.25},
      };
    }
    return layer;
  });
  const panels = payload.panels.map((panel) => {
    const axes = {x: inferredAxis(panel.axes.x, data), y: inferredAxis(panel.axes.y, data)};
    let layers = normalizeLayers(panel.layers);
    const onlyLayer = layers.length === 1 ? layers[0] : undefined;
    if (
      payload.plot_kind === 'categorical'
      && onlyLayer?.type === 'categories'
      && onlyLayer.category === onlyLayer.y
      && onlyLayer.labels
    ) {
      const source = data[onlyLayer.x] ?? [];
      const labels = source.map((value) => onlyLayer.labels?.[String(value)] ?? String(value));
      const hasRealLabels = labels.some((label, index) => label !== String(source[index]));
      if (source.length && hasRealLabels) {
        let labelField = `${onlyLayer.x}_labels`;
        while (labelField in data) labelField += '_category';
        data[labelField] = labels;
        axes.x = {
          ...axes.x,
          field: labelField,
          scale: 'category',
          label: axes.x.label?.replaceAll('_', ' ') || 'Case',
          units: undefined,
        };
        layers = [{
          id: onlyLayer.id,
          type: 'scatter',
          x: labelField,
          y: onlyLayer.y,
          label: axes.y.label ?? 'Values',
          style: {radius: 3.6, opacity: .92, marker: 'circle'},
        }];
      }
    }
    return {...panel, axes, layers};
  });
  return {
    ...payload,
    data,
    panels,
  };
}
