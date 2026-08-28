/* API 客户端: 统一错误提示; 文档/Excel 下载走原生链接。
   身份: 登录后的用户名存 localStorage, 每个请求经 X-Auth-User 头携带(RBAC 依据)。 */
import type {
  ApiEndpointRow, AuthConfigRow, ChainVerify, ComponentRow, DataAssetRow,
  EvidenceRow, FeatureRow, GateRow, GenerateSummary, GradingQuestion,
  InfraAssetRow, LabelMap, LoginInfo, MatrixEntryIn, PlatformUserRow,
  PreviewResult, ProjectDetail, ProjectInfo, RequirementRow, RoleRow,
  ResourceRow, SurveyAnswer, VulnerabilityRow, WizardState,
} from './types'

export type { MatrixEntryIn }

export const AUTH_STORAGE_KEY = 'secreq.auth.user'

/** 身份变更事件: 顶栏切换身份后, 各页面据此刷新"现在可以做什么"提示。 */
export const IDENTITY_EVENT = 'secreq:identity-changed'

export function getStoredUsername(): string | null {
  return localStorage.getItem(AUTH_STORAGE_KEY)
}

export function storeUsername(username: string | null) {
  if (username) localStorage.setItem(AUTH_STORAGE_KEY, username)
  else localStorage.removeItem(AUTH_STORAGE_KEY)
  window.dispatchEvent(new Event(IDENTITY_EVENT))
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  }
  const user = getStoredUsername()
  if (user) headers['X-Auth-User'] = user
  const resp = await fetch(path, { ...init, headers })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch { /* 非 JSON 错误体, 使用状态码 */ }
    throw new Error(detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export interface Constants {
  [key: string]: LabelMap | string[] | number | Record<string, Record<string, number>>
    | Record<string, { label: string; examples: string }>
}

export const api = {
  constants: () => request<Constants>('/api/meta/constants'),
  gradingQuestions: () =>
    request<{ questions: GradingQuestion[] }>('/api/meta/grading-questions')
      .then((r) => r.questions),

  /* ── 平台身份 ── */
  listUsers: () => request<PlatformUserRow[]>('/api/auth/users'),
  login: (username: string) =>
    request<LoginInfo>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username }) }),

  listProjects: () => request<ProjectDetail[]>('/api/projects'),
  getProject: (id: number) => request<ProjectDetail>(`/api/projects/${id}`),
  createProject: (payload: Partial<ProjectInfo>) =>
    request<ProjectDetail>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  patchProject: (id: number, payload: Partial<ProjectInfo>) =>
    request<ProjectDetail>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  loadWizard: (id: number) => request<WizardState>(`/api/projects/${id}/wizard-state`),

  saveSurvey: (id: number, answers: SurveyAnswer[], finalLevel?: string | null, note?: string | null) => {
    const body = finalLevel
      ? { answers, final_level: finalLevel, manual_adjust_note: note }
      : { answers }
    return request<Record<string, never>>(`/api/projects/${id}/survey`, {
      method: 'POST', body: JSON.stringify(body),
    })
  },
  saveFeatures: (id: number, rows: FeatureRow[]) =>
    request<FeatureRow[]>(`/api/projects/${id}/features`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  saveDataAssets: (id: number, rows: DataAssetRow[]) =>
    request<DataAssetRow[]>(`/api/projects/${id}/data-assets`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  saveMatrix: (id: number, roles: RoleRow[], resources: ResourceRow[], entries: MatrixEntryIn[]) =>
    request<{
      roles: (RoleRow & { id: number })[],
      resources: (ResourceRow & { id: number })[],
      entries: { id: number, role_id: number, resource_id: number, action: string, requires_approval: boolean }[],
      saved: { roles: number, resources: number, entries: number },
    }>(`/api/projects/${id}/matrix`, {
      method: 'POST',
      body: JSON.stringify({ roles, resources, entries }),
    }),
  getAuthDefaults: (id: number) =>
    request<{ grading_level: string; defaults: Record<string, number> }>(`/api/projects/${id}/auth-defaults`),
  saveAuthConfig: (id: number, cfg: AuthConfigRow) =>
    request<AuthConfigRow>(`/api/projects/${id}/auth-config`, {
      method: 'POST', body: JSON.stringify(cfg),
    }),
  saveComponents: (id: number, rows: Omit<ComponentRow, 'vulnerabilities'>[]) =>
    request<ComponentRow[]>(`/api/projects/${id}/components`, {
      method: 'POST', body: JSON.stringify({ components: rows }),
    }),
  listComponents: (id: number) => request<ComponentRow[]>(`/api/projects/${id}/components`),
  importSbomFile: async (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const user = getStoredUsername()
    const resp = await fetch(`/api/projects/${id}/components/import-sbom`, {
      method: 'POST', body: form,
      headers: user ? { 'X-Auth-User': user } : undefined,
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.detail ?? `导入失败 HTTP ${resp.status}`)
    }
    return (await resp.json()) as {
      filename: string, format: string, total_parsed: number, added: number, skipped_duplicate: number,
    }
  },
  saveInventory: (id: number, apiEndpoints: ApiEndpointRow[], infraAssets: InfraAssetRow[]) =>
    request<{ saved: Record<string, number>, api_endpoints: ApiEndpointRow[], infra_assets: InfraAssetRow[] }>(
      `/api/projects/${id}/inventory`,
      { method: 'POST', body: JSON.stringify({ api_endpoints: apiEndpoints, infra_assets: infraAssets }) },
    ),

  previewRequirements: (id: number) =>
    request<PreviewResult>(`/api/projects/${id}/requirements/preview`, { method: 'POST' }),
  generate: (id: number, skipOsv: boolean) =>
    request<GenerateSummary>(`/api/projects/${id}/generate`, {
      method: 'POST', body: JSON.stringify({ skip_osv: skipOsv }),
    }),

  listRequirements: (id: number) => request<RequirementRow[]>(`/api/projects/${id}/requirements`),
  listVulnerabilities: (id: number) => request<VulnerabilityRow[]>(`/api/projects/${id}/vulnerabilities`),
  setRequirementOwner: (id: number, reqId: string, owner: string) =>
    request<RequirementRow>(`/api/projects/${id}/requirements/${reqId}/owner`, {
      method: 'POST', body: JSON.stringify({ owner }),
    }),
  confirmRegulatory: (id: number, reqId: string) =>
    request<RequirementRow>(`/api/projects/${id}/requirements/${reqId}/confirm`, { method: 'POST' }),

  /* ── 评审门禁 ── */
  listGates: (id: number) => request<GateRow[]>(`/api/projects/${id}/gates`),
  submitGate: (id: number, gateType: string) =>
    request<GateRow>(`/api/projects/${id}/gates/${gateType}/submit`, { method: 'POST' }),
  reviewGate: (id: number, gateId: number, action: string, opinion: string) =>
    request<GateRow>(`/api/projects/${id}/gates/${gateId}/review`, {
      method: 'POST', body: JSON.stringify({ action, opinion }),
    }),
  finalizeGate: (id: number, gateId: number, action: string, opinion: string) =>
    request<GateRow>(`/api/projects/${id}/gates/${gateId}/final`, {
      method: 'POST', body: JSON.stringify({ action, opinion }),
    }),
  listEvidence: (id: number, gateId: number) =>
    request<EvidenceRow[]>(`/api/projects/${id}/gates/${gateId}/evidence`),
  verifyChain: (id: number, gateId: number) =>
    request<ChainVerify>(`/api/projects/${id}/gates/${gateId}/evidence/verify`),
}

/** 提交评审被门禁阻断时的 409 响应体(后端固定口径)。 */
export interface GateBlocked {
  gate: string
  status: 'blocked'
  missing: string[]
  message?: string
}

export function parseGateBlocked(err: Error): GateBlocked | null {
  try {
    const body = JSON.parse(err.message)
    if (body && body.status === 'blocked' && Array.isArray(body.missing)) return body
  } catch { /* 非阻断结构 */ }
  return null
}

/** 触发浏览器下载(GET 附件)。 */
export function downloadUrl(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
