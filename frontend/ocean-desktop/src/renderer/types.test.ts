import {describe, expect, it} from 'vitest';

import {staticFigureImage} from './types.js';
import type {TaskResultFile, TaskResultRecord} from './types.js';

const file = (path: string, mime_type: string): TaskResultFile => ({path, mime_type, size: 10, sha256: 'a'.repeat(64)});
const figure = (content: Record<string, unknown>, files: TaskResultFile[]): TaskResultRecord => ({
  result_ref: {task_id: 'task', result_id: 'figure_fig2', version: 1},
  workspace_id: 'ws',
  kind: 'file',
  title: 'fig2',
  summary: '',
  created_at: '2026-10-31T10:00:00Z',
  content: {render_status: 'static', ...content},
  files,
});

describe('staticFigureImage', () => {
  it('shows a PDF figure through its large picture, its preview only where there is none', () => {
    const pdf = file('fig2.pdf', 'application/pdf');
    const preview = file('preview.png', 'image/png');
    const display = file('display.png', 'image/png');
    // The preview is kept small enough for an agent to open, so a dense figure is blurred in it.
    expect(staticFigureImage(figure({preview_file: 'preview.png', display_file: 'display.png'}, [pdf, preview, display]))).toBe(display);
    expect(staticFigureImage(figure({preview_file: 'preview.png'}, [pdf, preview]))).toBe(preview);
    expect(staticFigureImage(figure({preview_file: 'fig2.pdf'}, [pdf]))).toBeUndefined();
  });

  it('shows a saved picture as itself', () => {
    const png = file('fig2.png', 'image/png');
    expect(staticFigureImage(figure({preview_file: 'fig2.png'}, [png]))).toBe(png);
  });
});
