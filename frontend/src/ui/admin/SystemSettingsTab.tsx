/* 系统设置: 评估编号规则(前缀/年份/位数), 带实时格式预览(#85)。
   未配置时后端回退历史格式 XM<年份>-<三位序号>, 老评估编号不受影响。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Checkbox, Form, Input, InputNumber, Typography, message } from 'antd'

import { api } from '../../api'

interface CodeRule {
  prefix: string
  include_year: boolean
  digits: number
}

export default function SystemSettingsTab() {
  const [rule, setRule] = useState<CodeRule | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<CodeRule>()

  const reload = useCallback(() => {
    api.getProjectCodeRule()
      .then((r) => { setRule(r); form.setFieldsValue(r) })
      .catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  const watched = Form.useWatch([], form)
  const preview = useMemo(() => {
    const current = watched ?? rule
    if (!current?.prefix) return '—'
    const year = new Date().getFullYear()
    const digits = typeof current.digits === 'number' ? current.digits : 3
    return `${current.prefix}${current.include_year ? year : ''}-${'0'.repeat(Math.max(digits - 1, 0))}1`
  }, [watched, rule])

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        评估编号在发起新评估时自动生成, 同时用作产物输出目录名 —— 修改规则只影响新评估,
        老评估编号与目录不变。序号按前缀查库递增保证不冲突。
      </Typography.Paragraph>
      <Card size="small" title="评估编号规则" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical" initialValues={rule ?? undefined}>
          <Form.Item
            name="prefix" label="前缀(1-10 位字母数字)"
            rules={[{ required: true }, { pattern: /^[A-Za-z0-9]+$/, message: '仅字母数字' }]}
          >
            <Input placeholder="如 XM / PRJ" maxLength={10} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="include_year" valuePropName="checked">
            <Checkbox>编号包含当前年份</Checkbox>
          </Form.Item>
          <Form.Item name="digits" label="序号位数" extra="1-6 位, 不足补零">
            <InputNumber min={1} max={6} style={{ width: 120 }} />
          </Form.Item>
          <Typography.Paragraph style={{ marginBottom: 12 }}>
            下一个编号预览: <code>{preview}</code>
          </Typography.Paragraph>
          <Button
            type="primary" loading={saving}
            onClick={async () => {
              const values = await form.validateFields()
              setSaving(true)
              try {
                const saved = await api.saveProjectCodeRule(values)
                setRule(saved)
                message.success('编号规则已保存')
              } catch (e) {
                message.error((e as Error).message)
              } finally {
                setSaving(false)
              }
            }}
          >
            保存规则
          </Button>
        </Form>
      </Card>
    </div>
  )
}
