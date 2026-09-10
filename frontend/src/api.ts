/* API 客户端: 统一错误提示; 附件下载走 fetch→blob(需携带登录态)。
   身份: 登录后 token 存 localStorage, 每个请求经 Authorization: Bearer 携带;
   遇 401 广播 AUTH_EXPIRED_EVENT, 由 App 清除登录态并回到登录页。 */
import type {
  ApiEndpointRow, AuthConfigRow, BaselineApiEndpoint, BaselineDataAsset,
  BaselinePermissionBundle, ComponentRow, DashboardData, DataAssetRow, DetailSectionMeta,
  ExternalSystemRow, FeatureRow, FilingRow, GenerateSummary, GradingQuestion,
  InfraArchImageRow, InfraAssetRow, LabelMap, LdapConfigRow, LdapSyncResult, LdapTestResult,
  LoginInfo, MatrixEntryIn,
  RequirementTransitionRow, ReviewOverviewRow, ReviewState, SystemDetailFeature,
  SystemImportResult,
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

// 平台角色分组(#309 五角色): 安全业务侧=安全管理员(评审裁定等);
// 平台管理端(平台设置)=安全管理员+系统管理员; 全量可见再含开发管理员与审计(只读)。
export function isSecuritySideRole(role: string | undefined | null): boolean {
  return role === 'security_admin'
}
export function isPlatformAdminRole(role: string | undefined | null): boolean {
  return isSecuritySideRole(role) || role === 'sys_admin'
}
export function isFullVisibilityRole(role: string | undefined | null): boolean {
  return isPlatformAdminRole(role) || role === 'dev_admin' || role === 'auditor'
}
/** 评估写操作(新建/填写/提交/撤回/删除)仅开发侧可用; 安全管理员/系统管理员/审计只读。 */
export function isDevSideRole(role: string | undefined | null): boolean {
  return role === 'pm' || role === 'dev_admin'
}

/** 系统批量导入(#346): 仅系统/开发/安全管理员; pm 与审计员(只读)不可导入。 */
export function isSystemImportRole(role: string | undefined | null): boolean {
  return role === 'sys_admin' || role === 'dev_admin' || role === 'security_admin'
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
    ...((init?.headers as Record<string, string>) ?? {}),
  }
  // FormData 由浏览器自动生成含 boundary 的 multipart Content-Type, 不能覆盖
  if (!(init?.body instanceof FormData)) headers['Content-Type'] = 'application/json'
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

/** 文件上传统一入口: FormData + Bearer, 错误提示口径与 request() 一致。 */
async function uploadRequest<T>(path: string, file: File | Blob, fieldName = 'file'): Promise<T> {
  const body = new FormData()
  body.append(fieldName, file)
  return request<T>(path, { method: 'POST', body })
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
  /** 评审中心(#307): 跨项目评审进度总览(仅已提交过的评审, 按数据权限过滤) */
  listReviews: () => request<ReviewOverviewRow[]>('/api/reviews'),
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
  /** 撤回评审(DESIGN 状态机): 审批中提交人可撤回, 回到新建阶段, 数据保留 */
  reviewWithdraw: (projectId: number) =>
    request<{ status: string; gate_status: string }>(
      `/api/projects/${projectId}/review/withdraw`, { method: 'POST' }),
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
  /** 分页信封(#283 item9): 服务端过滤分页; 不传 page 的全量口径见 listProjects */
  listProjectsPaged: (params: {
    page: number; pageSize: number; systemId?: number | null;
    status?: string | null; keyword?: string | null
  }) => {
    const q = new URLSearchParams()
    q.set('page', String(params.page))
    q.set('page_size', String(params.pageSize))
    if (params.systemId) q.set('system_id', String(params.systemId))
    if (params.status) q.set('status', params.status)
    if (params.keyword) q.set('keyword', params.keyword)
    return request<{ items: ProjectDetail[]; total: number }>(`/api/projects?${q.toString()}`)
  },
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

  /* ── 系统清单: 定级备案 / 被评估系统 ── */
  listFilings: () => request<FilingRow[]>('/api/filings'),
  createFiling: (data: Partial<FilingRow>) =>
    request<FilingRow>('/api/filings', { method: 'POST', body: JSON.stringify(data) }),
  updateFiling: (id: number, data: Partial<FilingRow>) =>
    request<FilingRow>(`/api/filings/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFiling: (id: number) => request<void>(`/api/filings/${id}`, { method: 'DELETE' }),
  /** CSV 批量导入备案(DESIGN): 逐行校验, 返回新增数与跳过明细 */
  importFilingsCsv: (file: File) =>
    uploadRequest<{ created: number; skipped: { row: number; name: string; reason: string }[] }>(
      '/api/filings/import', file),
  listSystems: () => request<SystemRow[]>('/api/systems'),
  getSystem: (id: number) => request<SystemRow>(`/api/systems/${id}`),
  /* 系统详情 Tab 分节数据(#272): features 读基线来源轮次, 其余读基线快照 */
  systemDetailFeatures: (id: number) =>
    request<DetailSectionMeta & { rows: SystemDetailFeature[] }>(
      `/api/systems/${id}/detail-section?section=features`),
  systemDetailDataAssets: (id: number) =>
    request<DetailSectionMeta & { rows: BaselineDataAsset[] }>(
      `/api/systems/${id}/detail-section?section=data_assets`),
  systemDetailPermissions: (id: number) =>
    request<DetailSectionMeta & { rows: BaselinePermissionBundle }>(
      `/api/systems/${id}/detail-section?section=permissions`),
  systemDetailApis: (id: number) =>
    request<DetailSectionMeta & { rows: BaselineApiEndpoint[] }>(
      `/api/systems/${id}/detail-section?section=apis`),
  /** 外部连接系统清单(#289): 读基线来源轮次, 与 features 分节同口径 */
  systemDetailExternalSystems: (id: number) =>
    request<DetailSectionMeta & { rows: ExternalSystemRow[] }>(
      `/api/systems/${id}/detail-section?section=external_systems`),
  createSystem: (data: Partial<SystemRow>) =>
    request<SystemRow>('/api/systems', { method: 'POST', body: JSON.stringify(data) }),
  /** CSV 批量导入系统(#346): 仅系统/开发/安全管理员; 逐行校验, 返回新增数与跳过明细 */
  importSystems: (file: File) =>
    uploadRequest<SystemImportResult>('/api/systems/import', file),
  updateSystem: (id: number, data: Partial<SystemRow>) =>
    request<SystemRow>(`/api/systems/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSystem: (id: number) => request<void>(`/api/systems/${id}`, { method: 'DELETE' }),
  systemLedger: () => request<SystemRow[]>('/api/systems/ledger'),
  /** 分页信封(#283 item9): 服务端过滤分页的台账 */
  systemLedgerPaged: (params: {
    page: number; pageSize: number; keyword?: string | null;
    filingId?: number | null; importance?: string | null; tag?: string | null
  }) => {
    const q = new URLSearchParams()
    q.set('page', String(params.page))
    q.set('page_size', String(params.pageSize))
    if (params.keyword) q.set('keyword', params.keyword)
    if (params.filingId) q.set('filing_id', String(params.filingId))
    if (params.importance) q.set('importance', params.importance)
    if (params.tag) q.set('tag', params.tag)
    return request<{ items: SystemRow[]; total: number }>(`/api/systems/ledger?${q.toString()}`)
  },

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
  importSystemSbom: (systemId: number, file: File) =>
    uploadRequest<{
      filename: string, format: string, total_parsed: number, added: number, skipped_duplicate: number,
    }>(`/api/systems/${systemId}/components/import-sbom`, file),
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
  importDictionaryFile: (id: number, file: File) =>
    uploadRequest<{ row_count: number; assets: DataAssetRow[] }>(
      `/api/projects/${id}/data-assets/import-dictionary`, file),
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
  importSbomFile: (id: number, file: File) =>
    uploadRequest<{
      filename: string, format: string, total_parsed: number, added: number, skipped_duplicate: number,
    }>(`/api/projects/${id}/components/import-sbom`, file),
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
  /** 标记需求不属实(#310 属实性确认): 必填原因, 保留记录不删除 */
  markRequirementInvalid: (id: number, reqId: string, reason: string) =>
    request<RequirementRow>(`/api/projects/${id}/requirements/${reqId}/invalid`,
      { method: 'POST', body: JSON.stringify({ reason }) }),

  /* ── 平台设置(仅安全角色) ── */
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
  saveNetboxConfig: (data: {
    base_url: string; token: string; system_slug: string;
    field_map: Record<string, string>; sync_enabled?: boolean; sync_interval_hours?: number
  }) =>
    request<{ status: string }>('/api/admin/netbox-config', { method: 'PUT', body: JSON.stringify(data) }),
  /** 只测不存: token 留空表示沿用已保存的 Token(#152) */
  testNetboxConfig: (data: { base_url: string; token?: string }) =>
    request<{ ok: boolean; latency_ms?: number; version?: string; reason?: string }>(
      '/api/admin/netbox-config/test', { method: 'POST', body: JSON.stringify(data) }),
  /** 拉取 system 对象类型字段, 供 field_map 对照; 未配置返回 409 */
  /** 基础资源环境配置(#289, DESIGN 分环境可配置) */
  /** 系统字典(#283): 系统标签 + 系统类型枚举(系统管理维护) */
  getSystemDicts: () => request<{ tags: string[]; types: Record<string, string> }>('/api/admin/system-dicts'),
  saveSystemDicts: (payload: { tags: string[]; types: { code: string; label: string }[] }) =>
    request<{ tags: string[]; types: Record<string, string> }>('/api/admin/system-dicts', {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  getInfraEnvs: () => request<{ envs: { code: string; name: string }[] }>('/api/admin/infra-envs'),
  saveInfraEnvs: (envs: { code: string; name: string }[]) =>
    request<{ envs: { code: string; name: string }[] }>('/api/admin/infra-envs', {
      method: 'PUT', body: JSON.stringify({ envs }),
    }),
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
  /** NetBox 连接配置探测(#271): 是否已配置 */
  getNetboxStatus: () =>
    request<{ configured: boolean }>('/api/netbox/status'),
  /** 同步状态: 执行中 + 调度配置 + 最近一轮日志(#271) */
  getNetboxSyncState: () =>
    request<NetboxSyncState>('/api/netbox/sync/state'),
  /** 手动触发一轮同步(#271); 运行中/未配置 409 */
  runNetboxSync: () =>
    request<NetboxSyncLogOut>('/api/netbox/sync/run', { method: 'POST' }),
  /** 同步执行历史(倒序) */
  listNetboxSyncLogs: (limit = 20) =>
    request<NetboxSyncLogOut[]>(`/api/netbox/sync/logs?limit=${limit}`),
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

  /* ── 工作台聚合(#280) ── */
  getDashboard: () => request<DashboardData>('/api/meta/dashboard'),

  /* ── LDAP/AD 对接(#280) ── */
  getLdapConfig: () => request<LdapConfigRow>('/api/admin/ldap-config'),
  saveLdapConfig: (data: LdapConfigRow) =>
    request<{ status: string }>('/api/admin/ldap-config', {
      method: 'PUT', body: JSON.stringify({ ...data, bind_password: data.bind_password ?? '' }),
    }),
  /** 只测不存: bind_password 留空表示沿用已保存密码(同 LLM/NetBox 口径) */
  testLdapConfig: (data: Partial<LdapConfigRow>) =>
    request<LdapTestResult>('/api/admin/ldap-config/test', {
      method: 'POST', body: JSON.stringify(data),
    }),
  syncLdapUsers: () =>
    request<LdapSyncResult>('/api/admin/ldap-config/sync', { method: 'POST' }),
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
  sync_enabled?: boolean
  sync_interval_hours?: number
}

/** 一轮 NetBox 同步的日志(#271) */
export interface NetboxSyncLogOut {
  id: number
  trigger: string
  status: string
  started_at: string | null
  finished_at: string | null
  stats: Record<string, Record<string, number>>
  errors: string[]
}

export interface NetboxSyncState {
  running: boolean
  schedule: { enabled: boolean; interval_hours: number }
  last: NetboxSyncLogOut | null
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
