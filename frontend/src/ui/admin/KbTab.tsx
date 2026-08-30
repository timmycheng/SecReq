/* 知识库管理: 模板启停与编辑(写回 YAML 自动备份, 保存时全量校验)。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Col, Form, Input, Modal, Row, Select, Space, Switch, Table, Tag,
  Typography, message,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { api, type KbTemplateRow } from '../../api'
import { labelMapOf, useEnums } from '../../enums'
import { PRIORITY_COLOR } from './shared'

export default function KbTab() {
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
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        停用后生成时跳过; 编辑写回 YAML 自动备份, 保存时全量校验。当前共 {rows.length} 条模板。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="按 id 或标题搜索" allowClear style={{ width: 280 }}
          onSearch={setKeyword}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
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
