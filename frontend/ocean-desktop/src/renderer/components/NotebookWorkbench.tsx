import {Download, LoaderCircle, NotebookTabs, X} from 'lucide-react';

import {useUiLanguage} from '../i18n.js';
import {MessageMarkdown} from '../message-markdown.js';
import type {ResultDocument} from '../types.js';

export type NotebookCell = {
  cell_type: string;
  source?: string[] | string;
  execution_count?: number | null;
  outputs?: Array<{output_type?: string; name?: string; text?: string[] | string}>;
};

const joined = (value: string[] | string | undefined): string => Array.isArray(value) ? value.join('') : value ?? '';

/** The code every agent ran for one request, with what it printed (request_notebook.py), and its download. */
export function NotebookWorkbench({document, loading, error, cells, downloadUrl, onClose}: {
  document: ResultDocument | null;
  loading: boolean;
  error: string | null;
  cells: NotebookCell[];
  downloadUrl: string | null;
  onClose: () => void;
}): React.JSX.Element {
  const {text: uiText} = useUiLanguage();
  const runs = typeof document?.content?.runs === 'number' ? document.content.runs : null;
  return <aside className="result-workbench notebook-workbench" aria-label={uiText('Analysis notebook', '分析 notebook')}>
    <header>
      <div><NotebookTabs size={18} /><span><strong>{uiText('Analysis notebook', '分析 notebook')}</strong>
        <small>{runs === null ? 'analysis.ipynb' : uiText(`${runs} code runs · analysis.ipynb`, `${runs} 次运行 · analysis.ipynb`)}</small></span></div>
      <div className="notebook-actions">
        {downloadUrl ? <a href={downloadUrl} download="analysis.ipynb"><Download size={14} />{uiText('Download', '下载')}</a> : null}
        <button type="button" onClick={onClose} title={uiText('Close', '关闭')} aria-label={uiText('Close', '关闭')}><X size={17} /></button>
      </div>
    </header>
    <div className="result-workbench-body">
      {loading ? <div className="workbench-empty"><LoaderCircle className="spin" size={30} /><p>{uiText('Loading the notebook…', '正在载入 notebook…')}</p></div>
        : error ? <div className="workbench-error"><strong>{uiText('Notebook unavailable', 'notebook 无法打开')}</strong><p>{error}</p></div>
        : <div className="notebook-scroll">{cells.map((cell, index) => cell.cell_type === 'markdown'
          ? <div key={index} className="notebook-markdown"><MessageMarkdown content={joined(cell.source)} /></div>
          : <div key={index} className="notebook-code">
            <span className="notebook-prompt">[{cell.execution_count ?? ' '}]</span>
            <div>
              <pre className="notebook-source"><code>{joined(cell.source)}</code></pre>
              {(cell.outputs ?? []).map((output, number) => <pre key={number}
                className={output.name === 'stderr' ? 'notebook-output stderr' : 'notebook-output'}>{joined(output.text)}</pre>)}
            </div>
          </div>)}</div>}
    </div>
  </aside>;
}
