/* Step3 功能清单: 手工增删 + 粘贴业务需求段落自动生成候选(大模型优先, 规则降级)。 */
import { useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, Form, Input, Modal, Popconfirm, Select, Space, Spin,
  Switch, Table, Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SnippetsOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'
import type { FeatureRow } from '../../types'

interface CandidateFeature extends FeatureRow {
  source_quote?: string | null
}

const EMPTY: FeatureRow = {
  name: '', module: '', categories: [], sensitivity: 'internal',
  involves_payment: false, exposed_to_internet: false,
}

/** 功能分类 → 该分类通常触发的安全需求(前端提示文案, 与知识库 trigger 对应)。 */
const CATEGORY_HINTS: Record<string, string> = {
  auth_login: '敏感操作二次认证、登录防护类需求',
  password_mgmt: '改密/找回流程身份复核、验证码防轰炸',
  file_upload: '文件类型白名单、病毒查杀、存储隔离',
  file_download: '下载接口路径穿越防护与鉴权',
  payment: '交易幂等与防重复提交、金额服务端校验',
  refund: '退款额度限制与人工审批',
  order: '交易记录完整性保护类需求',
  export_data: '导出权限管控与审计留痕、导出内容脱敏',
  message_push: '推送内容默认脱敏',
  comment_ugc: 'UGC 内容 XSS 过滤与富文本净化',
  api_open: '开放接口鉴权、限流与签名类需求',
  admin_console: '管理后台访问面收敛、审计日志完整性',
  third_auth: 'OAuth state 防 CSRF 与回调白名单',
  ai_feature: 'AI 输入输出内容安全类需求',
  audit_log: '审计日志完整性保护',
  search: '搜索防 SQL 注入与参数化查询',
  sms_email: '短信/邮件验证码发送频控与防轰炸',
}

export default function Step3Features({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<FeatureRow[]>(ws.features)
  const [editing, setEditing] = useState<FeatureRow | null>(null)
  const [editIndex, setEditIndex] = useState<number>(-1)
  const [pasteOpen, setPasteOpen] = useState(false)
  const savedRef = useRef(JSON.stringify(rows))

  const openAdd = () => { setEditIndex(-1); setEditing({ ...EMPTY }) }
  const openEdit = (index: number) => { setEditIndex(index); setEditing({ ...rows[index] }) }
  const applyEdit = (next: FeatureRow) => {
    const copy = [...rows]
    if (editIndex >= 0) copy[editIndex] = next
    else copy.push(next)
    setRows(copy)
    setEditing(null)
  }

  const categoryMap = labelMapOf(enums, 'feature_categories')

  const save = async (): Promise<boolean> => {
    if (!rows.length) {
      message.warning('请至少录入一个功能')
      return false
    }
    try {
      const saved = await api.saveFeatures(ws.project.id, rows)
      patch({ features: saved })
      savedRef.current = JSON.stringify(rows)
      message.success(`已保存 ${saved.length} 个功能`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => JSON.stringify(rows) !== savedRef.current })

  return (
    <div style={{ maxWidth: 980, margin: '0 auto' }}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<PlusOutlined />} onClick={openAdd}>新增功能</Button>
        <Button type="primary" ghost icon={<SnippetsOutlined />} onClick={() => setPasteOpen(true)}>
          粘贴需求段落自动生成
        </Button>
        <Typography.Text type="secondary">
          本步录入系统对外提供的功能。共 {rows.length} 条 ·
          功能分类直接决定规则引擎触发的安全需求(新增时每个分类下有说明)
        </Typography.Text>
      </Space>

      <Table<FeatureRow>
        rowKey={(_, i) => String(i)}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: '功能名称', dataIndex: 'name' },
          { title: '所属模块', dataIndex: 'module', render: (v) => v || '—' },
          {
            title: '功能分类', dataIndex: 'categories',
            render: (cats: string[]) => cats.map((c) => <Tag key={c} color="blue">{categoryMap[c] ?? c}</Tag>),
          },
          { title: '敏感级别', dataIndex: 'sensitivity', render: (v: string) => labelMapOf(enums, 'sensitivity_levels')[v] ?? v },
          { title: '涉及资金', dataIndex: 'involves_payment', width: 90, render: (v: boolean) => (v ? <Tag color="red">是</Tag> : '否') },
          { title: '公网暴露', dataIndex: 'exposed_to_internet', width: 90, render: (v: boolean) => (v ? <Tag color="orange">是</Tag> : '否') },
          {
            title: '操作', width: 120,
            render: (_, __, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(index)} />
                <Popconfirm title="删除该功能?" onConfirm={() => setRows(rows.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <FeatureModal
        key={editing ? `edit-${editIndex}` : 'closed'}
        value={editing}
        onCancel={() => setEditing(null)}
        onOk={applyEdit}
      />

      <PasteExtractModal
        projectId={ws.project.id}
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        onConfirm={(picked) => {
          const existing = new Set(rows.map((r) => r.name))
          const fresh = picked.filter((r) => !existing.has(r.name))
          setRows([...rows, ...fresh.map(({ source_quote: _q, ...rest }) => rest)])
          setPasteOpen(false)
          const skipped = picked.length - fresh.length
          message.success(
            `已加入 ${fresh.length} 个功能点${skipped ? `(重名跳过 ${skipped} 个)` : ''}, 请点「保存并下一步」落库`)
        }}
      />
    </div>
  )
}

/** 粘贴业务需求段落 → 候选功能点勾选确认。 */
function PasteExtractModal({ projectId, open, onClose, onConfirm }: {
  projectId: number
  open: boolean
  onClose: () => void
  onConfirm: (picked: CandidateFeature[]) => void
}) {
  const enums = useEnums()
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [candidates, setCandidates] = useState<CandidateFeature[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const categoryMap = labelMapOf(enums, 'feature_categories')

  const doExtract = async () => {
    if (!text.trim()) { message.warning('请先粘贴需求内容'); return }
    setLoading(true)
    try {
      const resp = await api.extractFeatures(projectId, text)
      setCandidates(resp.candidates as CandidateFeature[])
      setNote(resp.note || (resp.mode === 'llm' ? '大模型提取' : '关键词规则提取'))
      setSelected(new Set(resp.candidates.map((_, i) => i)))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const toggle = (index: number, checked: boolean) => {
    const next = new Set(selected)
    if (checked) next.add(index)
    else next.delete(index)
    setSelected(next)
  }

  return (
    <Modal
      title="粘贴业务需求段落, 自动生成功能点"
      open={open} onCancel={onClose} width={880}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        candidates && candidates.length > 0 && (
          <Button key="ok" type="primary"
            onClick={() => onConfirm(candidates.filter((_, i) => selected.has(i)))}>
            确认加入所选 {selected.size} 项
          </Button>
        ),
      ]}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        把业务需求书/会议纪要里的功能描述段落贴到下面, 系统自动提取功能点并建议分类,
        确认后再加入清单 —— 只建议不落库, 加入后仍可修改删除。
      </Typography.Paragraph>
      <Input.TextArea
        rows={6}
        placeholder={'示例: 系统支持个人用户注册登录, 登录需要短信验证码。\n客户可在线提交转账支付申请, 并查询交易订单。\n管理后台提供数据导出与操作日志功能。'}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Space style={{ margin: '10px 0' }}>
        <Button type="primary" loading={loading} onClick={() => void doExtract()}>提取功能点</Button>
        {note && <Typography.Text type="secondary">{note}</Typography.Text>}
      </Space>

      {loading && <Spin style={{ display: 'block', margin: '12px auto' }} />}
      {candidates && candidates.length > 0 && (
        <Table<CandidateFeature>
          rowKey={(_, i) => String(i)}
          dataSource={candidates}
          pagination={false}
          size="small"
          columns={[
            {
              title: '加入', width: 60,
              render: (_v, _r, index) => (
                <Checkbox
                  checked={selected.has(index)}
                  onChange={(e) => toggle(index, e.target.checked)}
                />
              ),
            },
            { title: '功能点', dataIndex: 'name', width: 300 },
            { title: '建议分类', dataIndex: 'categories',
              render: (cats: string[]) => cats.map((c) => <Tag key={c} color="blue">{categoryMap[c] ?? c}</Tag>) },
            { title: '资金', dataIndex: 'involves_payment', width: 60,
              render: (v: boolean) => (v ? <Tag color="red">是</Tag> : '否') },
            { title: '公网', dataIndex: 'exposed_to_internet', width: 60,
              render: (v: boolean) => (v ? <Tag color="orange">是</Tag> : '否') },
            { title: '敏感级别', dataIndex: 'sensitivity', width: 90,
              render: (v: string) => labelMapOf(enums, 'sensitivity_levels')[v] ?? v },
          ]}
        />
      )}
      {candidates && candidates.length === 0 && (
        <Alert type="warning" showIcon message="没有提取到功能点, 请检查文本内容或改用手动录入" />
      )}
    </Modal>
  )
}

function FeatureModal({ value, onOk, onCancel }: {
  value: FeatureRow | null
  onOk: (row: FeatureRow) => void
  onCancel: () => void
}) {
  const enums = useEnums()
  const [form] = Form.useForm<FeatureRow>()
  return (
    <Modal
      title="功能条目"
      open={value !== null}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => { /* 校验失败, 留在弹窗 */ })}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY}>
        <Form.Item name="name" label="功能名称" rules={[{ required: true, message: '请输入功能名称' }]}>
          <Input placeholder="如: 转账汇款" />
        </Form.Item>
        <Form.Item name="module" label="所属模块"><Input placeholder="如: 支付模块" /></Form.Item>
        <Form.Item
          name="categories" label="功能分类(可多选)"
          rules={[{ required: true, message: '至少选择一个分类' }]}
          extra="分类决定触发的安全需求维度"
        >
          <Select
            mode="multiple"
            options={optionsOf(enums, 'feature_categories')}
            placeholder="选择功能分类"
            optionRender={(o) => {
              const hint = typeof o.value === 'string' ? CATEGORY_HINTS[o.value] : undefined
              return (
                <div>
                  <div>{o.label}</div>
                  {hint && <div style={{ fontSize: 12, color: '#999' }}>通常触发: {hint}</div>}
                </div>
              )
            }}
          />
        </Form.Item>
        <Form.Item name="sensitivity" label="敏感级别">
          <Select options={optionsOf(enums, 'sensitivity_levels')} />
        </Form.Item>
        <Space size={32}>
          <Form.Item name="involves_payment" label="是否涉及资金" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="exposed_to_internet" label="是否公网暴露" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  )
}
