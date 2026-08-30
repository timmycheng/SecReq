/* 密码策略基线: 各等保档位的默认取值, 项目未显式覆盖时按此填充。 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Space, Spin, Typography, message } from 'antd'

import { api, type PolicyBaselines } from '../../api'
import { NumField } from './shared'

export default function PolicyTab() {
  const [data, setData] = useState<PolicyBaselines | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(() => {
    api.getPolicyBaselines().then(setData).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  if (!data) return <Spin style={{ display: 'block', margin: '40px auto' }} />

  const update = (level: string, key: string, value: number | null) => {
    const copy: PolicyBaselines = JSON.parse(JSON.stringify(data))
    if (value !== null) copy.baselines[level][key as keyof PolicyBaselines['baselines'][string]] = value
    setData(copy)
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        各定级档位的默认密码基线; 项目未显式覆盖时按此取值, 保存后对新预览与生成即时生效。
      </Typography.Paragraph>
      {Object.entries(data.baselines).map(([level, base]) => (
        <Card key={level} size="small" title={`等保${level}`} style={{ marginBottom: 12 }}>
          <Space size={24} wrap>
            <NumField label="最小长度" value={base.pwd_min_length}
              onChange={(v) => update(level, 'pwd_min_length', v)} />
            <NumField label="复杂度类别数" value={base.pwd_complexity}
              onChange={(v) => update(level, 'pwd_complexity', v)} />
            <NumField label="有效期(天)" value={base.pwd_valid_days}
              onChange={(v) => update(level, 'pwd_valid_days', v)} />
          </Space>
        </Card>
      ))}
      <Space size={24} style={{ marginBottom: 16 }}>
        <NumField label="全局锁定阈值(次)" value={data.lockout_threshold}
          onChange={(v) => v !== null && setData({ ...data, lockout_threshold: v })} />
        <NumField label="全局会话超时(分钟)" value={data.session_timeout_min}
          onChange={(v) => v !== null && setData({ ...data, session_timeout_min: v })} />
      </Space>
      <div>
        <Button
          type="primary" loading={saving}
          onClick={async () => {
            setSaving(true)
            try {
              await api.savePolicyBaselines(data)
              message.success('策略基线已保存')
            } catch (e) {
              message.error((e as Error).message)
            } finally {
              setSaving(false)
            }
          }}
        >
          保存基线
        </Button>
      </div>
    </div>
  )
}
