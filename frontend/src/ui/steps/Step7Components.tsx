/* Step7 软件/框架清单(SBOM 来源): 手工录入(常用组件自动补全) +
   上传 CycloneDX/SPDX 文件批量导入; 生成时自动匹配 OSV 漏洞。 */
import { useState } from 'react'
import {
  Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag,
  Typography, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { ComponentRow } from '../../types'
import type { StepProps } from '../WizardPage'

/** 内置常见组件库(自动补全候选拼 purl 提示), 覆盖 DESIGN.md 要求的常用 50 组件。 */
const KNOWN_COMPONENTS: Record<string, string> = {
  'Spring Boot': 'maven', MySQL: 'generic', Redis: 'generic', Nginx: 'generic',
  Vue: 'npm', React: 'npm', Angular: 'npm', lodash: 'npm', axios: 'npm',
  Element: 'npm', AntDesign: 'npm', log4j: 'maven', 'log4j-core': 'maven',
  fastjson: 'maven', jackson: 'maven', gson: 'maven', tomcat: 'maven',
  netty: 'maven', dubbo: 'maven', mybatis: 'maven', Druid: 'maven',
  kafka: 'generic', RabbitMQ: 'generic', Elasticsearch: 'generic',
  MongoDB: 'generic', PostgreSQL: 'generic', Oracle: 'generic',
  Django: 'pypi', Flask: 'pypi', requests: 'pypi', OpenSSL: 'generic',
  Kubernetes: 'generic', Docker: 'generic', Helm: 'generic',
  Ionic: 'npm', Flutter: 'pub', okhttp: 'maven', Retrofit: 'maven',
  'Spring Security': 'maven', Shiro: 'maven', jwt: 'npm', XStream: 'maven',
  dom4j: 'maven', poi: 'maven', 'itextpdf': 'maven', 'ImageMagick': 'generic',
  FFmpeg: 'generic', zlib: 'generic', libcurl: 'generic', Struts2: 'maven',
}

interface DraftRow extends Omit<ComponentRow, 'vulnerabilities'> {}

const EMPTY: DraftRow = { layer: 'backend', name: '', version: '', purl: null, license: null, source_type: 'manual_input' }

export default function Step7Components({ ws, patch, advance }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<DraftRow[]>(ws.components.map(({ vulnerabilities: _v, ...rest }) => rest))
  const [editing, setEditing] = useState<DraftRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)

  const layerMap = labelMapOf(enums, 'sbom_layers')

  const save = async () => {
    if (!rows.length) { message.warning('请至少录入一个组件'); return }
    setSaving(true)
    try {
      const saved = await api.saveComponents(ws.project.id, rows)
      patch({ components: saved })
      message.success(`已保存 ${saved.length} 个组件`)
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const doImport = async (file: File) => {
    setUploading(true)
    try {
      const result = await api.importSbomFile(ws.project.id, file)
      // 导入后重拉组件(导入为追加语义)
      const fresh = await (await fetch(`/api/projects/${ws.project.id}/components`)).json()
      setRows((fresh as ComponentRow[]).map(({ vulnerabilities: _v, ...rest }) => rest))
      patch({ components: fresh })
      message.success(`SBOM 解析(${result.format}): 解析 ${result.total_parsed} 条, 新增 ${result.added}, 跳过重复 ${result.skipped_duplicate}`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd Upload 默认上传
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<PlusOutlined />} onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY }) }}>新增组件</Button>
        <Upload accept=".json,.spdx" showUploadList={false} beforeUpload={(file) => { void doImport(file); return false }}>
          <Button icon={<UploadOutlined />} loading={uploading}>上传 SBOM 文件(CycloneDX / SPDX)</Button>
        </Upload>
        <Typography.Text type="secondary">共 {rows.length} 条 · 生成阶段将按 purl 自动查询 OSV.dev 漏洞</Typography.Text>
      </Space>

      <Table<DraftRow>
        rowKey={(r) => `${r.name}@${r.version}`}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: '层级', dataIndex: 'layer', width: 110, render: (v) => <Tag>{layerMap[v] ?? v}</Tag> },
          { title: '组件名', dataIndex: 'name' },
          { title: '版本', dataIndex: 'version' },
          { title: '许可证', dataIndex: 'license', render: (v) => v || '—' },
          { title: '来源', dataIndex: 'source_type', width: 120,
            render: (v) => (v === 'sbom_file' ? <Tag color="purple">SBOM文件</Tag> : <Tag>手工录入</Tag>) },
          {
            title: '操作', width: 120,
            render: (_, __, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => { setEditIndex(index); setEditing({ ...rows[index] }) }} />
                <Popconfirm title="删除该组件?" onConfirm={() => setRows(rows.filter((_, i) => i !== index))}>
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

      <ComponentModal
        key={`${editIndex}-${editing ? editing.name : ''}`}
        value={editing}
        enumsOptions={{ layers: optionsOf(enums, 'sbom_layers') }}
        onCancel={() => setEditing(null)}
        onOk={(next) => {
          const copy = [...rows]
          if (editIndex >= 0) copy[editIndex] = next
          else copy.push(next)
          setRows(copy)
          setEditing(null)
        }}
      />
    </div>
  )
}

function ComponentModal({ value, onOk, onCancel }: {
  value: DraftRow | null
  onOk: (row: DraftRow) => void
  onCancel: () => void
  enumsOptions: { layers: { value: string; label: string }[] }
}) {
  const enums = useEnums()
  const [form] = Form.useForm<DraftRow>()
  return (
    <Modal
      title="软件/框架组件"
      open={value !== null}
      onCancel={onCancel}
      onOk={async () => onOk(await form.validateFields())}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY}>
        <Form.Item name="layer" label="层级" rules={[{ required: true }]}>
          <Select options={optionsOf(enums, 'sbom_layers')} />
        </Form.Item>
        <Form.Item name="name" label="组件名" rules={[{ required: true }]}>
          <Input placeholder="输入或从下拉选择常用组件" list="known-components" />
        </Form.Item>
        <datalist id="known-components">
          {Object.keys(KNOWN_COMPONENTS).map((n) => <option key={n} value={n} />)}
        </datalist>
        <Form.Item name="version" label="版本号" rules={[{ required: true, message: '版本号用于漏洞匹配, 必填' }]}>
          <Input placeholder="如 2.14.1(务必准确)" />
        </Form.Item>
        <Form.Item name="license" label="许可证"><Input placeholder="如 Apache-2.0 / MIT" /></Form.Item>
      </Form>
    </Modal>
  )
}
