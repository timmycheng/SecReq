/* API 客户端: 统一错误提示; 文档/Excel 下载走原生链接。 */
import type {
  ApiEndpointRow, AuthConfigRow, ComponentRow, DataAssetRow, FeatureRow,
  GenerateSummary, GradingQuestion, InfraAssetRow, LabelMap, MatrixEntryIn,
  PreviewResult, ProjectDetail, ProjectInfo, RequirementRow,
  RoleRow, ResourceRow, SurveyAnswer, VulnerabilityRow, WizardState,
} from './types'

export type { MatrixEntryIn }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
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
}

export const api = {
  constants: () => request<Constants>('/api/meta/constants'),
  gradingQuestions: () =>
    request<{ questions: GradingQuestion[] }>('/api/meta/grading-questions')
      .then((r) => r.questions),

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
  importSbomFile: async (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`/api/projects/${id}/components/import-sbom`, {
      method: 'POST', body: form,
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
