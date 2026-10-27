import {Download, Table2, X} from 'lucide-react';

import {useUiLanguage} from '../i18n.js';
import type {ResultDocument} from '../types.js';

/** Preview the saved strings as a table; Download always returns the original file. */
export function DataWorkbench({document, loading, error, downloadUrl, onClose}: {
  document: ResultDocument;
  loading: boolean;
  error: string | null;
  downloadUrl: string | null;
  onClose: () => void;
}): React.JSX.Element {
  const {text} = useUiLanguage();
  const columns = document.content.columns as string[] | undefined;
  const rows = document.content.rows as string[][] | undefined;
  const previewError = document.content.preview_error as string | undefined;
  const netcdf = String(document.content.data_file ?? '').toLowerCase().endsWith('.nc');
  const width = Math.max(columns?.length ?? 0, ...((rows ?? []).map(row => row.length)));
  return <aside className="result-workbench data-workbench" aria-label={text('Data preview', '数据预览')}>
    <header>
      <div><Table2 size={18} /><strong>{document.title}</strong></div>
      <div className="notebook-actions">
        {downloadUrl && !netcdf ? <a href={downloadUrl} download><Download size={14} />{text('Download', '下载')}</a> : null}
        <button type="button" onClick={onClose} aria-label={text('Close', '关闭')}><X size={17} /></button>
      </div>
    </header>
    <div className="result-workbench-body">
      {loading ? <p role="status">{text('Loading…', '正在加载…')}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {previewError ? <p>{netcdf ? text('Metadata preview is unavailable. NetCDF download is disabled.', '无法预览元数据，不提供 NetCDF 文件下载。') : text('Table preview unavailable; download the original file.', '无法预览表格，可下载原文件。')}</p> : null}
      {rows && columns ? <>
        <p>{netcdf ? text('Variables and dimensions · NetCDF download is disabled.', '变量与维度 · 不提供 NetCDF 文件下载。') : document.content.truncated
          ? text('Preview: first 200 rows. Download for all rows.', '预览前 200 行，下载可获取全部内容。')
          : text(`${rows.length} rows`, `${rows.length} 行`)}</p>
        <div className="data-table-scroll"><table>
          <thead><tr>{Array.from({length: width}, (_, index) => <th key={index} scope="col">{columns[index] || text(`Column ${index + 1}`, `第 ${index + 1} 列`)}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}>{Array.from({length: width}, (_, column) => <td key={column}>{row[column] ?? ''}</td>)}</tr>)}</tbody>
        </table></div>
      </> : !previewError ? <p>{text('No table preview is available.', '没有可用的表格预览。')}</p> : null}
    </div>
  </aside>;
}
