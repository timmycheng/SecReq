/* 大模型接入: 内网请填行内 OpenAI 兼容网关; 留空则降级为关键词规则提取。 */
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Typography, message } from 'antd'

import { api, type LlmConfig } from '../../api'

export default function LlmTab() {
  const [cfg, setCfg] = useState<LlmConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.getLlmConfig().then((c) => { setCfg(c); form.setFieldsValue(c) })
      .catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="内网部署请填写行内大模型的接口地址"
          description="平台部署于无互联网出口的内网时, 公网大模型地址不可达。请填写行内已部署的
            OpenAI 兼容服务地址(如 https://llm-gate.corp.example.com/v1);
            留空则直接使用关键词规则提取, 功能不受影响。"
        />
        配置 OpenAI 兼容接口(/chat/completions)后, 功能清单的「粘贴需求段落自动生成」将使用大模型提取;
        未配置或调用失败时自动降级为关键词规则提取。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item name="base_url" label="接口地址" extra="如 https://llm-gate.corp.example.com/v1">
          <Input placeholder="https://..." />
        </Form.Item>
        <Form.Item name="api_key" label="API Key" extra={cfg?.api_key ? `当前: ${cfg.api_key}` : '未配置'}>
          <Input.Password placeholder="sk-..." />
        </Form.Item>
        <Form.Item name="model" label="模型名">
          <Input placeholder="如 glm-4 / qwen-max / gpt-4o-mini" />
        </Form.Item>
        <Button
          type="primary" loading={saving}
          onClick={async () => {
            const values = await form.validateFields()
            setSaving(true)
            try {
              await api.saveLlmConfig(values)
              message.success('已保存, 功能提取将使用大模型')
              reload()
            } catch (e) {
              message.error((e as Error).message)
            } finally {
              setSaving(false)
            }
          }}
        >
          保存配置
        </Button>
      </Form>
    </div>
  )
}
