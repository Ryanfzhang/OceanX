import {Component, useRef, useState, type ReactNode} from 'react';
import {BarChart3, Image as ImageIcon, LoaderCircle, Maximize2, Minus, Plus, X} from 'lucide-react';
import type {FeatureCollection, Geometry} from 'geojson';
import type {ResultCategory} from './result-features.js';

import {asRecord} from '../app-utils.js';
import type {ArtifactVersion, EventPayload} from '../types.js';
import {
  isScientificPayload,
  ScientificView,
  type ScientificPayload,
} from './ScientificView.js';

export type SpatialContext = {
  region_key: string;
  bounds?: [number, number, number, number];
  fit_policy?: 'region_change' | 'always' | 'never';
  features?: FeatureCollection<Geometry>;
};

export type SpatialPayload = {
  schema_version: 'ocean-interactive-spatial/v1';
  view_kind: 'spatial_map';
  variable: string;
  units: string;
  longitude: number[];
  latitude: number[];
  values: Array<Array<number | null>>;
  bounds: [number, number, number, number];
  colorbar?: EventPayload;
  categories?: ResultCategory[];
  rendering?: {
    kind?: 'continuous' | 'categorical';
    render?: 'filled_contour' | 'smooth' | 'cells';
    interpolation?: 'linear' | 'nearest';
    levels?: number | number[];
  };
  spatial_context?: SpatialContext;
};

export type StructuredPayload = ScientificPayload;

type ResultRenderBoundaryProps = {children: ReactNode; resetKey?: string};
type ResultRenderBoundaryState = {failed: boolean};

/** Keep one malformed or unexpectedly large result from unmounting the whole
 * desktop renderer. Selecting another result resets the isolated surface.
 */
export class ResultRenderBoundary extends Component<ResultRenderBoundaryProps, ResultRenderBoundaryState> {
  state: ResultRenderBoundaryState = {failed: false};

  static getDerivedStateFromError(): ResultRenderBoundaryState {
    return {failed: true};
  }

  componentDidUpdate(previous: ResultRenderBoundaryProps): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({failed: false});
  }

  render(): ReactNode {
    if (this.state.failed) return <div className="workbench-error" role="alert"><strong>View could not be rendered</strong><p>The saved result is still available; close this view or open another result.</p></div>;
    return this.props.children;
  }
}

export function isSpatial(value: unknown): value is SpatialPayload {
  const payload = asRecord(value);
  return payload.schema_version === 'ocean-interactive-spatial/v1'
    && payload.view_kind === 'spatial_map'
    && Array.isArray(payload.longitude)
    && Array.isArray(payload.latitude)
    && Array.isArray(payload.values);
}

export function isStructured(value: unknown): value is StructuredPayload {
  return isScientificPayload(value);
}

export function structuredViewKind(payload: StructuredPayload): string {
  const layers = payload.panels.flatMap((panel) => panel.layers);
  if (layers.some((layer) => layer.type === 'categories')) return 'classified_samples';
  if (payload.plot_kind === 'scatter' && layers.some((layer) => layer.type === 'field2d' || layer.type === 'heatmap')) return 'density_field';
  return payload.plot_kind;
}

const VIEW_LABELS: Record<string, string> = {
  spatial_map: 'Map', time_series: 'Time series', profile: 'Vertical profile',
  scatter: 'Scatter plot', ts_diagram: 'T–S diagram', section: 'Section',
  hovmoller: 'Hovmöller diagram', density_field: 'Density field',
  classified_samples: 'Classified samples',
};

export function viewLabel(kind: string | undefined): string {
  return kind ? VIEW_LABELS[kind] ?? kind.replaceAll('_', ' ') : 'Interactive result';
}

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1_000 || (Math.abs(value) > 0 && Math.abs(value) < .01)) return value.toExponential(3);
  return value.toFixed(3).replace(/\.0+$|(?<=\.[0-9]*?)0+$/g, '');
}

function SpatialView({payload, previewUrl}: {payload: SpatialPayload; previewUrl: string | null}): React.JSX.Element {
  const imageRef = useRef<HTMLImageElement>(null);
  const [hover, setHover] = useState<{lon: number; lat: number; value: number | null} | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({x: 0, y: 0});
  const dragRef = useRef<{x: number; y: number; startX: number; startY: number} | null>(null);
  const [west, south, east, north] = payload.bounds;
  const updateHover = (clientX: number, clientY: number) => {
    const image = imageRef.current;
    if (!image) return;
    const rect = image.getBoundingClientRect();
    const x = (clientX - rect.left) / rect.width;
    const y = (clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return setHover(null);
    const column = Math.min(payload.longitude.length - 1, Math.max(0, Math.floor(x * payload.longitude.length)));
    const row = Math.min(payload.latitude.length - 1, Math.max(0, Math.floor(y * payload.latitude.length)));
    setHover({
      lon: payload.longitude[column] ?? west + (east - west) * x,
      lat: payload.latitude[row] ?? north - (north - south) * y,
      value: payload.values[row]?.[column] ?? null,
    });
  };
  return <div className="spatial-view-stage"
    onPointerMove={(event) => {
      if (dragRef.current) {
        setOffset({x: dragRef.current.startX + event.clientX - dragRef.current.x, y: dragRef.current.startY + event.clientY - dragRef.current.y});
        setHover(null);
      } else updateHover(event.clientX, event.clientY);
    }}
    onPointerUp={() => {dragRef.current = null;}}
    onPointerLeave={() => {dragRef.current = null; setHover(null);}}
  >
    <div className="view-controls" role="group" aria-label="Interactive view controls">
      <button onClick={() => setScale((value) => Math.min(5, value + .35))} title="Zoom in"><Plus size={15} /></button>
      <button onClick={() => setScale((value) => Math.max(1, value - .35))} title="Zoom out"><Minus size={15} /></button>
      <button onClick={() => {setScale(1); setOffset({x: 0, y: 0});}} title="Reset view"><Maximize2 size={15} /></button>
    </div>
    {previewUrl ? <img ref={imageRef} src={previewUrl} alt={`${payload.variable} interactive spatial field`} draggable={false}
      style={{transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`}}
      onPointerDown={(event) => {
        if (scale <= 1) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = {x: event.clientX, y: event.clientY, startX: offset.x, startY: offset.y};
      }}
    /> : <div className="view-preview-missing"><ImageIcon size={30} /><p>Preview is unavailable, but the value grid is loaded.</p></div>}
    <div className="coordinate-corners"><span>{north.toFixed(2)}°N</span><span>{south.toFixed(2)}°N</span></div>
    {hover ? <output className="spatial-hover-readout"><strong>{payload.variable}</strong><span>{formatNumber(hover.lon)}° · {formatNumber(hover.lat)}°</span><b>{hover.value === null ? 'No data' : `${formatNumber(hover.value)} ${payload.units}`}</b></output> : null}
  </div>;
}



export function StructuredView({payload, compactHeader = false, featureId}: {payload: StructuredPayload; compactHeader?: boolean; featureId?: string}): React.JSX.Element {
  return <ScientificView payload={payload} compactHeader={compactHeader} featureId={featureId} />;
}

export function InteractiveViewWorkbench({artifact, loading, data, previewUrl, error, onClose}: {
  artifact: ArtifactVersion | null;
  loading: boolean;
  data: unknown;
  previewUrl: string | null;
  error: string | null;
  onClose: () => void;
}): React.JSX.Element {
  const kind = isSpatial(data) ? data.view_kind : isStructured(data) ? data.plot_kind : typeof artifact?.content?.view_kind === 'string' ? artifact.content.view_kind : undefined;
  return <aside className="result-workbench" aria-label="Result workbench">
    <header><div><BarChart3 size={18} /><span><strong>Result workbench</strong><small>{artifact ? `${viewLabel(kind)} · ${artifact.title}` : 'Select an interactive result'}</small></span></div>{artifact ? <button onClick={onClose} title="Close workbench"><X size={17} /></button> : null}</header>
    <div className="result-workbench-body">
      {!artifact ? <div className="workbench-empty"><BarChart3 size={38} /><h2>Explore research results</h2><p>Open a map or scientific chart from an OceanX answer.</p></div> : loading ? <div className="workbench-empty"><LoaderCircle className="spin" size={30} /><p>Loading the immutable result…</p></div> : error ? <div className="workbench-error"><strong>View unavailable</strong><p>{error}</p></div> : isSpatial(data) ? <SpatialView payload={data} previewUrl={previewUrl} /> : isStructured(data) ? <ResultRenderBoundary key={`${artifact.ref.artifact_id}@${artifact.ref.version}`} resetKey={`${artifact.ref.artifact_id}@${artifact.ref.version}`}><StructuredView payload={data} /></ResultRenderBoundary> : <div className="workbench-error"><strong>Unsupported result payload</strong><p>The saved result does not match the current scientific view contract.</p></div>}
      {artifact ? <footer><span>{artifact.summary}</span><code>{artifact.ref.artifact_id}@v{artifact.ref.version}</code></footer> : null}
    </div>
  </aside>;
}
