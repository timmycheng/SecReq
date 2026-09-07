/* LLM 管理(#280, 自系统管理 Tab 独立): 第三方大模型接入配置 + 连接测试。
   配置 OpenAI 兼容接口后功能提取使用大模型; 未配置或调用失败自动降级规则提取。
   内网部署请填写行内网关地址; 留空则直接使用关键词规则提取。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Form, Input, Row, Space, Tag, Typography, message,
} from 'antd'
import { ApiOutlined } from '@ant-design/icons'

import { api, type LlmConfig } from '../api'
import PageHeader from './PageHeader'

export default function LlmPage() {
  const [cfg, setCfg] = useState<LlmConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; latency_ms?: number; reply?: string; reason?: string } | null>(null)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.getLlmConfig().then((c) => { setCfg(c); form.setFieldsValue(c) })
      .catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="LLM 管理"
        description="功能清单「粘贴需求段落自动生成」依赖的大模型服务"
        extra={(
          <Space>
            <Button
              icon={<ApiOutlined />} loading={testing}
              onClick={async () => {
                const values = await form.validateFields()
                setTesting(true)
                setTestResult(null)
                try {
                  setTestResult(await api.testLlmConfig(values))
                } catch (e) {
                  message.error((e as Error).message)
                } finally {
                  setTesting(false)
                }
              }}
            >
              连接测试
            </Button>
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
          </Space>
        )}
      />
      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title="接入配置" style={{ marginBottom: 16 }}>
            <Form form={form} layout="vertical">
              <Form.Item name="base_url" label="接口地址" extra="OpenAI 兼容 /chat/completions, 如 https://llm-gate.corp.example.com/v1">
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item name="api_key" label="API Key" extra={cfg?.api_key ? `当前: ${cfg.api_key}` : '未配置'}>
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item name="model" label="模型名">
                <Input placeholder="如 glm-4 / qwen-max / gpt-4o-mini" />
              </Form.Item>
            </Form>
            {testResult && (
              <Alert
                type={testResult.ok ? 'success' : 'error'}
                showIcon
                message={testResult.ok
                  ? `连接成功(${testResult.latency_ms}ms)`
                  : `连接失败: ${testResult.reason ?? '未知原因'}`}
                description={testResult.ok && testResult.reply ? `模型响应: ${testResult.reply}` : undefined}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="运行说明" style={{ marginBottom: 16 }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Typography.Text>
                当前状态:
                {cfg?.configured
                  ? <Tag color="green" style={{ marginLeft: 8 }}>已配置, 生成走大模型</Tag>
                  : <Tag style={{ marginLeft: 8 }}>未配置, 降级为关键词规则提取</Tag>}
              </Typography.Text>
              <Typography.Text type="secondary">
                生成流程: 评估问卷清单 → 知识库触发匹配 → 大模型归纳 → 需求确认。
                未配置或调用失败时自动回落规则生成, 功能不受影响。
              </Typography.Text>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
