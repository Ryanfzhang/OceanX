import {useEffect, useRef, useState} from 'react';
import {FileText, FolderPlus, LoaderCircle, Plus} from 'lucide-react';

import type {WorkspaceSourceKind} from '../../shared/bridge.js';
import {useUiLanguage} from '../i18n.js';

/** The + button of the composer and the welcome box: a PDF or a data folder. */
export function SourceMenu({
  disabled = false,
  busy = false,
  placement = 'up',
  onChoose,
}: {
  disabled?: boolean;
  busy?: boolean;
  placement?: 'up' | 'down';
  onChoose: (kind: WorkspaceSourceKind) => void;
}): React.JSX.Element {
  const {text} = useUiLanguage();
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);
  const choose = (kind: WorkspaceSourceKind) => {
    setOpen(false);
    onChoose(kind);
  };
  const label = busy ? text('Adding source…', '正在添加来源…') : text('Add a PDF or a data folder', '添加 PDF 或数据文件夹');
  return <div className="source-menu-anchor" ref={anchorRef}>
    <button
      type="button"
      className="source-menu-button"
      disabled={disabled || busy}
      aria-busy={busy}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={label}
      title={label}
      onClick={() => setOpen((value) => !value)}
    >{busy ? <LoaderCircle className="spin" size={17} /> : <Plus size={19} />}</button>
    {open ? <div className={`source-menu${placement === 'down' ? ' down' : ''}`} role="menu">
      <button type="button" role="menuitem" onClick={() => choose('pdf')}><FileText size={16} />{text('Add PDF', '添加 PDF')}</button>
      <button type="button" role="menuitem" onClick={() => choose('data')}><FolderPlus size={16} />{text('Add data folder', '添加数据文件夹')}</button>
    </div> : null}
  </div>;
}
