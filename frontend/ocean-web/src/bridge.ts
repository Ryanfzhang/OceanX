import type {
  BackendFrame, DesktopBackendStatus, ModelProviderStatus, OceanDesktopBridge,
  WorkspaceSourceSelection,
} from '../../ocean-desktop/src/shared/bridge.js';
import {configureWebBasemap} from './basemap.js';

type Configuration = {
  project: {path: string; name: string};
  provider: ModelProviderStatus;
  backend: DesktopBackendStatus;
  map?: {cartoKey: string};
};

async function configuration(): Promise<Configuration> {
  const response = await fetch('/api/config', {cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error('The server workspace is unavailable.');
  return response.json() as Promise<Configuration>;
}

function choosePath(): Promise<WorkspaceSourceSelection | null> {
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'web-source-dialog';
    const form = document.createElement('form');
    const label = document.createElement('label');
    label.textContent = '服务器数据或 PDF 的绝对路径 / Server source path';
    const input = document.createElement('input');
    input.name = 'source-path'; input.required = true; input.autocomplete = 'off';
    input.placeholder = '/srv/ocean-data/file.nc 或 /srv/papers/paper.pdf';
    label.append(input);
    const note = document.createElement('p');
    note.textContent = '只读引用已有文件或目录，不上传、不列出服务器文件。';
    const error = document.createElement('p');
    error.setAttribute('role', 'alert');
    const actions = document.createElement('div');
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.textContent = '取消 / Cancel';
    const submit = document.createElement('button');
    submit.type = 'submit'; submit.textContent = '添加 / Add';
    actions.append(cancel, submit); form.append(label, note, error, actions); dialog.append(form);
    let settled = false;
    const finish = (value: WorkspaceSourceSelection | null) => {
      if (settled) return;
      settled = true; dialog.close(); dialog.remove(); resolve(value);
    };
    cancel.onclick = () => finish(null);
    dialog.addEventListener('cancel', (event) => {event.preventDefault(); finish(null);});
    form.onsubmit = async (event) => {
      event.preventDefault(); submit.disabled = true; error.textContent = '';
      try {
        const response = await fetch('/api/source', {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: input.value.trim()})});
        if (!response.ok) {
          error.textContent = '该来源不可用或不在服务器允许的目录内，请核对路径。';
          return;
        }
        finish(await response.json() as WorkspaceSourceSelection);
      } catch {error.textContent = '连接失败，请重试。';}
      finally {submit.disabled = false;}
    };
    document.body.append(dialog); dialog.showModal(); input.focus();
  });
}

export async function installWebBridge(): Promise<void> {
  const initial = await configuration();
  configureWebBasemap(initial.map?.cartoKey ?? '');
  const listeners = new Set<(frame: BackendFrame) => void>();
  let socket: WebSocket | null = null;
  let closed = false;
  let first = true;
  let retry: ReturnType<typeof setTimeout> | null = null;
  const emit = (frame: BackendFrame) => listeners.forEach((listener) => listener(frame));
  let connectReady!: () => void;
  const connected = new Promise<void>((resolve) => {connectReady = resolve;});
  const connect = () => {
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/protocol`);
    socket.onopen = () => {
      if (first) {first = false; connectReady(); return;}
      void configuration().then((config) => {
        const ready = config.backend.readyEvent;
        if (ready) emit({kind: 'event', payload: {...ready, event_id: `web_reconnect_${crypto.randomUUID()}`}});
      }).catch(() => undefined);
    };
    socket.onmessage = (event) => {
      try {emit(JSON.parse(String(event.data)) as BackendFrame);}
      catch {emit({kind: 'diagnostic', message: 'The server returned an invalid frame.'});}
    };
    socket.onclose = () => {
      if (closed) return;
      emit({kind: 'diagnostic', message: '连接暂时中断，后台任务继续；正在重连…'});
      retry = setTimeout(connect, 1500);
    };
  };
  connect();
  let startupTimeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([connected, new Promise<never>((_, reject) => {
      startupTimeout = setTimeout(() => reject(new Error(
        '无法连接工作区。请检查 SSH 转发，或刷新重试 / Cannot connect to the workspace. Check the SSH tunnel or reload.'
      )), 15000);
    })]);
  } catch (error) {
    closed = true;
    if (retry) clearTimeout(retry);
    (socket as WebSocket | null)?.close();
    throw error;
  } finally {
    clearTimeout(startupTimeout);
  }
  const unavailable = async (): Promise<never> => {
    throw new Error('此设置由服务器启动配置管理 / Configure this on the server.');
  };
  const updates = {configured: false, state: 'unavailable' as const};
  const bridge: OceanDesktopBridge = {
    chooseWorkspace: async () => initial.project.path,
    listProjects: async () => [{...initial.project, lastOpenedAt: Date.now()}],
    forgetProject: async () => [{...initial.project, lastOpenedAt: Date.now()}],
    chooseWorkspaceSource: choosePath,
    stageImageAttachment: unavailable,
    startBackend: async () => {
      const config = await configuration();
      if (config.backend.readyEvent) setTimeout(() => emit({kind: 'event',
        payload: {...config.backend.readyEvent!, event_id: `web_open_${crypto.randomUUID()}`}}), 0);
      return config.backend;
    },
    stopBackend: async () => undefined,
    getBackendStatus: async () => (await configuration()).backend,
    getModelProviderStatus: async () => (await configuration()).provider,
    configureModelProvider: unavailable,
    sendBackendFrame: async (frame) => {
      if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('正在重连，请稍后重试。');
      socket.send(JSON.stringify(frame));
    },
    openArtifactResource: async (url) => {
      if (!url.startsWith('/api/resources/')) throw new Error('Result resource is unavailable.');
      const link = document.createElement('a');
      link.href = `${url}?download=1`; link.download = ''; document.body.append(link); link.click(); link.remove();
      return {opened: true, revealed: false};
    },
    revealPortableExport: unavailable,
    getUpdateStatus: async () => updates,
    checkForUpdate: async () => updates,
    installPreparedUpdate: async () => updates,
    onBackendFrame: (listener) => {listeners.add(listener); return () => listeners.delete(listener);},
  };
  (window as unknown as {oceanDesktop: OceanDesktopBridge}).oceanDesktop = bridge;
  window.addEventListener('beforeunload', () => {closed = true; if (retry) clearTimeout(retry); socket?.close();});
}
