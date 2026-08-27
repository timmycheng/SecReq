/* Step4 数据字典与数据资产: 资产 → 数据表 → 字段 三级结构。
   资产分类分级决定加密/脱敏/合规需求触发; 字段名参与脱敏规则正则匹配。 */
import { useState } from 'react'
import {
  Button, Checkbox, Divider, Form, Input, Modal, Popconfirm, Select, Space,
  Table, Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { DataAssetRow, DataTableRow } from '../../types'
import type { StepProps } from '../WizardPage'

const EMPTY_ASSET: DataAssetRow = {
  name: '', data_type: 'business_data', classification: '内部',
  is_pii: false, is_sensitive_pii: false, storage_envs: ['db'],
  cross_border_transfer: false, tables: [],
}

export default function Step4DataAssets({ ws, patch, advance }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<DataAssetRow[]>(ws.data_assets)
  const [editing, setEditing] = useState<DataAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [saving, setSaving] = useState(false)

  const openAdd = () => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET }) }
  const openEdit = (index: number) => { setEditIndex(index); setEditing(JSON.parse(JSON.stringify(rows[index]))) }

  const save = async () => {
    if (!rows.length) {
      message.warning('请至少录入一个数据资产')
      return
    }
    setSaving(true)
    try {
      const saved = await api.saveDataAssets(ws.project.id, rows)
      patch({ data_assets: saved })
      message.success(`已保存 ${saved.length} 个数据资产`)
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const classificationColors: Record<string, string> = {
    公开: 'green', 内部: 'blue', 敏感: 'orange', 机密: 'red',
  }
  const assetTypeMap = labelMapOf(enums, 'data_asset_types')
  const storageMap = labelMapOf(enums, 'storage_envs')

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<PlusOutlined />} onClick={openAdd}>新增数据资产</Button>
        <Typography.Text type="secondary">
          共 {rows.length} 个资产 · 先建资产(分类/分级), 再在其下维护表与字段
        </Typography.Text>
      </Space>

      <Table<DataAssetRow>
        rowKey={(r) => r.name}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: '资产名称', dataIndex: 'name' },
          { title: '分类', dataIndex: 'data_type', render: (v: string) => assetTypeMap[v] ?? v },
          {
            title: '分级', dataIndex: 'classification',
            render: (v: string) => <Tag color={classificationColors[v] ?? 'default'}>{v}</Tag>,
          },
          {
            title: '个人信息', dataIndex: 'is_sensitive_pii',
            render: (_v, r) => (r.is_sensitive_pii ? <Tag color="red">敏感PII</Tag>
              : r.is_pii ? <Tag color="gold">PII</Tag> : '—'),
          },
          {
            title: '存储位置', dataIndex: 'storage_envs',
            render: (envs: string[]) => envs.map((e) => <Tag key={e}>{storageMap[e] ?? e}</Tag>),
          },
          { title: '跨境传输', dataIndex: 'cross_border_transfer', width: 90,
            render: (v: boolean) => (v ? <Tag color="volcano">是</Tag> : '否') },
          { title: '表/字段数', render: (_v, r) =>
            `${r.tables.length} / ${r.tables.reduce((n, t) => n + t.fields.length, 0)}`, width: 90 },
          {
            title: '操作', width: 120,
            render: (_, __, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(index)} />
                <Popconfirm title="删除该资产及其下全部表/字段?" onConfirm={() => setRows(rows.filter((_, i) => i !== index))}>
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

      {editing !== null && (
        <AssetEditor
          initial={editing}
          onClose={() => setEditing(null)}
          onSave={(next) => {
            const copy = [...rows]
            if (editIndex >= 0) copy[editIndex] = next
            else copy.push(next)
            setRows(copy)
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

/** 资产编辑弹窗: 基本属性 + 嵌套的表/字段三级编辑。 */
function AssetEditor({ initial, onSave, onClose }: {
  initial: DataAssetRow
  onSave: (row: DataAssetRow) => void
  onClose: () => void
}) {
  const enums = useEnums()
  const [form] = Form.useForm()
  const [tables, setTables] = useState<DataTableRow[]>(initial.tables ?? [])
  const [tableModalOpen, setTableModalOpen] = useState(false)

  return (
    <Modal
      title={`数据资产: ${initial.name || '(新资产)'}`}
      open
      width={760}
      onCancel={onClose}
      okText="保存资产"
      onOk={async () => {
        const base = await form.validateFields()
        if (!tables.length) {
          message.warning('请至少为资产录入一张数据表(可不含字段)')
          return
        }
        onSave({ ...base, tables })
      }}
    >
      <Form form={form} layout="vertical" initialValues={{ ...initial }}>
        <Space size={16} style={{ display: 'flex' }}>
          <Form.Item name="name" label="资产名称" rules={[{ required: true }]} style={{ width: 240 }}>
            <Input placeholder="如: 银行账户信息" />
          </Form.Item>
          <Form.Item name="data_type" label="资产分类" rules={[{ required: true }]} style={{ width: 200 }}>
            <Select options={optionsOf(enums, 'data_asset_types')} />
          </Form.Item>
          <Form.Item name="classification" label="分级" rules={[{ required: true }]} style={{ width: 140 }}>
            <Select options={(enums['data_classifications'] as string[] ?? []).map((c) => ({ value: c, label: c }))} />
          </Form.Item>
        </Space>
        <Space size={24} wrap>
          <Form.Item name="is_pii" label="是否个人信息" valuePropName="checked"><Checkbox /></Form.Item>
          <Form.Item name="is_sensitive_pii" label="是否敏感个人信息" valuePropName="checked"><Checkbox /></Form.Item>
          <Form.Item name="cross_border_transfer" label="是否跨境传输" valuePropName="checked"><Checkbox /></Form.Item>
          <Form.Item name="storage_envs" label="存储位置(多选)">
            <Select mode="multiple" style={{ minWidth: 280 }} options={optionsOf(enums, 'storage_envs')} />
          </Form.Item>
        </Space>
      </Form>

      <Divider plain>数据表(二级)</Divider>
      <Button size="small" icon={<PlusOutlined />} onClick={() => setTableModalOpen(true)} style={{ marginBottom: 8 }}>
        新增数据表
      </Button>
      {tables.map((t, ti) => (
        <CardLikeTable key={`${t.table_name}-${ti}`} table={t} enums={enums}
          onDelete={() => setTables(tables.filter((_, i) => i !== ti))}
          onReplace={(next) => {
            const copy = [...tables]; copy[ti] = next; setTables(copy)
          }}
        />
      ))}

      {tableModalOpen && (
        <TableEditor
          initial={null}
          enums={enums}
          onCancel={() => setTableModalOpen(false)}
          onSave={(next) => { setTables([...tables, next]); setTableModalOpen(false) }}
        />
      )}
    </Modal>
  )
}

function CardLikeTable({ table, onDelete, onReplace, enums }: {
  table: DataTableRow
  onDelete: () => void
  onReplace: (next: DataTableRow) => void
  enums: ReturnType<typeof useEnums>
}) {
  const [editingFieldIndex, setEditingFieldIndex] = useState<number | null>(null)
  return (
    <div style={{ border: '1px solid #eee', borderRadius: 6, padding: '8px 12px', marginBottom: 10 }}>
      <Space style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <b><DatabaseGlyph /> {table.table_name}</b>
        <Popconfirm title="删除整张表?" onConfirm={onDelete}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      </Space>
      {table.fields.map((f, fi) => (
        <Space key={`${f.field_name}-${fi}`} size={8} style={{ display: 'flex', marginBottom: 2 }} wrap>
          <code>{f.field_name}</code>
          <Typography.Text type="secondary">{f.field_type}</Typography.Text>
          {f.need_encrypt && <Tag color="purple">加密</Tag>}
          {f.need_mask && <Tag color="cyan">脱敏: {f.mask_rule || '建议规则'}</Tag>}
          <Button size="small" type="text" icon={<EditOutlined />}
            onClick={() => setEditingFieldIndex(fi)} />
        </Space>
      ))}
      <Button size="small" icon={<PlusOutlined />} onClick={() => {
        onReplace({ ...table, fields: [...table.fields, {
          field_name: '', field_type: 'varchar(64)', need_encrypt: false, need_mask: false, mask_rule: null,
        }] })
        setEditingFieldIndex(table.fields.length)
      }}>添加字段</Button>
      {editingFieldIndex !== null && table.fields[editingFieldIndex] && (
        <FieldEditor
          initial={table.fields[editingFieldIndex]}
          enums={enums}
          onCancel={() => setEditingFieldIndex(null)}
          onSave={(next) => {
            const fields = [...table.fields]
            fields[editingFieldIndex] = next
            onReplace({ ...table, fields })
            setEditingFieldIndex(null)
          }}
          onRemove={() => {
            onReplace({ ...table, fields: table.fields.filter((_, i) => i !== editingFieldIndex) })
            setEditingFieldIndex(null)
          }}
        />
      )}
    </div>
  )
}

function DatabaseGlyph() { return <span>🗄</span> }

function TableEditor({ initial, onSave, onCancel, enums }: {
  initial: DataTableRow | null
  onSave: (row: DataTableRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
}) {
  void enums
  const [name, setName] = useState(initial?.table_name ?? '')
  return (
    <Modal
      title="新增数据表" open onCancel={onCancel}
      okText="创建" onOk={() => {
        if (!name.trim()) { message.warning('请输入物理表名'); return }
        onSave({ table_name: name.trim(), fields: [] })
      }}
    >
      <Input placeholder="物理表名, 如 t_bank_account" value={name} onChange={(e) => setName(e.target.value)} />
    </Modal>
  )
}

function FieldEditor({ initial, onSave, onCancel, onRemove, enums }: {
  initial: DataTableRow['fields'][number]
  onSave: (field: DataTableRow['fields'][number]) => void
  onCancel: () => void
  onRemove: () => void
  enums: ReturnType<typeof useEnums>
}) {
  const [draft, setDraft] = useState(initial)
  const maskRules = labelMapOf(enums, 'mask_rules')
  return (
    <Modal
      title={`字段: ${initial.field_name || '(新字段)'}`} open onCancel={onCancel}
      okText="保存字段"
      onOk={() => {
        if (!draft.field_name.trim()) { message.warning('请输入字段名'); return }
        // 存中文规则文案, 文档直接可用; 脱敏规则建议的 code → 文案转换在前端完成
        const ruleText = draft.need_mask
          ? ((draft.mask_rule && draft.mask_rule in maskRules) ? maskRules[draft.mask_rule] : draft.mask_rule || '保留前3后4, 中间****')
          : null
        onSave({ ...draft, mask_rule: ruleText })
      }}
      footer={[
        <Button key="del" danger onClick={onRemove}>删除字段</Button>,
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        <Button key="ok" type="primary" onClick={() => {
          if (!draft.field_name.trim()) { message.warning('请输入字段名'); return }
          const ruleText = draft.need_mask
            ? ((draft.mask_rule && draft.mask_rule in maskRules) ? maskRules[draft.mask_rule] : draft.mask_rule || '保留前3后4, 中间****')
            : null
          onSave({ ...draft, mask_rule: ruleText })
        }}>保存字段</Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Input
            style={{ width: 220 }} placeholder="字段名, 如 card_number"
            value={draft.field_name}
            onChange={(e) => setDraft({ ...draft, field_name: e.target.value })}
          />
          <Input
            style={{ width: 160 }} placeholder="类型, 如 varchar(32)"
            value={draft.field_type}
            onChange={(e) => setDraft({ ...draft, field_type: e.target.value })}
          />
        </Space>
        <Space size={24}>
          <Checkbox checked={draft.need_encrypt}
            onChange={(e) => setDraft({ ...draft, need_encrypt: e.target.checked })}>加密存储</Checkbox>
          <Checkbox checked={draft.need_mask}
            onChange={(e) => setDraft({ ...draft, need_mask: e.target.checked })}>脱敏展示</Checkbox>
        </Space>
        {draft.need_mask && (
          <Select
            style={{ width: 320 }}
            placeholder="选择脱敏规则建议"
            value={undefined}
            onChange={(v) => setDraft({ ...draft, mask_rule: v })}
            options={Object.entries(maskRules).map(([value, label]) => ({ value, label }))}
          />
        )}
      </Space>
    </Modal>
  )
}
