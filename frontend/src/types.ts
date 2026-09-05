/* API 数据形态(与 schemas/*.py 对应)。枚举 code 的中文标签一律走 /api/meta/constants。 */

export type LabelMap = Record<string, string>

export interface ProjectInfo {
  id: number
  name: string
  code: string
  system_id?: number | null
  type: string
  types: string[]
  user_scale: string
  is_public: boolean
  pm_name?: string | null
  dev_lead_name?: string | null
  sec_contact_name?: string | null
  compliance_targets: string[]
  status: string
  created_at?: string | null
  /** 评估继承: 创建时复制该评估全部向导数据(仅创建请求使用) */
  from_project_id?: number | null
}

export interface ProjectDetail extends ProjectInfo {
  has_survey: boolean
  grading_level?: string | null
  counts: Record<string, number>
  system_name?: string | null
  filing_name?: string | null
  filing_level?: string | null
  is_current_baseline?: boolean
}

/* ── 系统台账: 定级备案 / 被评估系统 / 评估轮次 ── */

export interface RoundSummary {
  project_id: number
  project_name: string
  project_code: string
  status: string
  created_at?: string | null
  grading_level: string
  requirements_total: number
  requirements_open: number
}

export interface FilingRow {
  id: number
  name: string
  code?: string | null
  level: string
  note?: string | null
  created_at?: string | null
  system_count?: number
  latest_round?: RoundSummary | null
}

export interface SystemRow {
  id: number
  name: string
  code?: string | null
  /** NetBox custom-objects 对象 id(#154, 推送成功后回填) */
  netbox_object_id?: string | null
  filing_id?: number | null
  owner_name?: string | null
  /** ── 基本信息(#194 自评估上收, 系统承载) ── */
  user_scale?: string | null
  types?: string[]
  is_public?: boolean
  created_at?: string | null
  filing_name?: string | null
  filing_level?: string | null
  current_baseline_project_id?: number | null
  rounds?: RoundSummary[]
  latest_round?: RoundSummary | null
}

/* 两轮需求增量对比(GET /requirements/diff) */
export interface DiffRow {
  req_id: string
  title: string
  priority: string
  category: string
  source_label?: string | null
  status: string
  suggested_phase: string
}

export interface RequirementDiff {
  comparable: boolean
  message?: string
  previous_project?: {
    project_id: number
    project_name: string
    project_code: string
    created_at?: string | null
  }
  added?: DiffRow[]
  removed?: DiffRow[]
  changed?: {
    fields: string[]
    /** 字段级前后值(#176): 变更常由 描述/验收标准 触发, 需展示旧值→新值 */
    field_values?: Record<string, { label: string; previous: string; current: string }>
    previous: DiffRow
    current: DiffRow
  }[]
  summary?: { current_total: number; previous_total: number; added: number; removed: number; changed: number }
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
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
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
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
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
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
  name: string
  role_type: string
}

export interface ExternalSystemRow {
  id?: number
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
  name: string
  purpose?: string | null
  direction: string
  involves_sensitive: boolean
}

export interface ResourceRow {
  id?: number
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
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
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
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
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
  name: string
  path: string
  method: string
  auth_required: boolean
  public_exposed: boolean
  /** @deprecated v2.3.0 起以 sensitive_asset_uids 为准 */
  sensitive_asset_ids?: number[]
  /** 关联敏感数据资产 uid 列表(#66) */
  sensitive_asset_uids: string[]
  rate_limit?: string | null
}

export interface InfraAssetRow {
  id?: number
  /** 稳定业务标识(#66): 保存时原样回传, 新增行留空由后端生成 */
  uid?: string
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
  /** NetBox 互通(#153): 导入/推送成功后回填的来源侧标识 */
  netbox_ref_type?: string | null
  netbox_ref_id?: string | null
}

export interface NetboxSystemRow {
  id: number
  name?: string | null
  code?: string | null
  owner?: string | null
  url?: string | null
}

export interface NetboxAssetRow {
  id: number
  name?: string | null
  primary_ip?: string | null
  site?: string | null
  role?: string | null
  device_type?: string | null
  platform?: string | null
  dns_name?: string | null
  address?: string | null
  status?: string | null
  url?: string | null
}

export interface InfraArchImageRow {
  env: string
  image_data_url: string
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
  /** 来源实体稳定标识(#66) */
  source_entity_uid?: string | null
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
  /** 中文名(后端统一下发, 前端不自映射) */
  label?: string
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
