/* API 数据形态(与 schemas/*.py 对应)。枚举 code 的中文标签一律走 /api/meta/constants。 */

export type LabelMap = Record<string, string>

export interface ProjectInfo {
  id: number
  name: string
  code: string
  type: string
  types: string[]
  user_scale: string
  is_public: boolean
  offshore_vendor?: boolean
  pm_name?: string | null
  dev_lead_name?: string | null
  sec_contact_name?: string | null
  compliance_targets: string[]
  status: string
  created_at?: string | null
}

export interface ProjectDetail extends ProjectInfo {
  has_survey: boolean
  grading_level?: string | null
  counts: Record<string, number>
}

export interface SurveyAnswer {
  question_id: string
  option_id: string
}

export interface SurveyOut {
  project_id: number
  answers_json: SurveyAnswer[]
  suggested_level?: string | null
  suggested_reason?: string | null
  final_level?: string | null
  manual_adjust_note?: string | null
  effective_level: string
}

export interface GradingQuestion {
  id: string
  title: string
  options: { id: string; label: string; score: number; basis: string }[]
}

export interface FeatureRow {
  id?: number
  name: string
  module?: string | null
  description?: string | null
  categories: string[]
  sensitivity: string
  involves_payment: boolean
  exposed_to_internet: boolean
}

export interface DataFieldRow {
  id?: number
  field_name: string
  field_type: string
  need_encrypt: boolean
  need_mask: boolean
  mask_rule?: string | null
}

export interface DataTableRow {
  id?: number
  table_name: string
  fields: DataFieldRow[]
}

export interface DataAssetRow {
  id?: number
  name: string
  data_type: string
  classification: string
  legacy_classification?: string | null
  c3_tag?: boolean
  is_pii: boolean
  is_sensitive_pii: boolean
  storage_envs: string[]
  cross_border_transfer: boolean
  tables: DataTableRow[]
}

export interface RoleRow {
  id?: number
  name: string
  role_type: string
}

export interface ExternalSystemRow {
  id?: number
  name: string
  purpose?: string | null
  direction: string
  involves_sensitive: boolean
}

export interface ResourceRow {
  id?: number
  name: string
  resource_type: string
  criticality: string
}

export interface MatrixEntryRow {
  role_id: number
  resource_id: number
  action: string
  requires_approval: boolean
}

/** 提交矩阵时 entry 以 roles/resources 数组下标定位。 */
export interface MatrixEntryIn {
  role_index: number
  resource_index: number
  action: string
  requires_approval: boolean
}

export interface AuthConfigRow {
  auth_methods: string[]
  pwd_min_length?: number | null
  pwd_complexity?: number | null
  pwd_valid_days?: number | null
  lockout_threshold?: number | null
  pwd_history_limit?: number | null
  force_2fa: boolean
  session_timeout_min?: number | null
  concurrent_limit?: number | null
}

export interface ComponentVulnInline {
  cve_id: string
  severity: string
  cvss_score: number | null
  affected_range: string | null
  fix_version: string | null
  summary: string | null
  cnnvd_id?: string | null
  cn_severity?: string | null
}

export interface ComponentRow {
  id?: number
  layer: string
  name: string
  version: string
  purl?: string | null
  license?: string | null
  source_type: string
  /** 生态 code(见 vuln_ecosystems); 决定漏洞查询走哪个生态的数据 */
  ecosystem?: string | null
  /** 分发渠道 code(见 sbom_distros); OS 覆盖的前提 —— 版本串随渠道而变 */
  distro?: string | null
  /** 查询语义: hit/not_found/undetermined/not_covered, 四种不可合并 */
  vuln_status?: string | null
  vuln_status_note?: string | null
  vulnerabilities: ComponentVulnInline[]
}

export interface ApiEndpointRow {
  id?: number
  name: string
  path: string
  method: string
  auth_required: boolean
  public_exposed: boolean
  sensitive_asset_ids: number[]
  rate_limit?: string | null
}

export interface InfraAssetRow {
  id?: number
  asset_type: string
  name: string
  env: string
  ip?: string | null
  owner?: string | null
  holds_sensitive: boolean
  cpu_cores?: number | null
  memory_gb?: number | null
  disk_gb?: number | null
  os?: string | null
  quantity?: number | null
  purpose?: string | null
}

export interface WizardState {
  project: ProjectDetail
  survey: SurveyOut | null
  external_systems: ExternalSystemRow[]
  features: FeatureRow[]
  data_assets: DataAssetRow[]
  roles: RoleRow[]
  resources: ResourceRow[]
  permission_entries: MatrixEntryRow[]
  auth_config: AuthConfigRow | null
  components: ComponentRow[]
  api_endpoints: ApiEndpointRow[]
  infra_assets: InfraAssetRow[]
}

export interface CategoryCount {
  code: string
  label: string
  count: number
}

export interface PreviewResult {
  total: number
  by_category: CategoryCount[]
  by_priority: Record<string, number>
  top_items: string[]
}

export interface GenerateSummary {
  requirements_total: number
  by_category: CategoryCount[]
  vulnerabilities_total: number
  critical_vulnerabilities: number
  osv_summary: string
  degraded: boolean
  documents: Record<string, string>
  bom_file?: string | null
  skipped_templates: { template_id: string; reason: string }[]
}

export interface RegulatoryRefItem {
  file: string
  clause?: string
  summary?: string
  note?: string
}

export interface RequirementRow {
  id: number
  req_id: string
  template_id: string
  title: string
  description: string
  category: string
  priority: string
  asvs_ref?: string | null
  acceptance_criteria: string
  suggested_phase: string
  source_entity_type: string
  source_entity_id: number
  source_label?: string | null
  trigger_reason: string
  status: string
  regulatory_ref?: RegulatoryRefItem[]
  owner?: string | null
  reg_confirmed?: boolean
  confirmed_by?: string | null
  confirmed_at?: string | null
}

export interface VulnerabilityRow {
  component_name: string
  component_version: string
  cve_id: string
  severity: string
  cvss_score: number | null
  affected_range: string | null
  fix_version: string | null
  summary: string | null
  cnnvd_id?: string | null
  cn_severity?: string | null
}

/* ── 离线漏洞库(系统管理 · 漏洞库页) ─────────────── */

export interface VulnSourceRow {
  code: string
  name: string
  available: boolean
  reason?: string | null
  active: boolean
}

export interface VulnDbEcosystemRow {
  code: string
  label: string
  records?: number | null
}

export interface VulnDbGap {
  code: string
  label: string
  note: string
  detail: string
}

export interface VulnDbStatus {
  available: boolean
  path: string
  reason?: string
  db_version?: string | null
  built_at?: string | null
  total?: number
  size_mb?: number | null
  sha256?: string | null
  compressed?: boolean
  slim?: boolean
  upstream?: string | null
  declared_ecosystems?: VulnDbEcosystemRow[]
  imported_ecosystems?: string[]
  /** 真正覆盖 = 构建时声明导入 ∩ 实际入库; 覆盖判定以此为准 */
  covered_ecosystems?: string[]
  /** 库内有记录但本次构建未声明导入的生态(OSV 多生态公告夹带), 不计入覆盖 */
  incidental_ecosystems?: string[]
  missing_ecosystems?: VulnDbEcosystemRow[]
  sources?: VulnSourceRow[]
  gaps?: VulnDbGap[]
  cnnvd?: { available: boolean; path: string; total: number; db_version?: string | null }
}

export interface VulnDbVerifyResult {
  path: string
  sha256: string
  expected: string | null
  match: boolean | null
  size_mb: number
  cnnvd?: { available: boolean; path: string; total: number; db_version?: string | null }
}

/* ── 平台认证 ───────────────────────────────────── */

export interface LoginInfo {
  username: string
  display_name: string
  employee_id?: string | null
  role: string
  role_label: string
  token?: string | null
}
