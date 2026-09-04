/* 知识库触发条件编辑器(#81): 类目驱动表单替代手写 JSON。
   - type 用下拉(11 类, 中文标签来自 meta category_labels);
   - condition 按类目渲染对应字段(布尔开关/枚举下拉/列表多选);
   - 折叠「高级模式」保留原 JSON 编辑入口, 兜底复杂形态;
   - 未知 condition 键在表单切换时原样保留, 不丢数据。 */
import { useMemo } from 'react'
import { Input, Select, Space, Switch, Typography } from 'antd'

import type { Constants } from '../../api'
import { labelMapOf } from '../../enums'

export interface Trigger {
  type: string
  condition?: Record<string, unknown>
  [key: string]: unknown
}

type FieldType = 'select' | 'bool' | 'list'

interface FieldSpec {
  key: string
  label: string
  kind: FieldType
  /** select 的取值与文案; list 复用 options 的 value 部分 */
  options?: { value: string; label: string }[]
}

interface TypeSpec {
  /** condition 字段定义 */
  fields: FieldSpec[]
  note?: string
}

const RISK_OPTS = [
  { value: 'high', label: '高风险' },
  { value: 'medium', label: '中风险(含 medium 及以上)' },
]
const SEVERITY_OPTS = ['critical', 'high', 'medium', 'low']

const PERMISSION_RULE_KEYS = [
  { value: 'critical_action_without_approval', label: '关键资源高危操作免审批' },
  { value: 'sod_conflict', label: '职责分离(SoD)冲突' },
  // 修复(#165): 原选项值 super_admin 与引擎分派键 super_admin_exists 漂移,
  // 选了会生成永不命中的模板(引擎按 rule_key if/else 硬编码分派)
  { value: 'super_admin_exists', label: '超级管理员角色存在' },
  { value: 'always', label: '存在权限矩阵即触发' },
]
const POLICY_RULE_KEYS = [
  { value: 'password_strength', label: '口令强度' },
  { value: 'lockout_threshold', label: '登录失败锁定' },
  { value: 'session_timeout', label: '会话超时' },
  { value: 'force_2fa', label: '强制双因素认证' },
]
const REGULATORY_RULE_KEYS = [
  { value: 'l5_data_exists', label: '存在 5级(重要数据)资产' },
  { value: 'cross_border_exists', label: '存在跨境传输或境外外包' },
  { value: 'mobile_app_type', label: '评估类型为 APP/小程序' },
  { value: 'ai_feature', label: '功能清单含 AI 功能' },
  { value: 'final_level_l3', label: '有效定级为三级' },
  { value: 'sensitive_pii_exists', label: '存在敏感个人信息资产' },
  { value: 'djcp_l3_filing', label: '三级系统等保测评与备案' },
]

/** 各类目的 condition 字段定义; 未列出的类目为空 condition。 */
export function typeSpecs(enums: Constants): Record<string, TypeSpec> {
  const featureCats = Object.entries((enums['feature_categories'] as Record<string, string>) ?? {})
    .map(([value, label]) => ({ value, label }))
  const levels = Object.keys((enums['data_level_labels'] as Record<string, string>) ?? {})
    .map((v) => ({ value: v, label: v }))
  const maskKinds = Object.keys((enums['mask_field_patterns'] as Record<string, string>) ?? {})
    .map((v) => ({ value: v, label: v }))
  const compliance = Object.entries((enums['compliance_targets'] as Record<string, string>) ?? {})
    .map(([value, label]) => ({ value, label }))
  const methods = ((enums['auth_methods'] as Record<string, string>) ?? {})
  const methodOpts = Object.entries(methods).map(([value, label]) => ({ value, label: `${label}(${value})` }))

  const ruleKey = (opts: { value: string; label: string }[]): FieldSpec[] => [
    { key: 'rule_key', label: '规则', kind: 'select', options: opts },
  ]
  const cond = (key: string, label: string): FieldSpec => ({ key, label, kind: 'bool' })

  return {
    feature_category: {
      fields: [{ key: 'category', label: '功能分类', kind: 'select', options: featureCats }],
    },
    data_asset: {
      fields: [
        { key: 'classification', label: '精确分级', kind: 'select', options: levels },
        { key: 'level', label: '等级(精确)', kind: 'select', options: levels },
        { key: 'min_level', label: '最低等级(含以上)', kind: 'select', options: levels },
        cond('c3_tag', 'C3 鉴别信息标签'),
        cond('is_sensitive_pii', '敏感个人信息'),
        cond('has_log_leakage_risk', '存在日志存储环境'),
        cond('cross_border', '存在跨境传输'),
        { key: 'mask_fields_any_of', label: '命中任一脱敏字段类型', kind: 'list', options: maskKinds },
      ],
      note: '分级/等级/最低等级三者填其一; 布尔条件可叠加',
    },
    api_endpoint: {
      fields: [cond('public_exposed', '公网暴露'), cond('auth_required', '免认证(注意: 勾选=要求"免认证")'),
        cond('touches_sensitive_asset', '关联敏感数据资产')],
      note: '布尔条件语义为"必须为真"; 不填则不参与判定',
    },
    permission_rule: { fields: ruleKey(PERMISSION_RULE_KEYS) },
    policy_baseline: { fields: ruleKey(POLICY_RULE_KEYS) },
    regulatory_trigger: { fields: ruleKey(REGULATORY_RULE_KEYS) },
    license_risk: {
      fields: [{ key: 'risk', label: '许可证风险阈值', kind: 'select', options: RISK_OPTS }],
    },
    compliance: {
      fields: [{ key: 'target', label: '合规目标', kind: 'select', options: compliance }],
    },
    vulnerability: {
      fields: [{ key: 'severity_range', label: '严重度区间(取最不严重档为阈值)', kind: 'list',
        options: SEVERITY_OPTS.map((v) => ({ value: v, label: v })) }],
    },
    auth_method: {
      fields: [{ key: 'method', label: '认证方式', kind: 'select', options: methodOpts }],
    },
    external_system: { fields: [cond('sensitive_only', '仅命中涉敏感数据交互的系统')] },
  }
}

export default function TriggerEditor({ value, onChange, enums }: {
  value: Trigger
  onChange: (next: Trigger) => void
  enums: Constants
}) {
  const typeLabels = labelMapOf(enums, 'category_labels')
  const specs = useMemo(() => typeSpecs(enums), [enums])
  const spec = specs[value.type]
  const condition = value.condition ?? {}

  const setCondition = (key: string, v: unknown) => {
    const nextCondition = { ...condition }
    if (v === undefined || v === '' || (Array.isArray(v) && !v.length)) delete nextCondition[key]
    else nextCondition[key] = v
    onChange({ ...value, condition: nextCondition })
  }

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Space size={12} wrap style={{ width: '100%' }}>
        <Typography.Text type="secondary">触发类目</Typography.Text>
        <Select
          style={{ width: 200 }}
          value={value.type}
          onChange={(t) => {
            const next: Trigger = { type: t }
            const nextSpec = specs[t]
            // 换类目时保留能对上字段的 condition(如 rule_key → rule_key)
            if (nextSpec && nextSpec.fields.some((f) => f.key === 'rule_key') && condition.rule_key) {
              next.condition = { rule_key: condition.rule_key }
            }
            onChange(next)
          }}
          options={Object.entries(typeLabels).map(([v, label]) => ({ value: v, label: `${label}(${v})` }))}
        />
      </Space>
      {spec?.note && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{spec.note}</Typography.Text>}
      {(spec?.fields ?? []).map((field) => {
        const current = condition[field.key]
        if (field.kind === 'bool') {
          return (
            <Space key={field.key} size={8} style={{ display: 'flex' }} align="center">
              <Typography.Text>{field.label}</Typography.Text>
              <Switch
                size="small"
                checked={current === true}
                onChange={(checked) => setCondition(field.key, checked ? true : undefined)}
              />
            </Space>
          )
        }
        return (
          <Space key={field.key} size={8} style={{ display: 'flex' }} align="center">
            <Typography.Text type="secondary" style={{ width: 190, display: 'inline-block' }}>{field.label}</Typography.Text>
            {field.kind === 'select' ? (
              <Select
                style={{ width: 280 }}
                allowClear
                showSearch
                placeholder="不填则不参与判定"
                value={typeof current === 'string' ? current : undefined}
                options={field.options ?? []}
                onChange={(v) => setCondition(field.key, v)}
              />
            ) : (
              <Select
                mode="multiple" style={{ width: 280 }} allowClear
                placeholder="可多选"
                value={Array.isArray(current) ? current.map(String) : []}
                options={field.options ?? []}
                onChange={(vals) => setCondition(field.key, vals)}
              />
            )}
          </Space>
        )
      })}
      {!spec && (
        <Input
          placeholder="该类目暂无表单定义, 请展开高级模式编辑 JSON"
          disabled
        />
      )}
      {spec && Object.keys(condition).length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          当前 condition: {JSON.stringify(condition)}
        </Typography.Text>
      )}
    </Space>
  )
}
