import type {WorkspaceSourceSelection} from '../../ocean-desktop/src/shared/bridge.js';

const MAX_PDF_BYTES = 25 * 1024 * 1024;

export function chooseSource(): Promise<WorkspaceSourceSelection | null> {
  // Settings updates html.lang; the picker uses the same selection.
  const chinese = document.documentElement.lang.startsWith('zh');
  const text = (english: string, zh: string) => chinese ? zh : english;
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'web-source-dialog';
    dialog.setAttribute('aria-label', text('Add data or a paper', '添加数据或论文'));
    const form = document.createElement('form');
    const modes = document.createElement('div');
    modes.className = 'web-source-modes';
    const pathMode = document.createElement('button');
    pathMode.type = 'button'; pathMode.textContent = text('Server path', '服务器路径');
    const pdfMode = document.createElement('button');
    pdfMode.type = 'button'; pdfMode.textContent = text('Upload PDF', '上传 PDF');
    modes.append(pathMode, pdfMode);

    const pathPanel = document.createElement('section');
    const label = document.createElement('label');
    label.textContent = text('Absolute path to a server file or folder', '服务器文件或文件夹的绝对路径');
    const input = document.createElement('input');
    input.name = 'source-path'; input.autocomplete = 'off';
    input.placeholder = text('/srv/ocean-data/ or /srv/ocean-data/file.nc', '/srv/ocean-data/ 或 /srv/ocean-data/file.nc');
    label.append(input);
    const note = document.createElement('p');
    note.textContent = text('Supports data files, PDFs and folders already on the server. Sources are referenced read-only.',
      '支持服务器上已有的数据文件、PDF 或文件夹，以只读方式引用。');
    pathPanel.append(label, note);

    const pdfPanel = document.createElement('section');
    const file = document.createElement('input');
    file.type = 'file'; file.accept = '.pdf,application/pdf'; file.hidden = true;
    const choose = document.createElement('button');
    choose.type = 'button'; choose.textContent = text('Choose PDF…', '选择 PDF…');
    choose.onclick = () => file.click();
    const filename = document.createElement('p');
    filename.setAttribute('aria-live', 'polite');
    filename.textContent = text('No PDF selected', '尚未选择 PDF');
    file.onchange = () => {filename.textContent = file.files?.[0]?.name ?? text('No PDF selected', '尚未选择 PDF');};
    const pdfNote = document.createElement('p');
    pdfNote.textContent = text('Choose a PDF from this computer (up to 25 MB). A copy will be uploaded and attached to this task.',
      '从本机选择 PDF（最大 25 MB），上传副本并添加到当前任务。');
    pdfPanel.append(file, choose, filename, pdfNote);

    const error = document.createElement('p'); error.setAttribute('role', 'alert');
    const actions = document.createElement('div');
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.textContent = text('Cancel', '取消');
    const submit = document.createElement('button'); submit.type = 'submit';
    actions.append(cancel, submit);
    form.append(modes, pathPanel, pdfPanel, error, actions); dialog.append(form);
    let upload = false, settled = false;
    const controller = new AbortController();
    const setMode = (pdf: boolean) => {
      upload = pdf; pathPanel.hidden = pdf; pdfPanel.hidden = !pdf;
      input.required = !pdf; input.disabled = pdf;
      pathMode.setAttribute('aria-pressed', String(!pdf));
      pdfMode.setAttribute('aria-pressed', String(pdf));
      submit.textContent = pdf ? text('Upload and add', '上传并添加') : text('Add', '添加');
      error.textContent = '';
      (pdf ? choose : input).focus();
    };
    pathMode.onclick = () => setMode(false); pdfMode.onclick = () => setMode(true);
    const finish = (value: WorkspaceSourceSelection | null) => {
      if (settled) return;
      settled = true; controller.abort(); dialog.close(); dialog.remove(); resolve(value);
    };
    cancel.onclick = () => finish(null);
    dialog.addEventListener('cancel', (event) => {event.preventDefault(); finish(null);});
    form.onsubmit = async (event) => {
      event.preventDefault(); error.textContent = '';
      const selected = file.files?.[0];
      if (upload && (!selected || !selected.name.toLowerCase().endsWith('.pdf') || !selected.size)) {
        error.textContent = text('Choose a PDF file first.', '请先选择 PDF 文件。'); return;
      }
      if (upload && selected!.size > MAX_PDF_BYTES) {
        error.textContent = text('The PDF must be 25 MB or smaller.', 'PDF 不能超过 25 MB。'); return;
      }
      submit.disabled = pathMode.disabled = pdfMode.disabled = choose.disabled = true;
      submit.textContent = upload ? text('Uploading…', '正在上传…') : text('Adding…', '正在添加…');
      try {
        const response = await fetch(upload ? '/api/papers' : '/api/source', {
          method: 'POST', signal: controller.signal,
          headers: upload ? {'Content-Type': 'application/pdf', 'X-Filename': encodeURIComponent(selected!.name)}
            : {'Content-Type': 'application/json'},
          body: upload ? selected! : JSON.stringify({path: input.value.trim()}),
        });
        if (!response.ok) {
          error.textContent = upload
            ? response.status === 413 ? text('The PDF must be 25 MB or smaller.', 'PDF 不能超过 25 MB。')
              : text('Could not upload this PDF. Check the file and try again.', 'PDF 上传失败，请检查文件后重试。')
            : text('This file or folder is unavailable or outside the allowed server directories. Check the path.',
              '该文件或文件夹不可用，或不在服务器允许的目录内，请核对路径。');
          return;
        }
        finish(await response.json() as WorkspaceSourceSelection);
      } catch {
        if (!settled) error.textContent = text('Connection failed. Please try again.', '连接失败，请重试。');
      } finally {
        submit.disabled = pathMode.disabled = pdfMode.disabled = choose.disabled = false;
        submit.textContent = upload ? text('Upload and add', '上传并添加') : text('Add', '添加');
      }
    };
    document.body.append(dialog); dialog.showModal(); setMode(false);
  });
}
