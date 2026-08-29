/* 系统管理(仅安全角色): 知识库/定级题库/策略基线/大模型接入/用户管理/审计日志。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space,
  Spin, Switch, Table, Tabs, Tag, Typography, message,
  Result,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'

import { api, getStoredUser } from '../api'
import type {
  AdminUserRow, AuditLogRow, KbTemplateRow, LlmConfig, PolicyBaselines, QuestionBank,
} from '../api'
import { labelMapOf, useEnums } from '../enums'

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}

export default function AdminPage() {
  // 后端仅安全角色可访问; 前端同步给非安全角色明确的 403 提示
  if (getStoredUser()?.role !== 'security') {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Result status="403" title="403" subTitle="系统管理仅安全角色可访问" />
        </Card>
      </div>
    )
  }
  return (
    <div style={{ padding: 24 }}>
      <Card>
        <Tabs
          items={[
            { key: 'kb', label: '知识库', children: <KbTab /> },
            { key: 'questions', label: '定级题库', children: <QuestionTab /> },
            { key: 'policy', label: '密码策略基线', children: <PolicyTab /> },
            { key: 'llm', label: '大模型接入', children: <LlmTab /> },
            { key: 'users', label: '用户管理', children: <UsersTab /> },
            { key: 'audit', label: '审计日志', children: <AuditTab /> },
          ]}
        />
      </Card>
    </div>
  )
}

/* ── 知识库管理 ── */
function KbTab() {
  const enums = useEnums()
  const [rows, setRows] = useState<KbTemplateRow[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<KbTemplateRow | null>(null)
  const categoryLabels = labelMapOf(enums, 'category_labels')

  const reload = useCallback(() => {
    setLoading(true)
    api.listKb(keyword || undefined)
      .then((r) => setRows(r.templates))
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [keyword])
  useEffect(reload, [reload])

  const toggle = async (row: KbTemplateRow) => {
    try {
      await api.updateKbTemplate(row.id, { enabled: !row.enabled })
      message.success(`${row.id} 已${row.enabled ? '停用' : '启用'}`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="按 id 或标题搜索" allowClear style={{ width: 280 }}
          onSearch={setKeyword}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        <Typography.Text type="secondary">
          共 {rows.length} 条模板 · 停用后生成时跳过; 编辑写回 YAML 自动备份, 保存时全量校验
        </Typography.Text>
      </Space>
      <Table<KbTemplateRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 15, showSizeChanger: false }}
        size="small"
        columns={[
          { title: '编号', dataIndex: 'id', width: 160 },
          { title: '标题', dataIndex: 'title' },
          { title: '类目', dataIndex: 'trigger_type', width: 140,
            render: (v) => <Tag>{categoryLabels[v] ?? v}</Tag> },
          { title: '优先级', dataIndex: 'priority', width: 80,
            render: (v) => <Tag color={PRIORITY_COLOR[v]}>{labelMapOf(enums, 'priority_labels')[v] ?? v}</Tag> },
          { title: '启用', dataIndex: 'enabled', width: 80,
            render: (_v, r) => <Switch size="small" checked={r.enabled} onChange={() => void toggle(r)} /> },
          {
            title: '操作', width: 80,
            render: (_v, r) => <Button size="small" onClick={() => setEditing(r)}>编辑</Button>,
          },
        ]}
      />
      {editing && (
        <KbEditModal
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </>
  )
}

function KbEditModal({ row, onClose, onSaved }: {
  row: KbTemplateRow
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  return (
    <Modal
      title={`编辑知识库模板 ${row.id}`} open onCancel={onClose} width={760}
      confirmLoading={saving}
      onOk={async () => {
        const values = await form.validateFields()
        let trigger = values.trigger
        if (typeof trigger === 'string') {
          try {
            trigger = JSON.parse(trigger)
          } catch {
            message.error('触发条件不是合法 JSON, 请检查后重试')
            return
          }
        }
        setSaving(true)
        try {
          await api.updateKbTemplate(row.id, { ...values, trigger })
          message.success('已保存')
          onSaved()
        } catch (e) {
          message.error((e as Error).message)
        } finally {
          setSaving(false)
        }
      }}
    >
      <Form form={form} layout="vertical" initialValues={{
        ...row,
        trigger: JSON.stringify(row.trigger ?? {}, null, 2),
      }}>
        <Form.Item name="title" label="标题" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="需求描述(生成后的需求正文, 支持 {{占位符}})">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="acceptance_criteria" label="验收标准">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="trigger_reason" label="触发原因(展示给填报人)">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="priority" label="优先级">
              <Select options={['critical', 'high', 'medium', 'low'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="suggested_phase" label="建议阶段">
              <Select options={['design', 'development', 'test'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="asvs_ref" label="ASVS 条款">
              <Input placeholder="如 V1.1.2" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="trigger"
          label="触发条件(JSON)"
          extra="触发条件结构因类目而异, 修改前请先弄清原结构; 保存时后端会全量校验"
        >
          <Input.TextArea rows={4} style={{ fontFamily: 'monospace', fontSize: 12 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/* ── 定级题库 ── */
function QuestionTab() {
  const [bank, setBank] = useState<QuestionBank | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(() => {
    api.getQuestionBank().then(setBank).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  const save = async () => {
    if (!bank) return
    setSaving(true)
    try {
      await api.saveQuestionBank(bank)
      message.success('题库已保存并即时生效')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!bank) return <Spin />

  const updateOption = (qi: number, oi: number, patch: Partial<QuestionBank['questions'][0]['options'][0]>) => {
    const copy: QuestionBank = JSON.parse(JSON.stringify(bank))
    Object.assign(copy.questions[qi].options[oi], patch)
    setBank(copy)
  }

  return (
    <>
      <Typography.Paragraph type="secondary">
        题目分值与组合规则决定自动定级建议。此处调整选项分值; 保存后立即对新提交的问卷生效。
      </Typography.Paragraph>
      {bank.questions.map((q, qi) => (
        <Card
          key={q.id} size="small" title={`${q.id}. ${q.title}`} style={{ marginBottom: 12 }}
          extra={<Tag>命中组合: {bank.levels.find((l) => l.level)?.level ?? ''}</Tag>}
        >
          {q.options.map((o, oi) => (
            <Space key={o.id} size={8} style={{ display: 'flex', marginBottom: 6 }}>
              <Tag style={{ minWidth: 28, textAlign: 'center' }}>{o.id}</Tag>
              <Input style={{ width: 300 }} value={o.label}
                onChange={(e) => updateOption(qi, oi, { label: e.target.value })} />
              <InputNumber min={0} max={20} value={o.score}
                onChange={(v) => updateOption(qi, oi, { score: typeof v === 'number' ? v : 0 })} />
              <Typography.Text type="secondary">分</Typography.Text>
              <Input style={{ width: 320 }} value={o.basis ?? ''} placeholder="判定依据文案"
                onChange={(e) => updateOption(qi, oi, { basis: e.target.value })} />
            </Space>
          ))}
        </Card>
      ))}
      <Button type="primary" loading={saving} onClick={() => void save()}>保存题库</Button>
    </>
  )
}

/* ── 密码策略基线 ── */
function PolicyTab() {
  const [data, setData] = useState<PolicyBaselines | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(() => {
    api.getPolicyBaselines().then(setData).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  if (!data) return <Spin />

  const update = (level: string, key: string, value: number | null) => {
    const copy: PolicyBaselines = JSON.parse(JSON.stringify(data))
    if (value !== null) copy.baselines[level][key as keyof PolicyBaselines['baselines'][string]] = value
    setData(copy)
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <Typography.Paragraph type="secondary">
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

function NumField({ label, value, onChange }: {
  label: string
  value: number
  onChange: (v: number | null) => void
}) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <InputNumber style={{ width: 140 }} value={value} min={1} onChange={(v) => onChange(v ?? null)} />
    </Space>
  )
}

/* ── 大模型接入 ── */
function LlmTab() {
  const [cfg, setCfg] = useState<LlmConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.getLlmConfig().then((c) => { setCfg(c); form.setFieldsValue(c) })
      .catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  return (
    <div style={{ maxWidth: 640 }}>
      <Typography.Paragraph type="secondary">
        配置 OpenAI 兼容接口(/chat/completions)后, 功能清单的「粘贴需求段落自动生成」将使用大模型提取;
        未配置或调用失败时自动降级为关键词规则提取。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item name="base_url" label="接口地址" extra="如 https://llm-gate.example.com/v1">
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

/* ── 用户管理 ── */
function UsersTab() {
  const [rows, setRows] = useState<AdminUserRow[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.adminListUsers().then(setRows).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增用户</Button>
        <Typography.Text type="secondary">新用户未指定密码时由系统生成随机初始密码, 创建后弹窗展示</Typography.Text>
      </Space>
      <Table<AdminUserRow>
        rowKey="username" dataSource={rows} pagination={false} size="small"
        columns={[
          { title: '用户名', dataIndex: 'username' },
          { title: '姓名', dataIndex: 'display_name' },
          { title: '工号', dataIndex: 'employee_id', render: (v) => v || '—' },
          { title: '角色', dataIndex: 'role', width: 100,
            render: (v) => <Tag color={v === 'security' ? 'orange' : 'geekblue'}>{v === 'security' ? '安全' : '开发'}</Tag> },
          { title: '状态', dataIndex: 'active', width: 90,
            render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
          {
            title: '操作', width: 220,
            render: (_v, r) => (
              <Space>
                <Popconfirm
                  title={`重置 ${r.display_name} 的密码? 将生成随机密码。`}
                  onConfirm={async () => {
                    try {
                      const res = await api.adminResetPassword(r.username)
                      message.success(`已重置, 新密码 ${res.password ?? '-'}`, 8)
                    } catch (e) { message.error((e as Error).message) }
                  }}
                >
                  <Button size="small">重置密码</Button>
                </Popconfirm>
                <Button size="small" danger={r.active} onClick={async () => {
                  try {
                    const res = await api.adminToggleUser(r.username)
                    message.success(`${r.username} 已${res.active ? '启用' : '停用'}`)
                    reload()
                  } catch (e) { message.error((e as Error).message) }
                }}>
                  {r.active ? '停用' : '启用'}
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="新增用户" open={createOpen} onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await form.validateFields()
          try {
            const res = await api.adminCreateUser(values)
            message.success(`已创建, 初始密码 ${res.initial_password}`)
            setCreateOpen(false)
            form.resetFields()
            reload()
          } catch (e) {
            message.error((e as Error).message)
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input placeholder="如 dev_wang" />
          </Form.Item>
          <Form.Item name="display_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="employee_id" label="工号(可选)">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]} initialValue="developer">
            <Select options={[
              { value: 'developer', label: '开发' },
              { value: 'security', label: '安全' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

/* ── 审计日志 ── */
function AuditTab() {
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [loading, setLoading] = useState(false)

  const reload = useCallback(() => {
    setLoading(true)
    api.listAuditLogs()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        <Typography.Text type="secondary">最近 {rows.length} 条(登录/生成/确认/知识库与用户管理变更)</Typography.Text>
      </Space>
      <Table<AuditLogRow>
        rowKey="id" loading={loading} dataSource={rows} size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 180 },
          { title: '操作人', dataIndex: 'username', width: 120 },
          { title: '动作', dataIndex: 'action', width: 160,
            render: (v) => <Tag>{v}</Tag> },
          { title: '明细', dataIndex: 'detail',
            render: (d: Record<string, unknown>) => <code style={{ fontSize: 12 }}>{JSON.stringify(d)}</code> },
          { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '—' },
        ]}
      />
    </>
  )
}
