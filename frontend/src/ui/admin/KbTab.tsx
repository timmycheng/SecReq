/* 知识库管理: 模板新增/启停/编辑(写回 YAML 自动备份, 保存时全量校验)。
   编辑弹窗含监管出处增删排序(#80); 下拉一律用 meta 下发的中文映射(#82)。
   新增支持「复制为新模板」: 带入相近模板文案并自动建议下一个可用 id(#165)。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Col, Collapse, Form, Input, Modal, Popconfirm, Row, Select, Space, Switch, Table, Tag,
  Tooltip, Typography, message,
} from 'antd'
import {
  ArrowDownOutlined, ArrowUpOutlined, CopyOutlined, DeleteOutlined, PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'

import { api, type KbTemplateRow } from '../../api'
import { labelMapOf, useEnums } from '../../enums'
import TriggerEditor, { type Trigger } from './TriggerEditor'
import { PRIORITY_COLOR } from '../tokens'

const ID_PATTERN = /^SEC-[A-Z0-9]+-\d{3}$/

/** 建议下一个可用 id: SEC-DATA-007 → 同前缀最大序号 +1(新增 #165)。 */
function suggestNextId(ids: string[], sourceId: string): string {
  const match = sourceId.match(/^(.*-)(\d+)$/)
  const prefix = match ? match[1] : `${sourceId}-`
  const used = ids
    .filter((id) => id.startsWith(prefix))
    .map((id) => parseInt(id.slice(prefix.length), 10) || 0)
  return `${prefix}${String((used.length ? Math.max(...used) : 0) + 1).padStart(3, '0')}`
}

function emptyTemplate(): KbTemplateRow {
  return {
    id: '', title: '', trigger_type: 'feature_category', priority: 'high',
    suggested_phase: 'design', enabled: true,
    trigger: { type: 'feature_category', condition: {} },
    description: '', acceptance_criteria: '', trigger_reason: '', regulatory_ref: [],
  }
}

export default function KbTab() {
  const enums = useEnums()
  const [rows, setRows] = useState<KbTemplateRow[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<{ row: KbTemplateRow; mode: 'edit' | 'create' } | null>(null)
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

  const copyAsNew = (row: KbTemplateRow) => {
    setEditing({
      mode: 'create',
      row: { ...row, id: suggestNextId(rows.map((r) => r.id), row.id), enabled: true },
    })
  }

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        停用后生成时跳过; 新增/编辑写回 YAML 自动备份并校验(条件键写错会被拦截),
        保存后下一轮生成即生效。当前共 {rows.length} 条模板。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="按 id 或标题搜索" allowClear style={{ width: 280 }}
          onSearch={setKeyword}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ mode: 'create', row: emptyTemplate() })}>
          新增模板
        </Button>
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
            title: '操作', width: 170,
            render: (_v, r) => (
              <Space>
                <Button size="small" onClick={() => setEditing({ mode: 'edit', row: r })}>编辑</Button>
                <Tooltip title="带入该模板文案与触发条件, id 自动顺延, 适合新增相近规则">
                  <Button size="small" icon={<CopyOutlined />} onClick={() => copyAsNew(r)}>复制为新模板</Button>
                </Tooltip>
              </Space>
            ),
          },
        ]}
      />
      {editing && (
        <KbEditModal
          row={editing.row}
          mode={editing.mode}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </>
  )
}

function KbEditModal({ row, mode, onClose, onSaved }: {
  row: KbTemplateRow
  mode: 'edit' | 'create'
  onClose: () => void
  onSaved: () => void
}) {
  const enums = useEnums()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  // 表单编辑器与 JSON 高级模式共用同一份 trigger 文本(#81)
  const triggerWatch = Form.useWatch('trigger', form)
  const triggerObj = useMemo(() => {
    if (typeof triggerWatch !== 'string') return null
    try {
      const parsed = JSON.parse(triggerWatch)
      return parsed && typeof parsed === 'object' ? (parsed as Trigger) : null
    } catch {
      return null
    }
  }, [triggerWatch])
  // 中文标签来自 meta 统一下发(#82), 保存值仍为英文枚举
  const priorityOptions = Object.entries(labelMapOf(enums, 'priority_labels'))
    .map(([value, label]) => ({ value, label }))
  const phaseOptions = Object.entries(labelMapOf(enums, 'requirement_phases'))
    .map(([value, label]) => ({ value, label }))
  const requiredIfCreate = mode === 'create'
    ? [{ required: true, message: '新增模板必填' }] : []
  return (
    <Modal
      title={mode === 'create' ? '新增知识库模板' : `编辑知识库模板 ${row.id}`} open
      onCancel={onClose} width={760}
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
        if (!values.regulatory_ref?.length) {
          message.error('监管出处至少保留一条(每条必须含文件名)')
          return
        }
        setSaving(true)
        try {
          if (mode === 'create') {
            await api.createKbTemplate({ ...values, trigger, enabled: true })
          } else {
            await api.updateKbTemplate(row.id, { ...values, trigger })
          }
          message.success(mode === 'create' ? '模板已新增, 下一轮生成即生效' : '已保存')
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
        {mode === 'create' && (
          <Form.Item
            name="id" label="模板编号"
            rules={[
              { required: true, message: '请输入模板编号' },
              { pattern: ID_PATTERN, message: '格式: SEC-前缀-三位序号, 如 SEC-DATA-008' },
            ]}
            extra="复制为新模板时已自动建议下一个可用编号"
          >
            <Input placeholder="如 SEC-DATA-008" />
          </Form.Item>
        )}
        <Form.Item name="title" label="标题" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="description" label="需求描述(生成后的需求正文, 支持 {{占位符}})"
          rules={requiredIfCreate}
        >
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="acceptance_criteria" label="验收标准" rules={requiredIfCreate}>
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="trigger_reason" label="触发原因(展示给填报人)" rules={requiredIfCreate}>
          <Input.TextArea rows={2} />
        </Form.Item>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="priority" label="优先级" rules={requiredIfCreate}>
              <Select options={priorityOptions} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="suggested_phase" label="建议阶段" rules={requiredIfCreate}>
              <Select options={phaseOptions} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="asvs_ref" label="ASVS 条款">
              <Input placeholder="如 V1.1.2" />
            </Form.Item>
          </Col>
        </Row>
        {/* 触发条件: 表单与 JSON 双向同步, JSON 为存储真值(#81) */}
        {triggerObj !== null && (
          <Form.Item label="触发条件(表单)">
            <TriggerEditor
              value={triggerObj}
              enums={enums}
              onChange={(next) => form.setFieldValue('trigger', JSON.stringify(next, null, 2))}
            />
          </Form.Item>
        )}
        <Collapse
          style={{ marginBottom: 16 }}
          items={[{
            key: 'advanced',
            // forceRender: 让 trigger 字段在面板未展开时也注册进表单, 否则 useWatch 与保存都拿不到值
            forceRender: true,
            label: '高级模式: 直接编辑 JSON',
            extra: <Typography.Text type="secondary" style={{ fontSize: 12 }}>表单未覆盖的形态走这里</Typography.Text>,
            children: (
              <Form.Item
                name="trigger"
                noStyle
                rules={[{
                  validator: (_r, v) => {
                    if (typeof v === 'string') {
                      try { JSON.parse(v) } catch { return Promise.reject(new Error('不是合法 JSON')) }
                    }
                    return Promise.resolve()
                  },
                  message: '不是合法 JSON',
                }]}
              >
                <Input.TextArea rows={6} style={{ fontFamily: 'monospace', fontSize: 12 }} />
              </Form.Item>
            ),
          }]}
        />
        <Form.Item
          label="监管出处(合规依据)" required style={{ marginBottom: 8 }}
          extra="条款号不确定时写「参考《文件名》」并在备注标注「待合规部门确认」, 严禁编造条款号"
        />
        <Form.List name="regulatory_ref">
          {(fields, { add, remove, move }) => (
            <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 16 }}>
              {fields.map((field, index) => (
                <Space
                  key={field.key}
                  direction="vertical" size={4}
                  style={{
                    width: '100%', border: '1px solid #f0f0f0', borderRadius: 6,
                    padding: '8px 12px',
                  }}
                >
                  <Space size={8} wrap style={{ width: '100%' }}>
                    <Form.Item name={[field.name, 'file']} noStyle
                      rules={[{ required: true, message: '文件名必填' }]}>
                      <Input placeholder="文件名(如 JR/T 0197-2020)" style={{ width: 230 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'clause']} noStyle>
                      <Input placeholder="条款号(如 7.1.3, 可空)" style={{ width: 170 }} />
                    </Form.Item>
                    <Space.Compact>
                      <Button size="small" icon={<ArrowUpOutlined />} disabled={index === 0}
                        onClick={() => move(index, index - 1)} />
                      <Button size="small" icon={<ArrowDownOutlined />} disabled={index === fields.length - 1}
                        onClick={() => move(index, index + 1)} />
                      <Popconfirm title="删除该出处?" onConfirm={() => remove(index)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space.Compact>
                  </Space>
                  <Form.Item name={[field.name, 'summary']} noStyle>
                    <Input placeholder="摘要(该条款与本需求的关联)" />
                  </Form.Item>
                  <Form.Item name={[field.name, 'note']} noStyle>
                    <Input placeholder="备注(如: 待合规部门确认)" />
                  </Form.Item>
                </Space>
              ))}
              <Button size="small" icon={<PlusOutlined />}
                onClick={() => add({ file: '', clause: '', summary: '', note: '' })}>
                新增出处
              </Button>
            </Space>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}
