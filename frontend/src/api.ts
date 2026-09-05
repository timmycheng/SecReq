/* API 客户端: 统一错误提示; 附件下载走 fetch→blob(需携带登录态)。
   身份: 登录后 token 存 localStorage, 每个请求经 Authorization: Bearer 携带;
   遇 401 广播 AUTH_EXPIRED_EVENT, 由 App 清除登录态并回到登录页。 */
import type {
  ApiEndpointRow, AuthConfigRow, ComponentRow, DataAssetRow,
  ExternalSystemRow, FeatureRow, FilingRow, GenerateSummary, GradingQuestion,
  InfraArchImageRow, InfraAssetRow, LabelMap, LoginInfo, MatrixEntryIn,
  RequirementTransitionRow, ReviewState,
  NetboxAssetRow, NetboxSystemRow,
  PreviewResult, ProjectDetail, ProjectInfo, RequirementDiff, RequirementRow, RoleRow,
  ResourceRow, SurveyAnswer, SystemRow, VulnerabilityRow, VulnDbStatus, VulnDbVerifyResult,
  WizardState,
} from './types'

export type { MatrixEntryIn }

export const AUTH_STORAGE_KEY = 'secreq.auth.token'
export const USER_STORAGE_KEY = 'secreq.auth.info'

/** 会话失效事件: App 监听后清除本地登录态并展示登录页。 */
export const AUTH_EXPIRED_EVENT = 'secreq:auth-expired'

export interface StoredUser {
  id: number
  username: string
  display_name: string
  role: string
  role_label: string
}

export function getStoredToken(): string | null {
  return localStorage.getItem(AUTH_STORAGE_KEY)
}

// 平台角色分组(#216): 安全侧可维护 NetBox/定级备案; 全量可见角色再含审计(只读)。
export function isSecuritySideRole(role: string | undefined | null): boolean {
  return role === 'security_reviewer' || role === 'security_lead'
}
export function isFullVisibilityRole(role: string | undefined | null): boolean {
  return isSecuritySideRole(role) || role === 'auditor'
}

export function getStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as StoredUser) : null
  } catch {
    return null
  }
}

export function storeAuth(info: LoginInfo) {
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify({
    id: info.id,
    username: info.username,
    display_name: info.display_name,
    role: info.role,
    role_label: info.role_label,
  }))
  localStorage.setItem(AUTH_STORAGE_KEY, info.token ?? '')
}

export function clearAuth() {
  localStorage.removeItem(AUTH_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
}

/** 步骤耗时埋点(#229): 秒数非空时拼到 URL Query。 */
function qsDuration(seconds?: number): string {
  return seconds != null && seconds > 0 ? `?duration_seconds=${Math.round(seconds)}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  }
  const token = getStoredToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(path, { ...init, headers })
  if (!resp.ok) {
    if (resp.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
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

/** 触发浏览器下载: 经 fetch 携带 Bearer token, 再转 object URL 保存。 */
export async function downloadFile(path: string, filename?: string) {
  const token = getStoredToken()
  const resp = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!resp.ok) {
    if (resp.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    const body = await resp.json().catch(() => null)
    throw new Error(body?.detail ?? `下载失败 HTTP ${resp.status}`)
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename ?? (resp.headers.get('content-disposition') ?? '').split("filename*=")[1]?.split("''")[1]
    ?? `download-${Date.now()}`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
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

  /* ── 平台认证 ── */
  login: (username: string, password: string) =>
    request<LoginInfo>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  me: () => request<LoginInfo | null>('/api/auth/me'),
  reviewState: (projectId: number) =>
    request<ReviewState>(`/api/projects/${projectId}/review/state`),
  reviewSubmit: (projectId: number) =>
    request<{ status: string; missing?: string[]; gate_status?: string; version_hash?: string }>(
      `/api/projects/${projectId}/review/submit`, { method: 'POST', body: JSON.stringify({}) }),
  reviewAnnotate: (projectId: number, reqId: string, disposition: string, comment?: string) =>
    request<{ status: string; req_id: string; review_status: string }>(
      `/api/projects/${projectId}/review/requirements/${reqId}/annotate`,
      { method: 'POST', body: JSON.stringify({ disposition, comment: comment || null }) }),
  reviewDecide: (projectId: number, conclusion: string, comment?: string) =>
    request<{ status: string; gate_status: string }>(
      `/api/projects/${projectId}/review/decide`,
      { method: 'POST', body: JSON.stringify({ conclusion, comment: comment || null }) }),
  reviewFinalize: (projectId: number, comment?: string) =>
    request<{ status: string; gate_status: string }>(
      `/api/projects/${projectId}/review/finalize`,
      { method: 'POST', body: JSON.stringify({ comment: comment || null }) }),
  downloadReviewSheet: (projectId: number) =>
    fetch(`/api/projects/${projectId}/review/export/review-sheet`, {
      headers: { Authorization: `Bearer ${getStoredToken() ?? ''}` },
    }).then(async (resp) => {
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: resp.statusText }))
        throw new Error((body as { detail?: string }).detail ?? '导出失败')
      }
      const blob = await resp.blob()
      return URL.createObjectURL(blob)
    }),
  confirmBaselineLevel: (systemId: number, decision: 'adopt_suggested' | 'keep_filing', note?: string) =>
    request<{ status: string; summary: string }>(
      `/api/systems/${systemId}/baseline/confirm-level`,
      { method: 'POST', body: JSON.stringify({ decision, note: note || null }) }),
  requirementTransitions: (projectId: number, reqId: string) =>
    request<RequirementTransitionRow[]>(
      `/api/projects/${projectId}/requirements/${reqId}/transitions`),
  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ message: string }>('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  listProjects: () => request<ProjectDetail[]>('/api/projects'),
  getProject: (id: number) => request<ProjectDetail>(`/api/projects/${id}`),
  createProject: (payload: Partial<ProjectInfo>) =>
    request<ProjectDetail>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  /** 就地复制(#172): 把来源项目整卷向导数据复制到已落库的当前项目(先清后拷) */
  copyProjectFrom: (id: number, fromProjectId: number) =>
    request<ProjectDetail>(`/api/projects/${id}/copy-from`,
      { method: 'POST', body: JSON.stringify({ from_project_id: fromProjectId }) }),
  /** 一键清空(#172): 清空当前项目全部向导输入, 回到空白模板 */
  resetProjectWizard: (id: number) =>
    request<ProjectDetail>(`/api/projects/${id}/reset-wizard`, { method: 'POST' }),
  patchProject: (id: number, payload: Partial<ProjectInfo>, durationSeconds?: number) =>
    request<ProjectDetail>(`/api/projects/${id}${qsDuration(durationSeconds)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  loadWizard: (id: number) => request<WizardState>(`/api/projects/${id}/wizard-state`),

  /* ── 系统台账: 定级备案 / 被评估系统 ── */
  listFilings: () => request<FilingRow[]>('/api/filings'),
  createFiling: (data: Partial<FilingRow>) =>
    request<FilingRow>('/api/filings', { method: 'POST', body: JSON.stringify(data) }),
  updateFiling: (id: number, data: Partial<FilingRow>) =>
    request<FilingRow>(`/api/filings/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFiling: (id: number) => request<void>(`/api/filings/${id}`, { method: 'DELETE' }),
  listSystems: () => request<SystemRow[]>('/api/systems'),
  getSystem: (id: number) => request<SystemRow>(`/api/systems/${id}`),
  createSystem: (data: Partial<SystemRow>) =>
    request<SystemRow>('/api/systems', { method: 'POST', body: JSON.stringify(data) }),
  updateSystem: (id: number, data: Partial<SystemRow>) =>
    request<SystemRow>(`/api/systems/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSystem: (id: number) => request<void>(`/api/systems/${id}`, { method: 'DELETE' }),
  systemLedger: () => request<SystemRow[]>('/api/systems/ledger'),

  /* ── 系统清单(#194): 基础设施/组件/架构图挂系统, 多轮共享 ── */
  getSystemInfraAssets: (systemId: number) =>
    request<InfraAssetRow[]>(`/api/systems/${systemId}/infra-assets`),
  saveSystemInfraAssets: (systemId: number, rows: InfraAssetRow[]) =>
    request<InfraAssetRow[]>(`/api/systems/${systemId}/infra-assets`, {
      method: 'POST', body: JSON.stringify({ assets: rows }),
    }),
  getSystemComponents: (systemId: number) =>
    request<ComponentRow[]>(`/api/systems/${systemId}/components`),
  saveSystemComponents: (systemId: number, rows: Omit<ComponentRow, 'vulnerabilities'>[]) =>
    request<ComponentRow[]>(`/api/systems/${systemId}/components`, {
      method: 'POST', body: JSON.stringify({ components: rows }),
    }),
  importSystemSbom: async (systemId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const token = getStoredToken()
    const resp = await fetch(`/api/systems/${systemId}/components/import-sbom`, {
      method: 'POST', body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.detail ?? `导入失败 HTTP ${resp.status}`)
    }
    return (await resp.json()) as {
      filename: string, format: string, total_parsed: number, added: number, skipped_duplicate: number,
    }
  },
  getSystemArchImages: (systemId: number) =>
    request<InfraArchImageRow[]>(`/api/systems/${systemId}/arch-images`),
  uploadSystemArchImage: (systemId: number, env: string, imageDataUrl: string) =>
    request<InfraArchImageRow>(`/api/systems/${systemId}/arch-images/${env}`, {
      method: 'PUT', body: JSON.stringify({ image_data_url: imageDataUrl }),
    }),
  deleteSystemArchImage: (systemId: number, env: string) =>
    request<{ ok: boolean }>(`/api/systems/${systemId}/arch-images/${env}`, { method: 'DELETE' }),

  saveExternalSystems: (id: number, rows: ExternalSystemRow[]) =>
    request<ExternalSystemRow[]>(`/api/projects/${id}/external-systems`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  getGradingBaseline: (id: number) =>
    request<GradingBaseline>(`/api/projects/${id}/grading-baseline`),
  saveSurvey: (id: number, answers: SurveyAnswer[], finalLevel?: string | null, note?: string | null) => {
    const body = finalLevel
      ? { answers, final_level: finalLevel, manual_adjust_note: note }
      : { answers }
    return request<Record<string, never>>(`/api/projects/${id}/survey`, {
      method: 'POST', body: JSON.stringify(body),
    })
  },
  extractFeatures: (id: number, text: string) =>
    request<{ mode: 'llm' | 'rules'; note: string; candidates: FeatureRow[] & { source_quote?: string | null }[] }>(
      `/api/projects/${id}/features/extract`,
      { method: 'POST', body: JSON.stringify({ text }) },
    ),
  parseDictionary: (id: number, content: string) =>
    request<{ row_count: number; assets: DataAssetRow[] }>(`/api/projects/${id}/data-assets/parse-dictionary`, {
      method: 'POST', body: JSON.stringify({ content }),
    }),
  importDictionaryFile: async (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const token = getStoredToken()
    const resp = await fetch(`/api/projects/${id}/data-assets/import-dictionary`, {
      method: 'POST', body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.detail ?? `解析失败 HTTP ${resp.status}`)
    }
    return (await resp.json()) as { row_count: number; assets: DataAssetRow[] }
  },
  saveFeatures: (id: number, rows: FeatureRow[], durationSeconds?: number) =>
    request<FeatureRow[]>(`/api/projects/${id}/features${qsDuration(durationSeconds)}`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  saveDataAssets: (id: number, rows: DataAssetRow[], durationSeconds?: number) =>
    request<DataAssetRow[]>(`/api/projects/${id}/data-assets${qsDuration(durationSeconds)}`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  saveMatrix: (id: number, roles: RoleRow[], resources: ResourceRow[], entries: MatrixEntryIn[], durationSeconds?: number) =>
    request<{
      roles: (RoleRow & { id: number })[],
      resources: (ResourceRow & { id: number })[],
      entries: { id: number, role_id: number, resource_id: number, action: string, requires_approval: boolean }[],
      saved: { roles: number, resources: number, entries: number },
    }>(`/api/projects/${id}/matrix${qsDuration(durationSeconds)}`, {
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
    const token = getStoredToken()
    const resp = await fetch(`/api/projects/${id}/components/import-sbom`, {
      method: 'POST', body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.detail ?? `导入失败 HTTP ${resp.status}`)
    }
    return (await resp.json()) as {
      filename: string, format: string, total_parsed: number, added: number, skipped_duplicate: number,
    }
  },
  saveApiEndpoints: (id: number, rows: ApiEndpointRow[], durationSeconds?: number) =>
    request<ApiEndpointRow[]>(`/api/projects/${id}/api-endpoints${qsDuration(durationSeconds)}`, {
      method: 'POST', body: JSON.stringify(rows),
    }),
  saveInfraAssets: (id: number, rows: InfraAssetRow[]) =>
    request<InfraAssetRow[]>(`/api/projects/${id}/infra-assets`, {
      method: 'POST', body: JSON.stringify({ assets: rows }),
    }),

  previewRequirements: (id: number) =>
    request<PreviewResult>(`/api/projects/${id}/requirements/preview`, { method: 'POST' }),
  generate: (id: number, skipOsv: boolean, vulnSource?: 'online' | 'local') =>
    request<GenerateSummary>(`/api/projects/${id}/generate`, {
      method: 'POST',
      body: JSON.stringify({ skip_osv: skipOsv, ...(vulnSource ? { vuln_source: vulnSource } : {}) }),
    }),

  listRequirements: (id: number) => request<RequirementRow[]>(`/api/projects/${id}/requirements`),
  requirementsDiff: (id: number, against?: number) =>
    request<RequirementDiff>(
      `/api/projects/${id}/requirements/diff${against ? `?against=${against}` : ''}`),
  listVulnerabilities: (id: number) => request<VulnerabilityRow[]>(`/api/projects/${id}/vulnerabilities`),
  confirmRegulatory: (id: number, reqId: string) =>
    request<RequirementRow>(`/api/projects/${id}/requirements/${reqId}/confirm`, { method: 'POST' }),

  /* ── 系统管理(仅安全角色) ── */
  listKb: (keyword?: string) =>
    request<{ total: number; templates: KbTemplateRow[] }>(
      `/api/admin/knowledge-base${keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''}`),
  updateKbTemplate: (templateId: string, changes: Partial<KbTemplateRow>) =>
    request<KbTemplateRow>(`/api/admin/knowledge-base/${templateId}`, {
      method: 'PUT', body: JSON.stringify(changes),
    }),
  createKbTemplate: (data: Record<string, unknown>) =>
    request<KbTemplateRow>('/api/admin/knowledge-base', { method: 'POST', body: JSON.stringify(data) }),
  getQuestionBank: () => request<QuestionBank>(`/api/admin/grading-questions`),
  saveQuestionBank: (bank: QuestionBank) =>
    request<{ status: string }>('/api/admin/grading-questions', { method: 'PUT', body: JSON.stringify(bank) }),
  getPolicyBaselines: () => request<PolicyBaselines>('/api/admin/policy-baselines'),
  savePolicyBaselines: (data: PolicyBaselines) =>
    request<{ status: string }>('/api/admin/policy-baselines', { method: 'PUT', body: JSON.stringify(data) }),
  getLlmConfig: () => request<LlmConfig>('/api/admin/llm-config'),
  saveLlmConfig: (data: LlmConfig) =>
    request<{ status: string }>('/api/admin/llm-config', { method: 'PUT', body: JSON.stringify(data) }),
  /** 只测不存: api_key 留空表示沿用已保存的 Key(#62) */
  testLlmConfig: (data: { base_url: string; api_key?: string; model: string }) =>
    request<{ ok: boolean; latency_ms?: number; reply?: string; reason?: string }>(
      '/api/admin/llm-config/test', { method: 'POST', body: JSON.stringify(data) }),
  getNetboxConfig: () => request<NetboxConfig>('/api/admin/netbox-config'),
  saveNetboxConfig: (data: { base_url: string; token: string; system_slug: string; field_map: Record<string, string> }) =>
    request<{ status: string }>('/api/admin/netbox-config', { method: 'PUT', body: JSON.stringify(data) }),
  /** 只测不存: token 留空表示沿用已保存的 Token(#152) */
  testNetboxConfig: (data: { base_url: string; token?: string }) =>
    request<{ ok: boolean; latency_ms?: number; version?: string; reason?: string }>(
      '/api/admin/netbox-config/test', { method: 'POST', body: JSON.stringify(data) }),
  /** 拉取 system 对象类型字段, 供 field_map 对照; 未配置返回 409 */
  getNetboxSystemFields: () =>
    request<{ slug: string; fields: { name: string; type?: string | null }[] }>(
      '/api/admin/netbox-config/system-fields'),
  parseApiEndpoints: (projectId: number, data: { text: string }) => {
    const body = new FormData()
    body.append('text', data.text)
    return request<{ total: number; invalid: number; rows: { index: number; name: string; method: string; path: string; auth_required: boolean; public_exposed: boolean; error?: string | null }[] }>(
      `/api/projects/${projectId}/api-endpoints/parse`, { method: 'POST', body })
  },
  parseApiEndpointsFile: (projectId: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<{ total: number; invalid: number; rows: { index: number; name: string; method: string; path: string; auth_required: boolean; public_exposed: boolean; error?: string | null }[] }>(
      `/api/projects/${projectId}/api-endpoints/parse`, { method: 'POST', body })
  },
  /** NetBox 是否已配置 + base_url(构建外链用, 未配置不报错) */
  getNetboxStatus: () =>
    request<{ configured: boolean; base_url?: string }>('/api/netbox/status'),
  /** NetBox 系统清单搜索(#154): 按 field_map 裁剪为 {id, name, code, owner, url} */
  listNetboxSystems: (keyword: string, limit: number, offset: number) =>
    request<{ count: number; results: NetboxSystemRow[] }>(
      `/api/netbox/systems?keyword=${encodeURIComponent(keyword)}&limit=${limit}&offset=${offset}`),
  /** 推送台账系统到 NetBox(#154): 成功回填 netbox_object_id */
  pushNetboxSystem: (data: { system_id: number; name: string; code?: string; owner?: string }) =>
    request<{ netbox_object_id: string; url?: string }>('/api/netbox/systems',
      { method: 'POST', body: JSON.stringify(data) }),
  /** NetBox 资产搜索(#153): kind 为 devices / virtual-machines / ip-addresses */
  listNetboxAssets: (kind: 'devices' | 'virtual-machines' | 'ip-addresses',
                     keyword: string, limit: number, offset: number) =>
    request<{ count: number; results: NetboxAssetRow[] }>(
      `/api/netbox/${kind}?keyword=${encodeURIComponent(keyword)}&limit=${limit}&offset=${offset}`),
  getNetboxOptions: () =>
    request<{ sites: { id: number; name: string }[]; roles: { id: number; name: string }[];
      device_types: { id: number; model: string }[]; base_url: string }>('/api/netbox/options'),
  pushNetboxDevice: (data: {
    project_id: number; asset_id: number; name: string;
    site_id: number; role_id: number; device_type_id: number; ip_address?: string
  }) =>
    request<{ netbox_ref_type: string; netbox_ref_id: string; url: string; note?: string }>(
      '/api/netbox/devices', { method: 'POST', body: JSON.stringify(data) }),
  listArchImages: (id: number) =>
    request<InfraArchImageRow[]>(`/api/projects/${id}/arch-images`),
  saveArchImage: (id: number, env: string, imageDataUrl: string) =>
    request<InfraArchImageRow>(`/api/projects/${id}/arch-images/${env}`, {
      method: 'PUT', body: JSON.stringify({ image_data_url: imageDataUrl }),
    }),
  deleteArchImage: (id: number, env: string) =>
    request<{ ok: boolean }>(`/api/projects/${id}/arch-images/${env}`, { method: 'DELETE' }),
  getInfraAssets: (id: number) =>
    request<InfraAssetRow[]>(`/api/projects/${id}/infra-assets`),
  getChangelog: () =>
    request<{ version: string; date: string; blocks: { kind: 'h3' | 'para' | 'list_item' | 'quote' | 'table_row'; text?: string; cells?: string[] }[] }[]>(
      '/api/admin/changelog'),
  getProjectCodeRule: () =>
    request<{ prefix: string; include_year: boolean; digits: number }>('/api/admin/project-code-rule'),
  saveProjectCodeRule: (data: { prefix: string; include_year: boolean; digits: number }) =>
    request<{ prefix: string; include_year: boolean; digits: number }>(
      '/api/admin/project-code-rule', { method: 'PUT', body: JSON.stringify(data) }),
  adminListUsers: () => request<AdminUserRow[]>('/api/admin/users'),
  adminCreateUser: (data: { username: string; display_name: string; employee_id?: string; role: string; password?: string }) =>
    request<{ status: string; initial_password: string }>('/api/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  adminResetPassword: (username: string, password?: string) =>
    request<{ status: string; password: string | null }>(`/api/admin/users/${username}/reset-password`, {
      method: 'POST', body: JSON.stringify(password ? { password } : {}),
    }),
  adminUpdateUser: (username: string, data: { display_name: string; employee_id?: string; role: string }) =>
    request<{ username: string; display_name: string; employee_id?: string | null; role: string }>(
      `/api/admin/users/${username}`, { method: 'PUT', body: JSON.stringify(data) }),
  adminToggleUser: (username: string) =>
    request<{ username: string; active: boolean }>(`/api/admin/users/${username}/toggle-active`, { method: 'POST' }),
  listAuditLogs: () => request<AuditLogRow[]>('/api/admin/audit-logs'),

  /* ── 离线漏洞库(v2.2.0) ── */
  getVulnDb: () => request<VulnDbStatus>('/api/admin/vuln-db'),
  verifyVulnDb: () =>
    request<VulnDbVerifyResult>('/api/admin/vuln-db/verify', { method: 'POST' }),
  batchConfirmRequirements: (id: number, reqIds: string[]) =>
    request<{ confirmed: number; missing: string[] }>(`/api/projects/${id}/requirements/batch-confirm`, {
      method: 'POST', body: JSON.stringify({ req_ids: reqIds }),
    }),
}

/** 定级基线: 按当前输入干跑引擎得到的合规/策略/报送类要求(定级后即时反馈)。 */
export interface GradingBaseline {
  grading_level: string
  grading_text: string
  pwd_defaults: Record<string, number>
  requirements: {
    req_id: string
    title: string
    description: string
    category: string
    priority: string
    reg_confirmed?: boolean
  }[]
}

/* ── 系统管理数据形态 ── */
export interface KbRegulatoryRef {
  file: string
  clause?: string
  summary?: string
  note?: string
}

export interface KbTemplateRow {
  id: string
  trigger_type: string
  trigger: Record<string, unknown>
  title: string
  priority: string
  suggested_phase: string
  enabled: boolean
  description?: string
  acceptance_criteria?: string
  trigger_reason?: string
  regulatory_ref?: KbRegulatoryRef[]
}

export interface QuestionBank {
  questions: { id: string; title: string; options: { id: string; label: string; score: number; basis?: string; tags?: string[] }[] }[]
  levels: { level: string; min_score: number; combined_tags?: string[] }[]
  [key: string]: unknown
}

export interface PolicyBaselines {
  baselines: Record<string, { pwd_min_length: number; pwd_complexity: number; pwd_valid_days: number }>
  lockout_threshold: number
  session_timeout_min: number
}

export interface LlmConfig {
  base_url?: string
  api_key?: string
  model?: string
  configured?: boolean
}

export interface NetboxConfig {
  base_url?: string
  token?: string
  system_slug?: string
  field_map?: Record<string, string>
  configured?: boolean
}

export interface AdminUserRow {
  id: number
  username: string
  display_name: string
  employee_id?: string | null
  role: string
  active: boolean
}

export interface AuditLogRow {
  id: number
  username: string
  action: string
  /** 动作中文标签(后端统一下发); 未识别的 action 回退原始 code */
  action_label?: string | null
  /** 明细可读摘要(后端按动作类型渲染); 无法识别时为空, 前端回退原文 */
  summary?: string | null
  detail: Record<string, unknown>
  ip?: string | null
  created_at: string
}
