/* Step6 身份认证与密码策略设计器:
   按 Step2 定级给出默认基线(服务端 /auth-defaults 同一口径), 允许逐项调整;
   留空项在生成需求时自动取基线值。 */
import { useRef, useState } from 'react'
import { useEffect } from 'react'
import {
  Alert, Button, Checkbox, InputNumber, Select, Space, Spin, Typography, message,
} from 'antd'

import { api } from '../../api'
import { optionsOf, useEnums } from '../../enums'
import type { AuthConfigRow } from '../../types'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const DEFAULT_CFG: AuthConfigRow = {
  auth_methods: ['password'],
  pwd_min_length: null, pwd_complexity: null, pwd_valid_days: null,
  lockout_threshold: null, pwd_history_limit: null,
  force_2fa: false, session_timeout_min: null, concurrent_limit: null,
}

export default function Step6AuthPolicy({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [cfg, setCfg] = useState<AuthConfigRow>(ws.auth_config ?? DEFAULT_CFG)
  const [defaults, setDefaults] = useState<{ grading_level: string; defaults: Record<string, number> } | null>(null)
  const savedRef = useRef(JSON.stringify(ws.auth_config ?? DEFAULT_CFG))

  useEffect(() => {
    api.getAuthDefaults(ws.project.id).then(setDefaults).catch((e: Error) => message.error(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (): Promise<boolean> => {
    if (!cfg.auth_methods.length) {
      message.warning('请至少勾选一种认证方式')
      return false
    }
    try {
      const saved = await api.saveAuthConfig(ws.project.id, cfg)
      patch({ auth_config: saved })
      savedRef.current = JSON.stringify(cfg)
      message.success('认证与密码策略已保存')
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => JSON.stringify(cfg) !== savedRef.current })

  if (!defaults) return <Spin style={{ display: 'block', margin: '60px auto' }} />
  const d = defaults.defaults
  const clearOverrides = () => {
    setCfg({
      ...cfg,
      pwd_min_length: null, pwd_complexity: null, pwd_valid_days: null,
      lockout_threshold: null, pwd_history_limit: null,
      session_timeout_min: null, concurrent_limit: null,
    })
    message.success('已清空手动覆盖, 生成需求时将按定级基线自动取默认值')
  }

  const userScaleOver10w = ['100k_to_1m', 'over_1m'].includes(ws.project.user_scale)

  return (
    <div style={{ maxWidth: 820, margin: '0 auto' }}>
      <Alert
        type="info"
        showIcon
        message={`当前有效定级: ${ws.survey?.effective_level || defaults.grading_level || '未定级'} — 密码策略默认基线据此推导`}
        description={(
          <Space direction="vertical" size={2}>
            <span>
              默认基线: 最小长度 {d.pwd_min_length} · 复杂度 {d.pwd_complexity}/4 类 · 有效期 {d.pwd_valid_days} 天 ·
              锁定阈值 {d.lockout_threshold} 次 · 会话超时 {d.session_timeout_min} 分钟
            </span>
            <span>
              输入框留空即代表采用基线值(placeholder 中有默认值); 点「清空手动覆盖」可一次性恢复全部默认。
            </span>
          </Space>
        )}
      />

      <Typography.Title level={5} style={{ marginTop: 20 }}>认证方式(多选)</Typography.Title>
      <Checkbox.Group
        value={cfg.auth_methods}
        options={optionsOf(enums, 'auth_methods')}
        onChange={(vals) => setCfg({ ...cfg, auth_methods: vals as string[] })}
      />
      {userScaleOver10w && !cfg.force_2fa && (
        <Alert style={{ marginTop: 12 }} type="warning" showIcon
          message="用户规模超过 10 万, 行内指引建议强制开启 2FA(规则引擎会输出建议需求)" />
      )}

      <Typography.Title level={5} style={{ marginTop: 24 }}>密码策略</Typography.Title>
      <Space size={20} wrap align="start">
        <NumField label="最小长度" value={cfg.pwd_min_length} placeholder={`${d.pwd_min_length}(默认)`}
          min={6} max={64}
          onChange={(v) => setCfg({ ...cfg, pwd_min_length: v })} />
        <Space direction="vertical" size={0}>
          <Typography.Text type="secondary">复杂度类别数</Typography.Text>
          <Select
            style={{ width: 170 }}
            value={cfg.pwd_complexity ?? undefined}
            placeholder={`默认 ${d.pwd_complexity}`}
            options={[3, 4].map((n) => ({ value: n, label: `${n} 类` }))}
            onChange={(v) => setCfg({ ...cfg, pwd_complexity: v })}
          />
        </Space>
        <NumField label="有效期(天)" value={cfg.pwd_valid_days} placeholder={`${d.pwd_valid_days}(默认)`}
          min={1} max={3650}
          onChange={(v) => setCfg({ ...cfg, pwd_valid_days: v })} />
        <NumField label="错误锁定阈值(次)" value={cfg.lockout_threshold} placeholder={`${d.lockout_threshold}(默认)`}
          min={1} max={100}
          onChange={(v) => setCfg({ ...cfg, lockout_threshold: v })} />
        <NumField label="历史密码不重复次数" value={cfg.pwd_history_limit} placeholder={`默认 ${d.pwd_history_limit}`}
          min={0} max={24}
          onChange={(v) => setCfg({ ...cfg, pwd_history_limit: v })} />
        <Checkbox checked={cfg.force_2fa}
          onChange={(e) => setCfg({ ...cfg, force_2fa: e.target.checked })}>
          强制双因素认证(2FA)
        </Checkbox>
      </Space>

      <Typography.Title level={5} style={{ marginTop: 24 }}>会话策略</Typography.Title>
      <Space size={20} wrap>
        <NumField label="会话超时(分钟)" value={cfg.session_timeout_min} placeholder={`${d.session_timeout_min}(默认)`}
          min={1} max={1440}
          onChange={(v) => setCfg({ ...cfg, session_timeout_min: v })} />
        <NumField label="单点登录并发限制" value={cfg.concurrent_limit} placeholder={`默认 ${d.concurrent_limit}`}
          min={1} max={99}
          onChange={(v) => setCfg({ ...cfg, concurrent_limit: v })} />
      </Space>

      <div style={{ marginTop: 24 }}>
        <Button onClick={clearOverrides}>清空手动覆盖</Button>
      </div>
    </div>
  )
}

function NumField({ label, value, onChange, placeholder, min, max }: {
  label: string
  value: number | null | undefined
  onChange: (v: number | null) => void
  placeholder?: string
  min?: number
  max?: number
}) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <InputNumber
        style={{ width: 160 }}
        value={value ?? undefined}
        placeholder={placeholder}
        min={min}
        max={max}
        onChange={(v) => onChange(typeof v === 'number' ? v : null)}
      />
    </Space>
  )
}
