/* Step5 组件与许可证(SBOM 来源): 常用组件按层级分组点选添加(自动带默认许可证与风险提示)
   + 手工录入 + 上传 CycloneDX/SPDX 文件批量导入; 生成时自动匹配漏洞与许可证风险。
   本步允许为空(生成时跳过漏洞扫描), 降低不熟悉 SBOM 用户的学习成本。

   v2.2.0: 新增「生态」与「分发渠道」两个维度 —— OS 覆盖的前提。
   同一个 MySQL 8.0.32 在 Debian 是 8.0.32-1~deb12u1、RHEL 是 8.0.32-1.el9、
   Bitnami 是 8.0.32-debian-11-r0, 不知道分发渠道就无法匹配。
   未指定生态的组件走跨生态模糊匹配, 结果标注「待确认」, 绝不静默显示"无漏洞"。 */
import { useRef, useState } from 'react'
import {
  Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag,
  Tooltip, Typography, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { ComponentRow } from '../../types'
import GlossaryTip from '../GlossaryTip'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

interface DraftRow extends Omit<ComponentRow, 'vulnerabilities'> {}

interface KnownComponent { name: string; license: string; ecosystem?: string }

const EMPTY: DraftRow = {
  layer: 'backend', name: '', version: '', purl: null, license: null,
  source_type: 'manual_input', ecosystem: null, distro: null,
}

const RISK_COLOR: Record<string, string> = { high: 'red', medium: 'orange', low: 'green' }

/** 查询语义 → 标签色。not_covered 与 undetermined 用告警色, 避免被误读成"已查过且安全"。 */
const STATUS_COLOR: Record<string, string> = {
  hit: 'red', not_found: 'green', undetermined: 'orange', not_covered: 'gold',
}

export default function Step7Components({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [rows, setRows] = useState<DraftRow[]>(ws.components.map(({ vulnerabilities: _v, ...rest }) => rest))
  const [editing, setEditing] = useState<DraftRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [uploading, setUploading] = useState(false)
  const savedRef = useRef(JSON.stringify(rows))

  const layerMap = labelMapOf(enums, 'sbom_layers')
  const riskMap = labelMapOf(enums, 'license_risk') as unknown as Record<string, { risk: string; label: string; note: string }>
  const commonComponents = (enums['common_components'] ?? {}) as unknown as Record<string, KnownComponent[]>
  const statusMap = labelMapOf(enums, 'vuln_query_status')
  const statusHints = labelMapOf(enums, 'vuln_query_status_hints')

  const riskOf = (license?: string | null) => (license ? riskMap[license] : undefined)

  const addKnown = (layer: string, comp: KnownComponent) => {
    if (rows.some((r) => r.name === comp.name)) {
      message.info(`${comp.name} 已在清单中`)
      return
    }
    setRows([...rows, {
      ...EMPTY,
      layer,
      name: comp.name,
      license: comp.license,
      ecosystem: comp.ecosystem ?? null,
      version: '',
    }])
    message.info(`已添加 ${comp.name}, 请补全版本号`)
  }

  const save = async (): Promise<boolean> => {
    const missingVersion = rows.find((r) => !r.version?.trim())
    if (missingVersion) {
      message.warning(`组件「${missingVersion.name}」缺少版本号(漏洞匹配需要), 请补全或删除`)
      return false
    }
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
    <div style={{ maxWidth: 1120, margin: '0 auto' }}>
      <Alert
        style={{ marginBottom: 12 }}
        type="info"
        showIcon
        message="本步登记系统使用的第三方组件(即 SBOM, 软件物料清单), 自动发现带已知漏洞的旧版本与高风险许可证"
        description={(
          <span>
            从下方常用组件库点选添加(自动带默认许可证与生态), 也可以「新增组件」手工录入或上传
            <GlossaryTip term="sbom">SBOM</GlossaryTip>文件
            (<GlossaryTip term="cyclonedx">CycloneDX / SPDX</GlossaryTip>)批量导入。
            生成阶段将按组件坐标查询<b>本地离线漏洞库</b>, 并按许可证风险库输出合规要求。
            <b>「生态」与「分发渠道」决定能否匹配上</b> —— OS 类组件(MySQL/Nginx/OpenSSL 等)
            的版本号随分发渠道而变, 不填就只能做跨渠道模糊匹配, 结果会标注「待确认」。
            若项目确无第三方组件, 可直接保存进入下一步。
          </span>
        )}
      />

      {/* 常用组件库: 按层级分组点选 */}
      <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: '12px 16px', marginBottom: 16 }}>
        <Typography.Text strong>常用组件库(点选添加, 再补版本号)</Typography.Text>
        {Object.entries(commonComponents).map(([layer, comps]) => (
          <div key={layer} style={{ marginTop: 8 }}>
            <Tag color="blue" style={{ marginRight: 8 }}>{layerMap[layer] ?? layer}</Tag>
            {comps.map((comp: KnownComponent) => {
              const info = riskOf(comp.license)
              const added = rows.some((r) => r.name === comp.name)
              return (
                <Tag.CheckableTag
                  key={comp.name}
                  checked={false}
                  style={{
                    border: '1px solid #d9d9d9', margin: '2px 6px 2px 0',
                    opacity: added ? 0.45 : 1, cursor: added ? 'not-allowed' : 'pointer',
                  }}
                  onChange={() => !added && addKnown(layer, comp)}
                >
                  {comp.name}
                  {info && <span style={{ color: info.risk === 'high' ? '#cf1322' : info.risk === 'medium' ? '#d46b08' : '#52c41a' }}> · {info.label}</span>}
                </Tag.CheckableTag>
              )
            })}
          </div>
        ))}
      </div>

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
          { title: '层级', dataIndex: 'layer', width: 100, render: (v) => <Tag>{layerMap[v] ?? v}</Tag> },
          { title: '组件名', dataIndex: 'name' },
          { title: '版本', dataIndex: 'version', width: 110,
            render: (v) => v || <Typography.Text type="danger">待补全</Typography.Text> },
          { title: '生态', dataIndex: 'ecosystem', width: 150,
            render: (v: string | null) => (v
              ? <Tag color="geekblue">{labelMapOf(enums, 'vuln_ecosystems')[v] ?? v}</Tag>
              : <Typography.Text type="secondary">未指定</Typography.Text>) },
          { title: '分发渠道', dataIndex: 'distro', width: 170,
            render: (v: string | null) => (v
              ? <Tag>{labelMapOf(enums, 'sbom_distros')[v] ?? v}</Tag>
              : <Typography.Text type="secondary">—</Typography.Text>) },
          { title: '许可证', dataIndex: 'license', width: 180,
            render: (v: string | null) => {
              if (!v) return '—'
              const info = riskOf(v)
              return (
                <Space size={4}>
                  <span>{v}</span>
                  {info && (
                    <Tooltip title={info.note}>
                      <Tag color={RISK_COLOR[info.risk]} style={{ marginRight: 0 }}>{info.label}</Tag>
                    </Tooltip>
                  )}
                </Space>
              )
            } },
          { title: '来源', dataIndex: 'source_type', width: 110,
            render: (v) => (v === 'sbom_file' ? <Tag color="purple">SBOM文件</Tag> : <Tag>手工录入</Tag>) },
          { title: '漏洞查询', dataIndex: 'vuln_status', width: 200,
            render: (v: string | null, row: DraftRow) => {
              if (!v) return <Typography.Text type="secondary">未查询</Typography.Text>
              // 命中但带说明(跨渠道模糊匹配 / 麒麟推断 / 修订号不明)时,
              // 必须显式标成"待确认" —— 不能让人当成已确认的漏洞或已确认的安全
              const unconfirmed = v === 'hit' && Boolean(row.vuln_status_note)
              return (
                <Space direction="vertical" size={0}>
                  <Tooltip title={row.vuln_status_note || statusHints[v] || undefined}>
                    <Tag color={unconfirmed ? 'orange' : (STATUS_COLOR[v] ?? 'default')}>
                      {unconfirmed ? '命中 · 待确认' : (statusMap[v] ?? v)}
                    </Tag>
                  </Tooltip>
                  {row.vuln_status_note && (
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {row.vuln_status_note.length > 28
                        ? `${row.vuln_status_note.slice(0, 28)}…`
                        : row.vuln_status_note}
                    </Typography.Text>
                  )}
                </Space>
              )
            } },
          {
            title: '操作', width: 110,
            render: (_v, _r, index) => (
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
  const riskMap = labelMapOf(enums, 'license_risk') as unknown as Record<string, { risk: string; label: string; note: string }>
  const commonComponents = (enums['common_components'] ?? {}) as unknown as Record<string, KnownComponent[]>
  const licenseOptions = Object.values(commonComponents).flat().map((c) => c.license)
  const uniqueLicenses = Array.from(new Set(licenseOptions)).filter(Boolean)
  const [form] = Form.useForm<DraftRow>()
  const license = Form.useWatch('license', form)
  const risk = license ? riskMap[license] : undefined
  const ecosystem = Form.useWatch('ecosystem', form) as string | null | undefined

  return (
    <Modal
      title="软件/框架组件"
      open={value !== null}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => { /* 校验失败, 留在弹窗 */ })}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY}>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="layer" label="层级" rules={[{ required: true }]} style={{ width: 180 }}>
            <Select options={optionsOf(enums, 'sbom_layers')} />
          </Form.Item>
          <Form.Item name="name" label="组件名" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="如 Spring Boot" list="known-components" />
          </Form.Item>
          <datalist id="known-components">
            {Object.entries(commonComponents).flatMap(([, comps]) => comps).map((c) => <option key={c.name} value={c.name} />)}
          </datalist>
        </Space>
        <Form.Item name="version" label="版本号" rules={[{ required: true, message: '版本号用于漏洞匹配, 必填' }]} extra="版本号务必准确, 它决定漏洞匹配结果">
          <Input placeholder="如 2.14.1" />
        </Form.Item>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item
            name="ecosystem" label="生态" style={{ width: 240 }}
            extra="决定在本地漏洞库的哪个生态数据中查找"
          >
            <Select allowClear showSearch placeholder="如 npm / Maven / Bitnami"
                    options={optionsOf(enums, 'vuln_ecosystems')} />
          </Form.Item>
          <Form.Item
            name="distro" label="分发渠道" style={{ flex: 1 }}
            extra="OS 类组件必填: 同一版本在不同渠道的版本串完全不同"
          >
            <Select allowClear showSearch placeholder="如 Bitnami 镜像 / 银河麒麟"
                    options={optionsOf(enums, 'sbom_distros')} />
          </Form.Item>
        </Space>
        {ecosystem === 'other' && (
          <Alert style={{ marginBottom: 12 }} type="warning" showIcon
                 message="该组件未纳入本地漏洞库覆盖范围(如源码编译、K8s), 将标注为「未纳入覆盖范围」, 需人工评估或由 SCA 补充" />
        )}
        <Form.Item
          name="license" label="许可证" extra="常用组件保存后可按名称自动带出默认许可证"
        >
          <Select
            allowClear showSearch
            placeholder="如 Apache-2.0 / MIT / GPL-3.0"
            options={uniqueLicenses.map((l) => ({ value: l, label: l }))}
          />
        </Form.Item>
        {risk && (
          <Alert
            type={risk.risk === 'high' ? 'error' : risk.risk === 'medium' ? 'warning' : 'success'}
            showIcon message={`${risk.label}: ${risk.note}`}
          />
        )}
      </Form>
    </Modal>
  )
}
