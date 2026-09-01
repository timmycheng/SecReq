/* Step4 数据字典与数据资产: 资产 → 数据表 → 字段 三级结构; 支持粘贴/上传字典自动分级。
   资产分类分级决定加密/脱敏/合规需求触发; 字段名参与脱敏规则正则匹配。
   字段编辑为表卡片内的行内编辑区, 避免多层弹窗嵌套。 */
import { useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, Col, Divider, Form, Input, Modal, Popconfirm, Row, Select,
  Space, Spin, Table, Tag, Tooltip, Typography, Upload, message,
} from 'antd'
import {
  DatabaseOutlined, DeleteOutlined, EditOutlined, ImportOutlined, PlusOutlined,
} from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'
import type { DataAssetRow, DataFieldRow, DataTableRow } from '../../types'

const EMPTY_ASSET: DataAssetRow = {
  name: '', data_type: 'business_data', classification: '2级_C1次要信息',
  c3_tag: false,
  is_pii: false, is_sensitive_pii: false, storage_envs: ['db'],
  cross_border_transfer: false, tables: [],
}

export default function Step4DataAssets({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<DataAssetRow[]>(ws.data_assets)
  const [editing, setEditing] = useState<DataAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [importOpen, setImportOpen] = useState(false)
  const savedRef = useRef(JSON.stringify(rows))

  const openAdd = () => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET }) }
  const openEdit = (index: number) => { setEditIndex(index); setEditing(JSON.parse(JSON.stringify(rows[index]))) }

  const save = async (): Promise<boolean> => {
    if (!rows.length) {
      message.warning('请至少录入一个数据资产')
      return false
    }
    try {
      const saved = await api.saveDataAssets(ws.project.id, rows)
      patch({ data_assets: saved })
      savedRef.current = JSON.stringify(rows)
      message.success(`已保存 ${saved.length} 个数据资产`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => JSON.stringify(rows) !== savedRef.current })

  const classificationColors: Record<string, string> = {
    '5级_重要数据': 'red', '4级_C3鉴别信息': 'volcano', '3级_C2主要信息': 'orange',
    '2级_C1次要信息': 'blue', '1级_公开数据': 'green',
  }
  const levelLabels = labelMapOf(enums, 'data_level_labels')
  const assetTypeMap = labelMapOf(enums, 'data_asset_types')
  const storageMap = labelMapOf(enums, 'storage_envs')

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<PlusOutlined />} onClick={openAdd}>新增数据资产</Button>
        <Button type="primary" ghost icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
          粘贴/上传数据字典(自动分级, 推荐)
        </Button>
        <Typography.Text type="secondary">
          本步描述系统处理了哪些数据。共 {rows.length} 个资产 ·
          推荐用「粘贴/上传数据字典」贴入表与字段清单, 自动完成安全分级并建议脱敏字段;
          分级与敏感个人信息标记决定加密/脱敏/合规需求
        </Typography.Text>
      </Space>

      <Table<DataAssetRow>
        rowKey={(_, i) => String(i)}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: '资产名称', dataIndex: 'name' },
          { title: '分类', dataIndex: 'data_type', render: (v: string) => assetTypeMap[v] ?? v },
          {
            title: '分级(JR/T 0197)', dataIndex: 'classification',
            render: (v: string, r) => (
              <Space size={4} wrap>
                <Tag color={classificationColors[v] ?? 'default'}>{levelLabels[v] ?? v}</Tag>
                {r.c3_tag && <Tag color="magenta">C3</Tag>}
              </Space>
            ),
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

      <DictionaryImportModal
        projectId={ws.project.id}
        open={importOpen}
        existingNames={rows.map((r) => r.name)}
        onClose={() => setImportOpen(false)}
        onConfirm={(assets) => {
          const existing = new Set(rows.map((r) => r.name))
          const fresh = assets.filter((a) => !existing.has(a.name))
          setRows([...rows, ...fresh])
          setImportOpen(false)
          const skipped = assets.length - fresh.length
          message.success(
            `已导入 ${fresh.length} 个数据资产${skipped ? `(重名跳过 ${skipped} 个)` : ''}, 请核对分级后点「保存并下一步」落库`)
        }}
      />

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

/** 资产编辑弹窗: 基本属性 + 嵌套的表/字段编辑(字段在表卡片内行内编辑)。 */
function AssetEditor({ initial, onSave, onClose }: {
  initial: DataAssetRow
  onSave: (row: DataAssetRow) => void
  onClose: () => void
}) {
  const enums = useEnums()
  const [form] = Form.useForm()
  const [tables, setTables] = useState<DataTableRow[]>(initial.tables ?? [])
  const [tableModalOpen, setTableModalOpen] = useState(false)
  const levelMeta = (enums['data_level_meta'] ?? {}) as Record<string, { label: string; examples: string }>
  const levelLabels = labelMapOf(enums, 'data_level_labels')
  const selectedLevel = Form.useWatch('classification', form)

  return (
    <Modal
      title={`数据资产: ${initial.name || '(新资产)'}`}
      open
      width={760}
      onCancel={onClose}
      okText="保存资产"
      onOk={async () => {
        const base = await form.validateFields()
        // 表结构允许后补(#89): 只填资产属性即可保存
        // 合并 initial: 保留 uid 等未注册字段, 编辑时原样回传(#66)
        onSave({ ...initial, ...base, tables })
        if (!tables.length) {
          message.info('已保存资产(表结构为空), 可稍后在列表中「编辑」补建表, 或用「粘贴/上传数据字典」自动分级导入')
        }
      }}
    >
      <Form form={form} layout="vertical" initialValues={{ ...initial }}>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="name" label="资产名称" rules={[{ required: true }]}>
              <Input placeholder="如: 银行账户信息" />
            </Form.Item>
          </Col>
          <Col span={7}>
            <Form.Item
              name="data_type" label="数据类别" rules={[{ required: true }]}
              extra="回答「这是什么数据」: 按业务形态选(如客户信息/交易/日志)"
            >
              <Select options={optionsOf(enums, 'data_asset_types')} />
            </Form.Item>
          </Col>
          <Col span={9}>
            <Form.Item
              name="classification"
              label={(
                <Tooltip title="JR/T 0197-2020《金融数据安全 数据安全分级指南》五级体系, 决定加密/脱敏/合规需求的档位">
                  安全分级(?)
                </Tooltip>
              )}
              rules={[{ required: true }]}
              extra={selectedLevel && levelMeta[selectedLevel] ? (
                <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                  典型数据(JR/T 0197 附录A节选): {levelMeta[selectedLevel].examples}
                </Typography.Text>
              ) : undefined}
            >
              <Select
                showSearch
                optionFilterProp="label"
                options={(enums['data_levels'] as string[] ?? []).map((code) => ({
                  value: code,
                  label: levelMeta[code]?.label ?? levelLabels[code] ?? code,
                }))}
              />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={24}>
            <Form.Item noStyle shouldUpdate={(a, b) => a.classification !== b.classification}>
              {({ getFieldValue }) => (
                <Form.Item name="c3_tag" valuePropName="checked" style={{ marginBottom: 8 }}>
                  <Checkbox disabled={!['4级_C3鉴别信息', '5级_重要数据'].includes(getFieldValue('classification'))}>
                    C3 鉴别信息标签(生物特征/口令类, 触发传输/缓存/日志专属规则)
                  </Checkbox>
                </Form.Item>
              )}
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={6}>
            <Form.Item name="is_pii" label="是否个人信息" valuePropName="checked" extra="是否处理可识别自然人的信息">
            <Checkbox>是</Checkbox>
          </Form.Item>
          </Col>
          <Col span={7}>
            <Form.Item name="is_sensitive_pii" label="是否敏感个人信息" valuePropName="checked" extra="勾选会触发个人信息保护事前评估类需求">
            <Checkbox>是</Checkbox>
          </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item name="cross_border_transfer" label="是否跨境传输" valuePropName="checked" extra="勾选会触发数据出境安全评估类需求">
            <Checkbox>是</Checkbox>
          </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="storage_envs" label="存储位置(多选)">
              <Select mode="multiple" options={optionsOf(enums, 'storage_envs')} />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <Divider plain>数据表(在表卡片内直接增删改字段)</Divider>
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
  const setFields = (fields: DataFieldRow[]) => onReplace({ ...table, fields })
  return (
    <div style={{ border: '1px solid #eee', borderRadius: 6, padding: '8px 12px', marginBottom: 10 }}>
      <Space style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <b><DatabaseOutlined style={{ color: '#2f5597' }} /> {table.table_name}</b>
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
        setFields([...table.fields, {
          field_name: '', field_type: 'varchar(64)', need_encrypt: false, need_mask: false, mask_rule: null,
        }])
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
            setFields(fields)
            setEditingFieldIndex(null)
          }}
          onRemove={() => {
            setFields(table.fields.filter((_, i) => i !== editingFieldIndex))
            setEditingFieldIndex(null)
          }}
        />
      )}
    </div>
  )
}

function TableEditor({ onSave, onCancel, enums }: {
  onSave: (row: DataTableRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
}) {
  void enums
  const [name, setName] = useState('')
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

/** 字段行内编辑区(非弹窗): 名称/类型/加密/脱敏 + 脱敏规则建议。 */
function FieldEditor({ initial, onSave, onCancel, onRemove, enums }: {
  initial: DataFieldRow
  onSave: (field: DataFieldRow) => void
  onCancel: () => void
  onRemove: () => void
  enums: ReturnType<typeof useEnums>
}) {
  const [draft, setDraft] = useState<DataFieldRow>(initial)
  const maskRules = labelMapOf(enums, 'mask_rules')
  // 历史数据可能存的是规则文案(中文), 只有能对上 code 时才回显下拉
  const knownRule = draft.mask_rule && draft.mask_rule in maskRules ? draft.mask_rule : undefined

  const commit = () => {
    if (!draft.field_name.trim()) { message.warning('请输入字段名'); return }
    // 存中文规则文案, 文档直接可用; 脱敏规则建议的 code → 文案转换在前端完成
    const ruleText = draft.need_mask
      ? (knownRule ? maskRules[knownRule] : draft.mask_rule || '保留前3后4, 中间****')
      : null
    onSave({ ...draft, mask_rule: ruleText })
  }

  return (
    <div style={{ border: '1px dashed #d9d9d9', borderRadius: 6, padding: '10px 12px', margin: '8px 0', background: '#fafafa' }}>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
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
          {draft.need_mask && (
            <Select
              style={{ width: 320 }}
              placeholder="选择脱敏规则建议"
              value={knownRule}
              onChange={(v) => setDraft({ ...draft, mask_rule: v })}
              options={Object.entries(maskRules).map(([value, label]) => ({ value, label }))}
            />
          )}
        </Space>
        {draft.need_mask && !knownRule && draft.mask_rule && (
          <Typography.Text type="secondary">当前规则: {draft.mask_rule}(自定义文案, 可从下拉重新选择建议规则)</Typography.Text>
        )}
        <Space>
          <Button size="small" type="primary" onClick={commit}>保存字段</Button>
          <Button size="small" onClick={onCancel}>取消</Button>
          <Button size="small" danger onClick={onRemove}>删除字段</Button>
        </Space>
      </Space>
    </div>
  )
}

/** 数据字典导入: 粘贴文本或上传 xlsx/csv → 后端解析+自动分级 → 预览确认(分级可改) → 加入清单。 */
function DictionaryImportModal({ projectId, open, existingNames, onClose, onConfirm }: {
  projectId: number
  open: boolean
  existingNames: string[]
  onClose: () => void
  onConfirm: (assets: DataAssetRow[]) => void
}) {
  const enums = useEnums()
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [assets, setAssets] = useState<DataAssetRow[] | null>(null)
  const [rowCount, setRowCount] = useState(0)
  const [note, setNote] = useState<string | null>(null)
  const levelLabels = labelMapOf(enums, 'data_level_labels')
  const levelOptions = ((enums['data_levels'] as string[]) ?? []).map((code) => ({
    value: code, label: levelLabels[code] ?? code,
  }))

  const applyResult = (result: { row_count: number; assets: DataAssetRow[] }) => {
    setAssets(result.assets)
    setRowCount(result.row_count)
    setNote(`解析 ${result.row_count} 行, 生成 ${result.assets.length} 个资产(每张表一个)。分级为按字段名自动推断, 请逐个核对。`)
  }

  const doParseText = async () => {
    if (!text.trim()) { message.warning('请先粘贴字典内容'); return }
    setLoading(true)
    try {
      applyResult(await api.parseDictionary(projectId, text))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const doUpload = async (file: File) => {
    setLoading(true)
    try {
      applyResult(await api.importDictionaryFile(projectId, file))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
    return false
  }

  const updateLevel = (index: number, level: string) => {
    if (!assets) return
    const copy = [...assets]
    copy[index] = { ...copy[index], classification: level }
    setAssets(copy)
  }

  return (
    <Modal
      title="粘贴/上传数据字典, 自动识别数据分级"
      open={open} onCancel={onClose} width={920}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        assets && assets.length > 0 && (
          <Button key="ok" type="primary"
            onClick={() => onConfirm(assets.filter((a) => !existingNames.includes(a.name)))}>
            确认导入 {assets.filter((a) => !existingNames.includes(a.name)).length} 个资产
          </Button>
        ),
      ]}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        每行一条: <b>表名 + 字段名 + 类型</b>(Tab/逗号/竖线分隔, 支持 Excel 直接复制粘贴),
        或上传 .xlsx/.csv 文件。系统按字段名自动推断分级(JR/T 0197)、PII 标记与脱敏建议。
      </Typography.Paragraph>
      <Input.TextArea
        rows={6}
        placeholder={'示例(Excel 里选中表格区域直接 Ctrl+C 粘贴即可):\ncustomer_info\t客户姓名\tVARCHAR(64)\ncustomer_info\tmobile_phone\tVARCHAR(16)\ncustomer_info\tid_card_no\tVARCHAR(32)\naccount\tbalance\tDECIMAL'}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Space style={{ margin: '10px 0' }} wrap>
        <Button type="primary" loading={loading} onClick={() => void doParseText()}>解析并自动分级</Button>
        <Upload accept=".xlsx,.xlsm,.csv,.tsv,.txt" showUploadList={false} beforeUpload={(f) => void doUpload(f) as unknown as boolean}>
          <Button icon={<ImportOutlined />}>上传文件(.xlsx/.csv)</Button>
        </Upload>
        {note && <Typography.Text type="secondary">{note}</Typography.Text>}
      </Space>

      {loading && <Spin style={{ display: 'block', margin: '12px auto' }} />}
      {assets && assets.length > 0 && (
        <Table<DataAssetRow>
          rowKey={(r) => r.name}
          dataSource={assets}
          pagination={false}
          size="small"
          columns={[
            { title: '表/资产', dataIndex: 'name' },
            { title: '字段数', render: (_v, r) => r.tables.reduce((n, t) => n + t.fields.length, 0), width: 80 },
            { title: '建议分级(可改)', dataIndex: 'classification', width: 220,
              render: (v: string, _r, index) => (
                <Select size="small" style={{ width: 200 }} value={v} options={levelOptions}
                  onChange={(next) => updateLevel(index, next)} />
              ) },
            { title: '个人信息', render: (_v, r) => (r.is_sensitive_pii ? <Tag color="red">敏感PII</Tag>
              : r.is_pii ? <Tag color="gold">PII</Tag> : '—') },
            { title: '建议脱敏字段', render: (_v, r) => {
              const masked = r.tables.flatMap((t) => t.fields.filter((f) => f.need_mask).map((f) => f.field_name))
              return masked.length ? masked.join('、') : '—'
            } },
          ]}
        />
      )}
      {assets && assets.every((a) => existingNames.includes(a.name)) && (
        <Alert style={{ marginTop: 8 }} type="warning" showIcon
          message="解析出的表都已存在, 确认导入后不会新增任何资产" />
      )}
      {rowCount > 0 && assets && assets.length === 0 && (
        <Alert style={{ marginTop: 8 }} type="warning" showIcon message="未能解析出有效数据行" />
      )}
    </Modal>
  )
}
