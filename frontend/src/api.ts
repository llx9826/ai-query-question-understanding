import type { PublicationResult, PublicationSummary, Session, Snapshot, Workspace } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export const getToken = () => sessionStorage.getItem('aiq-access-token') || 'demo-local-key';
export const setToken = (value: string) => sessionStorage.setItem('aiq-access-token', value);

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/ui-api${path}`, {
      method, headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new ApiError(0, '连接暂时中断。请求可能仍在后台执行，请恢复连接查看结果，避免重复提问。');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status,
    typeof data.detail === 'string' ? data.detail : '请求未成功，请检查连接或输入。');
  return data as T;
}

async function managementRequest<T>(path: string, method = 'GET', body?: FormData | unknown): Promise<T> {
  let response: Response;
  try {
    const multipart = body instanceof FormData;
    response = await fetch(`/api/v1${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(multipart || body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
      signal: AbortSignal.timeout(120000),
    });
  } catch {
    throw new ApiError(0, '数据发布连接中断。请刷新数据状态后再决定是否重试。');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(
    response.status,
    typeof data.detail === 'string' ? data.detail : '数据操作未成功。',
  );
  return data as T;
}

const params = (agent: string) => `agent_id=${encodeURIComponent(agent)}`;
const sessionPath = (id: string) => `/sessions/${encodeURIComponent(id)}`;
export const api = {
  bootstrap: () => request<Workspace>('/bootstrap', 'POST'),
  sessions: (agent: string) => request<{ sessions: Session[] }>(`/sessions?${params(agent)}`),
  create: (agent_id: string, name: string, workspace_id: string) => request<{ session_id: string }>(
    '/sessions', 'POST', { agent_id, name, workspace_id }),
  rename: (id: string, agent_id: string, name: string) => request(sessionPath(id), 'PATCH', { agent_id, name }),
  snapshot: (id: string, agent: string, before?: string) => request<Snapshot>(
    `${sessionPath(id)}/snapshot?${params(agent)}${before ? `&before=${encodeURIComponent(before)}` : ''}`),
  send: (id: string, agent_id: string, question: string, message_id: string) => request(
    `${sessionPath(id)}/chat`, 'POST', { agent_id, question, message_id }),
  interrupt: (id: string, agent: string) => request(`${sessionPath(id)}/interrupt?${params(agent)}`, 'POST'),
  datasets: (workspace: string) => managementRequest<PublicationResult | null>(
    `/workspaces/${encodeURIComponent(workspace)}/datasets`),
  publications: (workspace: string) => managementRequest<PublicationSummary[]>(
    `/workspaces/${encodeURIComponent(workspace)}/publications`),
  upload: (workspace: string, files: File[]) => {
    const body = new FormData();
    files.forEach(file => body.append('files', file));
    return managementRequest<PublicationResult>(
      `/workspaces/${encodeURIComponent(workspace)}/uploads`, 'POST', body);
  },
  removeDataset: (workspace: string, dataset: string) => managementRequest<PublicationResult>(
    `/workspaces/${encodeURIComponent(workspace)}/datasets/${encodeURIComponent(dataset)}`, 'DELETE'),
  activatePublication: (workspace: string, publication: string) => managementRequest<PublicationResult>(
    `/workspaces/${encodeURIComponent(workspace)}/publications/${encodeURIComponent(publication)}/activate`, 'POST'),
  addRelationship: (
    workspace: string,
    relationship: {
      left_model: string; left_column: string; right_model: string; right_column: string;
      join_type: 'ONE_TO_ONE' | 'ONE_TO_MANY' | 'MANY_TO_ONE' | 'MANY_TO_MANY';
    },
  ) => managementRequest<PublicationResult>(
    `/workspaces/${encodeURIComponent(workspace)}/relationships`, 'POST', relationship),
};

// crypto.randomUUID 在普通局域网 HTTP 上不可用，getRandomValues 可用。
export function messageId(): string {
  return 'web-' + Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2, '0')).join('');
}
