/* 基础设施步骤(独立步骤): 架构图上传预览(每环境一张, #164)+ 设备清单手填,
   支持从 NetBox 导入资产与手动推送写回(#153, 旁路增强不断连主流程)。 */
import { useEffect, useRef, useState } from 'react'
import type { Key } from 'react'
import {
  Alert, Button, Checkbox, Form, Image, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tabs, Tag, Typography, Upload, message,
} from 'antd'
import {
  CloudServerOutlined, DatabaseOutlined, DeleteOutlined, DeploymentUnitOutlined,
  EditOutlined, HddOutlined, ImportOutlined, PlusOutlined, UploadOutlined,
} from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { InfraAssetRow, NetboxAssetRow } from '../../types'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const EMPTY_ASSET: InfraAssetRow = {
  asset_type: 'server', name: '', env: 'prod', ip: null, owner: '',
  holds_sensitive: false, cpu_cores: null, memory_gb: null, disk_gb: null,
  os: null, quantity: 1, purpose: null,
}

const ALL_ENVS = ['test', 'prod', 'dev'] as const
const ENV_LABEL: Record<string, string> = { test: '测试环境', prod: '生产环境', dev: '开发环境' }
const ENV_ICON: Record<string, React.ReactNode> = {
  test: <HddOutlined />, prod: <CloudServerOutlined />, dev: <DeploymentUnitOutlined />,
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  server: <CloudServerOutlined />, database: <DatabaseOutlined />,
  middleware: <HddOutlined />, network: <DeploymentUnitOutlined />,
}

type NetboxKind = 'devices' | 'virtual-machines' | 'ip-addresses'

/** NetBox 对象类型 → 资产默认字段映射(#153): 环境由导入弹窗统一选择, 其余可手改 */
const NETBOX_KIND_META: Record<NetboxKind, { label: string; refType: string; assetType: string }> = {
  devices: { label: '设备', refType: 'dcim.device', assetType: 'server' },
  'virtual-machines': { label: '虚拟机', refType: 'virtualization.virtual-machine', assetType: 'server' },
  'ip-addresses': { label: 'IP 地址', refType: 'ipam.ip-address', assetType: 'network' },
}

function netboxLink(baseUrl: string | undefined, refType: string | null | undefined,
                    refId: string | null | undefined): string | undefined {
  if (!baseUrl || !refType || !refId) return undefined
  const path = refType === 'virtualization.virtual-machine'
    ? 'virtualization/virtual-machines'
    : refType === 'ipam.ip-address' ? 'ipam/ip-addresses' : 'dcim/devices'
  return `${baseUrl}/${path}/${refId}/`
}

export default function Step7InfraList({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [assets, setAssets] = useState<InfraAssetRow[]>(ws.infra_assets)
  const [editing, setEditing] = useState<InfraAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [activeEnv, setActiveEnv] = useState<'test' | 'prod' | 'dev'>('prod')
  const [archImages, setArchImages] = useState<Partial<Record<string, string>>>({})
  const savedRef = useRef(JSON.stringify(assets))
  // NetBox 互通(#153): 导入弹窗 + 推送弹窗状态; 失败只影响弹窗, 手填保存不受影响
  const [importOpen, setImportOpen] = useState(false)
  const [importKind, setImportKind] = useState<NetboxKind>('devices')
  const [importKeyword, setImportKeyword] = useState('')
  const [importRows, setImportRows] = useState<NetboxAssetRow[]>([])
  const [importTotal, setImportTotal] = useState(0)
  const [importPage, setImportPage] = useState(1)
  const [importError, setImportError] = useState<string | null>(null)
  const [importLoading, setImportLoading] = useState(false)
  const [importSelected, setImportSelected] = useState<NetboxAssetRow[]>([])
  const [importEnv, setImportEnv] = useState<'test' | 'prod' | 'dev'>('prod')
  const [pushOpen, setPushOpen] = useState(false)
  const [pushTargets, setPushTargets] = useState<InfraAssetRow[]>([])
  const [pushOptions, setPushOptions] = useState<{
    sites: { id: number; name: string }[]; roles: { id: number; name: string }[];
    device_types: { id: number; model: string }[]
  } | null>(null)
  const [pushError, setPushError] = useState<string | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [nbBaseUrl, setNbBaseUrl] = useState<string | undefined>(undefined)

  useEffect(() => {
    // 加载三环境架构图; 失败不阻塞清单编辑
    api.listArchImages(ws.project.id)
      .then((rows) => setArchImages(Object.fromEntries(rows.map((r) => [r.env, r.image_data_url]))))
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // 已有 NetBox 关联行时才取 base_url 构建外链(#153); 未配置/断连静默
    if (!assets.some((a) => a.netbox_ref_id)) return
    api.getNetboxStatus()
      .then((s) => { if (s.configured) setNbBaseUrl(s.base_url) })
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const assetsOf = (env: string) => assets.filter((a) => (a.env || 'prod') === env)

  const save = async (): Promise<boolean> => {
    try {
      await api.saveInfraAssets(ws.project.id, assets)
      const fresh = await api.getInfraAssets(ws.project.id)
      setAssets(fresh)
      patch({ infra_assets: fresh })
      savedRef.current = JSON.stringify(fresh)
      message.success(`已保存基础设施清单(共 ${fresh.length} 项资产)`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({
    save,
    isDirty: () => JSON.stringify(assets) !== savedRef.current,
  })

  const isServer = (row: InfraAssetRow) => row.asset_type === 'server'

  /** 架构图上传(#164): 前端读为 data URL, 类型/大小由后端校验; 返回 false 阻止 antd 自动上传 */
  const uploadArch = (env: string, file: File): boolean => {
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) {
      message.error('仅支持 png/jpg/webp 图片')
      return false
    }
    const reader = new FileReader()
    reader.onload = () => {
      api.saveArchImage(ws.project.id, env, String(reader.result))
        .then((row) => {
          setArchImages((prev) => ({ ...prev, [env]: row.image_data_url }))
          message.success(`已更新${ENV_LABEL[env]}架构图`)
        })
        .catch((e: Error) => message.error(e.message))
    }
    reader.readAsDataURL(file)
    return false
  }

  const removeArch = (env: string) => {
    api.deleteArchImage(ws.project.id, env)
      .then(() => {
        setArchImages((prev) => ({ ...prev, [env]: undefined }))
        message.success(`已删除${ENV_LABEL[env]}架构图`)
      })
      .catch((e: Error) => message.error(e.message))
  }

  // ── NetBox 导入(#153): 搜索/翻页/勾选, 映射为资产行走既有整卷保存 ──
  const loadImport = (kind: NetboxKind, keyword: string, page: number) => {
    setImportLoading(true)
    setImportError(null)
    api.listNetboxAssets(kind, keyword, 10, (page - 1) * 10)
      .then((data) => {
        setImportRows(data.results ?? [])
        setImportTotal(data.count ?? 0)
        setImportSelected([])
      })
      .catch((e: Error) => setImportError(e.message))
      .finally(() => setImportLoading(false))
  }

  const openImport = () => {
    setImportOpen(true)
    setImportRows([]); setImportTotal(0); setImportPage(1)
    setImportSelected([]); setImportError(null); setImportKeyword('')
    loadImport(importKind, '', 1)
  }

  const importToRows = () => {
    const fresh: InfraAssetRow[] = []
    let skipped = 0
    for (const row of importSelected) {
      const refId = String(row.id)
      if (assets.some((a) => a.netbox_ref_id === refId)) { skipped += 1; continue }
      const meta = NETBOX_KIND_META[importKind]
      fresh.push({
        ...EMPTY_ASSET,
        uid: crypto.randomUUID(),
        env: importEnv,
        asset_type: meta.assetType,
        name: row.name || row.address || `NetBox#${row.id}`,
        ip: row.primary_ip || row.address || null,
        os: row.platform ?? null,
        quantity: 1,
        netbox_ref_type: meta.refType,
        netbox_ref_id: refId,
      })
    }
    if (fresh.length) setAssets((prev) => [...prev, ...fresh])
    message.success(
      `已导入 ${fresh.length} 项${skipped ? `, 跳过已存在 ${skipped} 项` : ''}; 记得保存清单`)
    setImportOpen(false)
  }

  // ── NetBox 推送(#153): 保存后的旁路动作, 失败不回滚、可重试 ──
  const openPush = () => {
    const targets = assets.filter(
      (a) => selectedKeys.includes((a.uid ?? String(a.id)) as Key) && !a.netbox_ref_id)
    const linked = assets.filter(
      (a) => selectedKeys.includes((a.uid ?? String(a.id)) as Key) && a.netbox_ref_id).length
    if (!targets.length) { message.info('请选择尚未关联 NetBox 的资产行'); return }
    if (linked) message.info(`${linked} 行已关联 NetBox, 已自动跳过`)
    setPushTargets(targets)
    setPushError(null)
    setPushOpen(true)
    if (!pushOptions) {
      api.getNetboxOptions()
        .then(setPushOptions)
        .catch((e: Error) => setPushError(e.message))
    }
  }

  const pushRows = (siteId: number, roleId: number, typeId: number, ip: string | undefined) => {
    let ok = 0
    const failures: string[] = []
    const refs: Record<string, { refType: string; refId: string; url: string }> = {}
    const run = async () => {
      for (const target of pushTargets) {
        try {
          const res = await api.pushNetboxDevice({
            project_id: ws.project.id,
            asset_id: target.id as number,
            name: target.name,
            site_id: siteId, role_id: roleId, device_type_id: typeId,
            ip_address: ip || undefined,
          })
          ok += 1
          refs[target.uid ?? String(target.id)] = {
            refType: res.netbox_ref_type, refId: res.netbox_ref_id, url: res.url,
          }
          if (res.note) failures.push(`${target.name}: ${res.note}`)
        } catch (e) {
          failures.push(`${target.name}: ${(e as Error).message}`)
        }
      }
      if (ok) {
        // 推送已在后端落库, 前端行同步回填; 整卷再保存时字段幂等
        setAssets((prev) => prev.map((a) => {
          const ref = refs[a.uid ?? String(a.id)]
          return ref
            ? { ...a, netbox_ref_type: ref.refType, netbox_ref_id: ref.refId }
            : a
        }))
      }
      setPushOpen(false)
      message.success(`已推送 ${ok} 项到 NetBox${failures.length ? `; ${failures.length} 项失败, 可修复后重试` : ''}`)
      if (failures.length) Modal.info({
        title: '推送失败明细', width: 560,
        content: failures.map((f, i) => <div key={i} style={{ fontSize: 12 }}>{f}</div>),
      })
    }
    void run()
  }

  const archCard = (env: string) => {
    const url = archImages[env]
    return (
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {url ? (
          <Image src={url} width={220} style={{ borderRadius: 4, border: '1px solid #eee' }} />
        ) : (
          <div style={{
            width: 220, height: 124, border: '1px dashed #d9d9d9', borderRadius: 4,
            display: 'grid', placeItems: 'center', color: '#999', fontSize: 12,
          }}>
            暂无{ENV_LABEL[env]}架构图
          </div>
        )}
        <Space direction="vertical" size={6}>
          <Upload
            accept=".png,.jpg,.jpeg,.webp" showUploadList={false}
            beforeUpload={(f) => uploadArch(env, f as unknown as File)}
          >
            <Button size="small" icon={<UploadOutlined />}>{url ? '替换架构图' : '上传架构图'}</Button>
          </Upload>
          {url && (
            <Popconfirm title="删除该架构图?" onConfirm={() => removeArch(env)}>
              <Button size="small" danger icon={<DeleteOutlined />}>删除架构图</Button>
            </Popconfirm>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            png/jpg/webp, 不超过 2MB; 随项目复制/评估继承自动带走
          </Typography.Text>
        </Space>
      </div>
    )
  }

  const envTable = (env: string) => {
    const rows = assetsOf(env)
    return (
      <Table<InfraAssetRow>
        rowKey={(r) => r.uid ?? String(r.id ?? r.name)}
        dataSource={rows}
        pagination={false}
        size="small"
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: setSelectedKeys,
          getCheckboxProps: (r) => ({ disabled: Boolean(r.netbox_ref_id) }),
        }}
        columns={[
          { title: '类型', dataIndex: 'asset_type', width: 100,
            render: (v) => <Tag color={v === 'network' ? 'geekblue' : 'default'}>{TYPE_ICON[v] ?? null} {labelMapOf(enums, 'infra_asset_types')[v] ?? v}</Tag> },
          { title: '名称', dataIndex: 'name',
            render: (v, r) => {
              const link = netboxLink(nbBaseUrl, r.netbox_ref_type, r.netbox_ref_id)
              return (
                <Space size={6}>
                  <span>{v}</span>
                  {r.netbox_ref_id && (
                    <Tag color="blue" style={{ marginRight: 0 }}>
                      {link ? <a href={link} target="_blank" rel="noreferrer">NetBox</a> : 'NetBox'}
                    </Tag>
                  )}
                </Space>
              )
            } },
          { title: 'IP/地址', dataIndex: 'ip', width: 120,
            render: (v) => v || <Typography.Text type="secondary">预留</Typography.Text> },
          { title: '规格', render: (_v, r) => isServer(r)
            ? [r.cpu_cores && `${r.cpu_cores}核`, r.memory_gb && `${r.memory_gb}G内存`, r.disk_gb && `${r.disk_gb}G盘`, r.os]
              .filter(Boolean).join(' / ') || '—'
            : (r.purpose || '—') },
          { title: '数量', dataIndex: 'quantity', width: 70, render: (v) => v ?? '—' },
          { title: '承载敏感数据', dataIndex: 'holds_sensitive', width: 110,
            render: (v: boolean) => (v ? <Tag color="red">是</Tag> : '否') },
          {
            title: '操作', width: 110,
            render: (_v, r) => {
              const idx = assets.indexOf(r)
              return (
                <Space>
                  <Button size="small" icon={<EditOutlined />}
                    onClick={() => { setEditIndex(idx); setEditing({ ...r }) }} />
                  <Popconfirm title="删除该资产?" onConfirm={() => setAssets(assets.filter((a) => a !== r))}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              )
            },
          },
        ]}
      />
    )
  }

  // 已关联行的 NetBox 外链需要 base_url; 存在关联行时挂载期拉一次(未配置静默)
  return (
    <div style={{ maxWidth: 1120, margin: '0 auto' }}>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        按环境上传架构图并手填资产清单: 架构图表达整体拓扑关系, 规格等明细在清单里登记。
        可从 NetBox 导入资产, 或把已保存的清单行推送写回 NetBox(旁路增强, 断连不影响本步)。
      </Typography.Text>

      <Tabs
        activeKey={activeEnv}
        onChange={(k) => setActiveEnv(k as 'test' | 'prod' | 'dev')}
        items={ALL_ENVS.map((env) => ({
          key: env,
          label: <span>{ENV_ICON[env] ?? null} {ENV_LABEL[env]}</span>,
          children: (
            <div>
              {archCard(env)}
              <Space style={{ marginBottom: 8 }} wrap>
                <Button
                  size="small" icon={<PlusOutlined />}
                  onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET, env }) }}
                >
                  新增资产
                </Button>
                <Button size="small" icon={<ImportOutlined />}
                  onClick={() => { setImportEnv(env); openImport() }}>
                  从 NetBox 导入
                </Button>
                <Button size="small" disabled={selectedKeys.length === 0} onClick={openPush}>
                  推送到 NetBox
                </Button>
                <Typography.Text type="secondary">
                  {ENV_LABEL[env]}共 {assetsOf(env).length} 项资产{env === 'dev' ? '(允许为空)' : ''}
                </Typography.Text>
              </Space>
              {envTable(env)}
            </div>
          ),
        }))}
      />

      {editing !== null && (
        <InfraModal
          key={`ia-${editIndex}-${editing.name}`}
          value={editing}
          enums={enums}
          onCancel={() => setEditing(null)}
          onOk={(next) => {
            const copy = [...assets]
            if (editIndex >= 0) copy[editIndex] = next
            else copy.push({ ...next, uid: next.uid ?? crypto.randomUUID() })
            setAssets(copy)
            setEditing(null)
          }}
        />
      )}

      <NetboxImportModal
        open={importOpen}
        kind={importKind}
        keyword={importKeyword}
        env={importEnv}
        rows={importRows}
        total={importTotal}
        page={importPage}
        loading={importLoading}
        error={importError}
        selected={importSelected}
        onClose={() => setImportOpen(false)}
        onKind={(k) => { setImportKind(k); setImportPage(1); setImportSelected([]); loadImport(k, importKeyword, 1) }}
        onKeyword={(kw) => { setImportKeyword(kw); setImportPage(1); loadImport(importKind, kw, 1) }}
        onPage={(page) => { setImportPage(page); loadImport(importKind, importKeyword, page) }}
        onSelected={setImportSelected}
        onEnv={setImportEnv}
        onRetry={() => loadImport(importKind, importKeyword, importPage)}
        onOk={importToRows}
      />

      <NetboxPushModal
        open={pushOpen}
        targets={pushTargets}
        options={pushOptions}
        error={pushError}
        onClose={() => setPushOpen(false)}
        onRetryOptions={() => {
          setPushError(null)
          api.getNetboxOptions().then(setPushOptions).catch((e: Error) => setPushError(e.message))
        }}
        onPush={pushRows}
      />
    </div>
  )
}

function InfraModal({ value, onOk, onCancel, enums }: {
  value: InfraAssetRow | null
  onOk: (row: InfraAssetRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
}) {
  const [form] = Form.useForm<InfraAssetRow>()
  const type = Form.useWatch('asset_type', form)
  return (
    <Modal
      title="基础设施资产" open={value !== null} onCancel={onCancel}
      onOk={() => form.validateFields()
        .then((v) => onOk({ ...(value ?? EMPTY_ASSET), ...v }))
        .catch(() => { /* 校验失败, 留在弹窗 */ })}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY_ASSET}>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="asset_type" label="资产类型" rules={[{ required: true }]} style={{ width: 160 }}>
            <Select options={optionsOf(enums, 'infra_asset_types')} />
          </Form.Item>
          <Form.Item name="env" label="环境" rules={[{ required: true }]} style={{ width: 130 }}>
            <Select options={optionsOf(enums, 'env_names')} />
          </Form.Item>
          <Form.Item name="quantity" label="数量" style={{ width: 110 }}>
            <InputNumber min={1} max={9999} style={{ width: '100%' }} />
          </Form.Item>
        </Space>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="服务器: 如 应用服务器-生产 / 网络: 如 负载均衡" />
        </Form.Item>
        {type === 'server' ? (
          <Space size={12} style={{ display: 'flex' }} align="start">
            <Form.Item name="cpu_cores" label="CPU核数" style={{ width: 110 }}>
              <InputNumber min={1} max={1024} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="memory_gb" label="内存(GB)" style={{ width: 110 }}>
              <InputNumber min={1} max={4096} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="disk_gb" label="磁盘(GB)" style={{ width: 110 }}>
              <InputNumber min={1} max={1000000} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="os" label="操作系统" style={{ flex: 1 }}>
              <Input placeholder="如 CentOS 7.9 / 麒麟V10" />
            </Form.Item>
          </Space>
        ) : (
          <Form.Item name="purpose" label="用途/网络区域" extra="如: 接入层负载均衡, 设计期可只写区域规划">
            <Input placeholder="如: DMZ 区反向代理" />
          </Form.Item>
        )}
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="ip" label="IP/地址" extra="设计期没有可留空(预留)">
            <Input placeholder="10.x.x.x" />
          </Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
        </Space>
        <Form.Item name="holds_sensitive" label="是否承载敏感数据" valuePropName="checked">
          <Checkbox>承载敏感数据</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  )
}

type NetboxOptions = {
  sites: { id: number; name: string }[]
  roles: { id: number; name: string }[]
  device_types: { id: number; model: string }[]
}

/** NetBox 导入弹窗(#153): 数据源切换 + keyword 搜索 + 分页勾选; 未配置/断连给可读空态+重试。 */
function NetboxImportModal({ open, kind, keyword, env, rows, total, page, loading, error, selected, onClose, onKind, onKeyword, onPage, onSelected, onEnv, onRetry, onOk }: {
  open: boolean
  kind: NetboxKind
  keyword: string
  env: 'test' | 'prod' | 'dev'
  rows: NetboxAssetRow[]
  total: number
  page: number
  loading: boolean
  error: string | null
  selected: NetboxAssetRow[]
  onClose: () => void
  onKind: (k: NetboxKind) => void
  onKeyword: (kw: string) => void
  onPage: (page: number) => void
  onSelected: (rows: NetboxAssetRow[]) => void
  onEnv: (env: 'test' | 'prod' | 'dev') => void
  onRetry: () => void
  onOk: () => void
}) {
  const nameOf = (row: NetboxAssetRow) => row.name || row.address || `NetBox#${row.id}`
  return (
    <Modal
      title="从 NetBox 导入资产" open={open} onCancel={onClose} width={720}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" disabled={selected.length === 0} onClick={onOk}>
          导入所选 {selected.length} 项
        </Button>,
      ]}
    >
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          style={{ width: 130 }} value={kind}
          options={Object.entries(NETBOX_KIND_META).map(([value, meta]) => ({ value, label: meta.label }))}
          onChange={(k) => onKind(k as NetboxKind)}
        />
        <Input.Search
          style={{ width: 260 }} placeholder="关键字搜索" allowClear
          defaultValue={keyword} onSearch={onKeyword}
        />
        <Select
          style={{ width: 120 }} value={env}
          options={[{ value: 'prod', label: '导入到生产' }, { value: 'test', label: '导入到测试' }, { value: 'dev', label: '导入到开发' }]}
          onChange={(v) => onEnv(v as 'test' | 'prod' | 'dev')}
        />
      </Space>
      {error ? (
        <Alert
          type="warning" showIcon
          message={`NetBox 暂不可用: ${error}`}
          description="手填清单与保存完全不受影响; 可稍后重试。"
          action={<Button size="small" onClick={onRetry}>重试</Button>}
        />
      ) : (
        <Table<NetboxAssetRow>
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={rows}
          pagination={{ current: page, pageSize: 10, total, showSizeChanger: false }}
          onChange={(pagination) => onPage(pagination.current ?? 1)}
          rowSelection={{
            selectedRowKeys: selected.map((r) => r.id),
            onChange: (_, rows) => onSelected(rows),
          }}
          locale={{ emptyText: '无匹配数据' }}
          columns={[
            { title: '名称', render: (_v, r) => nameOf(r) },
            { title: kind === 'ip-addresses' ? '地址' : 'IP',
              render: (_v, r) => r.primary_ip || r.address || '—' },
            { title: kind === 'devices' ? '站点' : '站点/平台', ellipsis: true,
              render: (_v, r) => r.site || r.platform || '—' },
            { title: '角色/类型', ellipsis: true,
              render: (_v, r) => r.role || r.device_type || '—' },
          ]}
        />
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        导入行默认「{NETBOX_KIND_META[kind].label}」类型、数量 1, 环境统一为「{env === 'prod' ? '生产' : env === 'test' ? '测试' : '开发'}」, 导入后可再逐行修改; 需保存清单才落库。
      </Typography.Text>
    </Modal>
  )
}

/** NetBox 推送弹窗(#153): site/role/device_type 必填 + 可选 IP; 失败不回滚、可重试。 */
function NetboxPushModal({ open, targets, options, error, onClose, onRetryOptions, onPush }: {
  open: boolean
  targets: InfraAssetRow[]
  options: NetboxOptions | null
  error: string | null
  onClose: () => void
  onRetryOptions: () => void
  onPush: (siteId: number, roleId: number, typeId: number, ip?: string) => void
}) {
  const multiQty = targets.some((t) => (t.quantity ?? 1) > 1)
  const defaultIp = targets.length === 1 ? targets[0].ip ?? undefined : undefined
  return (
    <Modal
      title={`推送到 NetBox(已选 ${targets.length} 行)`} open={open} onCancel={onClose}
      footer={null} width={560}
    >
      {error ? (
        <Alert
          type="warning" showIcon style={{ marginBottom: 12 }}
          message={`NetBox 暂不可用: ${error}`}
          action={<Button size="small" onClick={onRetryOptions}>重试</Button>}
        />
      ) : !options ? (
        <Alert type="info" showIcon message="正在拉取 NetBox 站点/角色/设备类型…" />
      ) : (
        <NetboxPushForm
          count={targets.length}
          options={options} multiQty={multiQty}
          defaultIp={defaultIp}
          onSubmit={(siteId, roleId, typeId, ip) => onPush(siteId, roleId, typeId, ip || undefined)}
          onCancel={onClose}
        />
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        推送是保存后的旁路动作: 失败不影响本系统清单, 可修复后重试; 数量大于 1 的行按一台推送。
      </Typography.Text>
    </Modal>
  )
}

function NetboxPushForm({ count, options, multiQty, defaultIp, onSubmit, onCancel }: {
  count: number
  options: NetboxOptions
  multiQty: boolean
  defaultIp?: string
  onSubmit: (siteId: number, roleId: number, typeId: number, ip?: string) => void
  onCancel: () => void
}) {
  const [siteId, setSiteId] = useState<number>()
  const [roleId, setRoleId] = useState<number>()
  const [typeId, setTypeId] = useState<number>()
  const [ip, setIp] = useState<string>(defaultIp ?? '')
  const [pushing, setPushing] = useState(false)
  const ready = siteId !== undefined && roleId !== undefined && typeId !== undefined
  return (
    <div>
      {multiQty && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="所选行含数量大于 1 的资产, 将按一台推送" />
      )}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Select
          placeholder="站点(必填)" style={{ width: '100%' }} value={siteId}
          options={options.sites.map((s) => ({ value: s.id, label: s.name }))}
          onChange={setSiteId}
        />
        <Select
          placeholder="设备角色(必填)" style={{ width: '100%' }} value={roleId}
          options={options.roles.map((r) => ({ value: r.id, label: r.name }))}
          onChange={setRoleId}
        />
        <Select
          placeholder="设备类型(必填)" style={{ width: '100%' }} value={typeId}
          options={options.device_types.map((t) => ({ value: t.id, label: t.model }))}
          onChange={setTypeId}
        />
        <Input
          placeholder="管理 IP(可选, 如 10.0.0.1/24)" value={ip}
          onChange={(e) => setIp(e.target.value)}
        />
        <Space>
          <Button type="primary" loading={pushing} disabled={!ready}
            onClick={() => {
              setPushing(true)
              onSubmit(siteId as number, roleId as number, typeId as number, ip || undefined)
            }}>
            推送所选 {count} 行
          </Button>
          <Button onClick={onCancel}>取消</Button>
        </Space>
      </Space>
    </div>
  )
}
