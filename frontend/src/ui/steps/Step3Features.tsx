/* Step3 功能清单: 动态增删行, 功能分类为受控枚举多选(规则引擎按交集触发)。 */
import { useState } from 'react'
import {
  Button, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { FeatureRow } from '../../types'
import type { StepProps } from '../WizardPage'

const EMPTY: FeatureRow = {
  name: '', module: '', categories: [], sensitivity: 'internal',
  involves_payment: false, exposed_to_internet: false,
}

export default function Step3Features({ ws, patch, advance }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<FeatureRow[]>(ws.features)
  const [editing, setEditing] = useState<FeatureRow | null>(null)
  const [editIndex, setEditIndex] = useState<number>(-1)
  const [saving, setSaving] = useState(false)

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

  const save = async () => {
    if (!rows.length) {
      message.warning('请至少录入一个功能')
      return
    }
    setSaving(true)
    try {
      const saved = await api.saveFeatures(ws.project.id, rows)
      patch({ features: saved })
      message.success(`已保存 ${saved.length} 个功能`)
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<PlusOutlined />} onClick={openAdd}>新增功能</Button>
        <span style={{ color: '#888' }}>共 {rows.length} 条 · 功能分类直接决定规则引擎触发的安全需求</span>
      </Space>

      <Table<FeatureRow>
        rowKey={(r) => r.name}
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

      <Button type="primary" loading={saving} onClick={save} style={{ marginTop: 16 }}>
        保存并下一步
      </Button>

      <FeatureModal
        key={editing ? `edit-${editIndex}` : 'closed'}
        value={editing}
        onCancel={() => setEditing(null)}
        onOk={applyEdit}
        enumsOptions={{
          categories: optionsOf(enums, 'feature_categories'),
          sensitivity: optionsOf(enums, 'sensitivity_levels'),
        }}
      />
    </div>
  )
}

function FeatureModal({ value, onOk, onCancel }: {
  value: FeatureRow | null
  onOk: (row: FeatureRow) => void
  onCancel: () => void
  enumsOptions: { categories: { value: string; label: string }[]; sensitivity: { value: string; label: string }[] }
}) {
  const enums = useEnums()
  const [form] = Form.useForm<FeatureRow>()
  return (
    <Modal
      title="功能条目"
      open={value !== null}
      onCancel={onCancel}
      onOk={async () => onOk(await form.validateFields())}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY}>
        <Form.Item name="name" label="功能名称" rules={[{ required: true, message: '请输入功能名称' }]}>
          <Input placeholder="如: 转账汇款" />
        </Form.Item>
        <Form.Item name="module" label="所属模块"><Input placeholder="如: 支付模块" /></Form.Item>
        <Form.Item
          name="categories" label="功能分类(受控枚举, 可多选)"
          rules={[{ required: true, message: '至少选择一个分类' }]}
        >
          <Select mode="multiple" options={optionsOf(enums, 'feature_categories')} placeholder="决定触发的安全需求维度" />
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
