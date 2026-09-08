/* 组件清单卡(SBOM, 系统级): 自 SystemInventoryCards 拆出(#289, SBOM 与基础设施分立)。
   数据源 /api/systems/{id}/components, 多轮评估共享; #259 起可被评估向导
   「组件与许可证」步骤内嵌: 可选 onHandle 把 save/isDirty 注册给向导步骤句柄。 */
import { useEffect, useState } from 'react'
import {
  Alert, AutoComplete, Button, Card, Collapse, Form, Input, Modal, Popconfirm, Select,
  Space, Table, Tag, Tooltip, Typography, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { ComponentRow } from '../../types'
import { RISK_TEXT_COLOR } from '../tokens'
import type { InventoryCardHandle } from './inventoryCommon'

interface DraftRow extends Omit<ComponentRow, 'vulnerabilities'> {}

interface KnownComponent { name: string; license: string; ecosystem?: string }

/** 新增组件的默认层级; 若后端枚举 code 变更导致失配, 回退枚举第一个可用值(#42)。 */
const PREFERRED_LAYER = 'backend'

const RISK_COLOR: Record<string, string> = { high: 'red', medium: 'orange', low: 'green' }

/** 查询语义 → 标签色。not_covered 与 undetermined 用告警色, 避免被误读成"已查过且安全"。 */
const STATUS_COLOR: Record<string, string> = {
  hit: 'red', not_found: 'green', undetermined: 'orange', not_covered: 'gold',
}

export function SystemComponentsCard({ systemId, onHandle, onSaved }: {
  systemId: number
  onHandle?: (h: InventoryCardHandle | null) => void
  /** 保存成功后回吐最新清单(#259): 向导步骤据此同步 WizardState, 确认页条数不陈旧 */
  onSaved?: (rows: ComponentRow[]) => void
}) {
  const enums = useEnums()
  const [rows, setRows] = useState<DraftRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [editing, setEditing] = useState<DraftRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [modalSeq, setModalSeq] = useState(0)

  const openModal = (row: DraftRow | null, index: number) => {
    setModalSeq((s) => s + 1)
    setEditIndex(index)
    setEditing(row)
  }

  useEffect(() => {
    setLoaded(false)
    api.getSystemComponents(systemId)
      .then((fresh) => {
        setRows(fresh.map(({ vulnerabilities: _v, ...rest }) => rest))
        setDirty(false)
      })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoaded(true))
  }, [systemId])

  const layerMap = labelMapOf(enums, 'sbom_layers')
  const riskMap = labelMapOf(enums, 'license_risk') as unknown as Record<string, { risk: string; label: string; note: string }>
  const statusMap = labelMapOf(enums, 'vuln_query_status')
  const statusHints = labelMapOf(enums, 'vuln_query_status_hints')

  const riskOf = (license?: string | null) => (license ? riskMap[license] : undefined)

  const emptyRow = (): DraftRow => ({
    layer: layerMap[PREFERRED_LAYER] ? PREFERRED_LAYER : (Object.keys(layerMap)[0] ?? ''),
    name: '', version: '', purl: null, license: null,
    source_type: 'manual_input', ecosystem: null, distro: null,
  })

  const save = async (silent = false): Promise<boolean> => {
    if (!dirty) return true
    const missingVersion = rows.find((r) => !r.version?.trim())
    if (missingVersion) {
      message.warning(`组件「${missingVersion.name}」缺少版本号(漏洞匹配需要), 请补全或删除`)
      return false
    }
    setSaving(true)
    try {
      const fresh = await api.saveSystemComponents(systemId, rows)
      setDirty(false)
      onSaved?.(fresh)
      if (!silent) {
        message.success(rows.length ? `已保存 ${rows.length} 个组件` : '组件清单已保存(为空, 生成时跳过漏洞扫描)')
      }
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    } finally {
      setSaving(false)
    }
  }

  // 每次渲染后重新注册句柄(闭包始终指向最新状态), 卸载时注销 —— 与 useRegisterStepHandle 同套路
  useEffect(() => {
    onHandle?.({ save, isDirty: () => dirty })
    return () => onHandle?.(null)
  })

  const doImport = async (file: File) => {
    setUploading(true)
    try {
      const result = await api.importSystemSbom(systemId, file)
      // 导入为追加语义, 服务端即时生效 → 重拉覆盖本地
      const fresh = await api.getSystemComponents(systemId)
      setRows(fresh.map(({ vulnerabilities: _v, ...rest }) => rest))
      setDirty(false)
      message.success(`SBOM 解析(${result.format}): 解析 ${result.total_parsed} 条, 新增 ${result.added}, 跳过重复 ${result.skipped_duplicate}`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card
      size="small" variant="borderless" title="组件清单(SBOM, 系统级)"
      extra={(
        <Space>
          {dirty && <Typography.Text type="warning" style={{ fontSize: 12 }}>有未保存修改</Typography.Text>}
          <Button size="small" type="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
            保存清单
          </Button>
        </Space>
      )}
    >
      <Alert
        style={{ marginBottom: 12 }}
        type="info"
        showIcon
        message="登记系统使用的第三方组件(即 SBOM, 软件物料清单), 生成时自动发现带已知漏洞的旧版本与高风险许可证"
        description={(
          <span>
            从组件弹窗的常用组件库点选添加(自动带默认许可证与生态), 也可以「新增组件」手工录入或上传
            SBOM 文件(CycloneDX / SPDX)批量导入。
            <b>「生态」与「分发渠道」决定能否匹配上</b> —— OS 类组件(MySQL/Nginx/OpenSSL 等)
            的版本号随分发渠道而变, 不填就只能做跨渠道模糊匹配, 结果会标注「待确认」。
          </span>
        )}
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<PlusOutlined />} onClick={() => openModal(emptyRow(), -1)}>新增组件</Button>
        <Upload accept=".json,.spdx" showUploadList={false} beforeUpload={(file) => { void doImport(file); return false }}>
          <Button icon={<UploadOutlined />} loading={uploading}>上传 SBOM 文件批量导入</Button>
        </Upload>
        <Typography.Text type="secondary">共 {rows.length} 条</Typography.Text>
      </Space>

      <Table<DraftRow>
        /* 已保存行按稳定 uid 取键, 删除行不再导致其余行身份漂移; 新增行(未落库)回退序号 */
        rowKey={(r, i) => r.uid || `new-${i ?? 0}`}
        dataSource={rows}
        pagination={false}
        size="small"
        loading={!loaded}
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
                <Button size="small" icon={<EditOutlined />} onClick={() => openModal({ ...rows[index] }, index)} />
                <Popconfirm title="删除该组件?" onConfirm={() => { setRows(rows.filter((_, i) => i !== index)); setDirty(true) }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <ComponentModal
        key={`component-modal-${modalSeq}`}
        value={editing}
        onCancel={() => setEditing(null)}
        onOk={(next) => {
          const copy = [...rows]
          if (editIndex >= 0) copy[editIndex] = next
          else copy.push(next)
          setRows(copy)
          setDirty(true)
          setEditing(null)
        }}
      />
    </Card>
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
  const riskOf = (license?: string | null) => (license ? riskMap[license] : undefined)
  const licenseOptions = Object.values(commonComponents).flat().map((c) => c.license)
  const uniqueLicenses = Array.from(new Set(licenseOptions)).filter(Boolean)
  // 名称 → 常用组件(带层级), 供 AutoComplete 过滤与自动回填(#91)
  const knownByName = new Map<string, KnownComponent & { layer: string }>()
  for (const [layer, comps] of Object.entries(commonComponents)) {
    for (const c of comps) {
      if (!knownByName.has(c.name)) knownByName.set(c.name, { ...c, layer })
    }
  }
  const nameOptions = [...knownByName.values()].map((c) => ({
    value: c.name,
    label: `${c.name}(${labelMapOf(enums, 'sbom_layers')[c.layer] ?? c.layer})`,
  }))
  const [form] = Form.useForm<DraftRow>()
  const license = Form.useWatch('license', form)
  const risk = license ? riskMap[license] : undefined
  const ecosystem = Form.useWatch('ecosystem', form) as string | null | undefined

  return (
    <Modal
      title="软件/框架组件"
      open={value !== null}
      onCancel={onCancel}
      onOk={() => form.validateFields()
        .then((v) => onOk({ ...(value ?? {}), ...v }))
        .catch(() => { /* 校验失败, 留在弹窗 */ })}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? undefined}>
        <Collapse
          size="small" style={{ marginBottom: 12 }}
          items={[{
            key: 'common',
            label: '常用组件库(点选自动带出许可证与生态)',
            children: (
              <div>
                {Object.entries(commonComponents).map(([layer, comps]) => (
                  <div key={layer} style={{ marginBottom: 4 }}>
                    <Tag color="blue" style={{ marginRight: 8 }}>{labelMapOf(enums, 'sbom_layers')[layer] ?? layer}</Tag>
                    {comps.map((comp: KnownComponent) => {
                      const info = riskOf(comp.license)
                      return (
                        <Tag.CheckableTag
                          key={comp.name}
                          checked={false}
                          style={{ border: '1px solid #d9d9d9', margin: '2px 6px 2px 0' }}
                          onChange={() => {
                            form.setFieldsValue({
                              layer,
                              name: comp.name,
                              license: comp.license,
                              ecosystem: comp.ecosystem ?? null,
                            })
                            message.info(`已带入 ${comp.name}, 请补全版本号`)
                          }}
                        >
                          {comp.name}
                          {info && <span style={{ color: RISK_TEXT_COLOR[info.risk] }}> · {info.label}</span>}
                        </Tag.CheckableTag>
                      )
                    })}
                  </div>
                ))}
              </div>
            ),
          }]}
        />
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="layer" label="层级" rules={[{ required: true }]} style={{ width: 180 }}>
            <Select options={optionsOf(enums, 'sbom_layers')} />
          </Form.Item>
          <Form.Item name="name" label="组件名" rules={[{ required: true }]} style={{ flex: 1 }}>
            <AutoComplete
              placeholder="输入过滤常用组件, 或手输自定义组件"
              options={nameOptions}
              filterOption={(input, opt) =>
                String(opt?.value ?? '').toLowerCase().includes(input.toLowerCase())}
              onChange={(v) => {
                const hit = knownByName.get(String(v))
                if (hit) {
                  form.setFieldsValue({
                    layer: hit.layer,
                    license: hit.license,
                    ecosystem: hit.ecosystem ?? null,
                  })
                }
              }}
            />
          </Form.Item>
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
