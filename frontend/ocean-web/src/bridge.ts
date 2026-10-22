import {chooseSource} from './source-picker.js';
import type {
  BackendFrame, DesktopBackendStatus, ModelProviderStatus, OceanDesktopBridge,
} from '../../ocean-desktop/src/shared/bridge.js';

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

export async function installWebBridge(): Promise<void> {
  const initial = await configuration();
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
    chooseWorkspaceSource: chooseSource,
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
    getMapConfig: async () => initial.map ?? {cartoKey: ''},
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
