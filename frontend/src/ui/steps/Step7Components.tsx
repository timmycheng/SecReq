/* Step7 软件/框架清单(SBOM 来源): 手工录入(常用组件自动补全) +
   上传 CycloneDX/SPDX 文件批量导入; 生成时自动匹配 OSV 漏洞。
   本步允许为空(生成时跳过漏洞扫描), 降低不熟悉 SBOM 用户的学习成本。 */
import { useRef, useState } from 'react'
import {
  Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag,
  Typography, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { ComponentRow } from '../../types'
import GlossaryTip from '../GlossaryTip'
import { useRegisterStepHandle } from './stepContext'
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

export default function Step7Components({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<DraftRow[]>(ws.components.map(({ vulnerabilities: _v, ...rest }) => rest))
  const [editing, setEditing] = useState<DraftRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [uploading, setUploading] = useState(false)
  const savedRef = useRef(JSON.stringify(rows))

  const layerMap = labelMapOf(enums, 'sbom_layers')

  const save = async (): Promise<boolean> => {
    try {
      const saved = await api.saveComponents(ws.project.id, rows)
      patch({ components: saved })
      savedRef.current = JSON.stringify(rows)
      message.success(rows.length ? `已保存 ${saved.length} 个组件` : '组件清单已保存(为空, 生成时跳过漏洞扫描)')
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => JSON.stringify(rows) !== savedRef.current })

  const doImport = async (file: File) => {
    setUploading(true)
    try {
      const result = await api.importSbomFile(ws.project.id, file)
      // 导入后重拉组件(导入为追加语义, 服务端即时生效)
      const fresh = await api.listComponents(ws.project.id)
      const local = fresh.map(({ vulnerabilities: _v, ...rest }) => rest)
      setRows(local)
      patch({ components: fresh })
      savedRef.current = JSON.stringify(local)
      message.success(`SBOM 解析(${result.format}): 解析 ${result.total_parsed} 条, 新增 ${result.added}, 跳过重复 ${result.skipped_duplicate}`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Alert
        style={{ marginBottom: 12 }}
        type="info"
        showIcon
        message="本步登记系统使用的第三方组件(即 SBOM, 软件物料清单), 用于自动发现带已知漏洞的旧版本"
        description={(
          <span>
            有构建工具或安全团队导出的 <GlossaryTip term="sbom">SBOM</GlossaryTip> 文件
            (<GlossaryTip term="cyclonedx">CycloneDX / SPDX</GlossaryTip> 格式) 可直接上传批量导入;
            没有文件就点「新增组件」手工录入, 输入组件名会自动补全常用组件。
            生成阶段将按组件坐标(<GlossaryTip term="purl">purl</GlossaryTip>)自动查询
            <GlossaryTip term="osv">OSV.dev</GlossaryTip>漏洞库。
            若项目确无第三方组件, 可直接保存进入下一步(跳过漏洞扫描)。
          </span>
        )}
      />

      {rows.length === 0 && (
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message="组件清单为空: 生成时将没有 SBOM 与漏洞清单内容, 也无法触发组件整改需求"
        />
      )}

      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<PlusOutlined />} onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY }) }}>新增组件</Button>
        <Upload accept=".json,.spdx" showUploadList={false} beforeUpload={(file) => { void doImport(file); return false }}>
          <Button icon={<UploadOutlined />} loading={uploading}>上传 SBOM 文件批量导入</Button>
        </Upload>
        <Typography.Text type="secondary">共 {rows.length} 条</Typography.Text>
      </Space>

      <Table<DraftRow>
        rowKey={(_, i) => String(i)}
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

      <ComponentModal
        key={`${editIndex}-${editing ? editing.name : ''}`}
        value={editing}
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
}) {
  const enums = useEnums()
  const [form] = Form.useForm<DraftRow>()
  return (
    <Modal
      title="软件/框架组件"
      open={value !== null}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => { /* 校验失败, 留在弹窗 */ })}
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
        <Form.Item name="version" label="版本号" rules={[{ required: true, message: '版本号用于漏洞匹配, 必填' }]} extra="版本号务必准确, 它决定漏洞匹配结果">
          <Input placeholder="如 2.14.1" />
        </Form.Item>
        <Form.Item name="license" label="许可证"><Input placeholder="如 Apache-2.0 / MIT" /></Form.Item>
      </Form>
    </Modal>
  )
}
