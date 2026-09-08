/* 基础设施清单卡(系统级): 自 SystemInventoryCards 拆出并按 DESIGN 重排(#289) ——
   架构图按环境维护(环境列表由系统设置 infra_envs 可配置), 资产平铺为一张表,
   表上方提供 环境/资产类型/敏感数据 筛选。数据源 /api/systems/{id}/...,
   #259 起可被评估向导「基础设施」步骤内嵌(onHandle 注册步骤句柄)。 */
import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Checkbox, Form, Image, Input, InputNumber, Modal, Popconfirm, Select,
  Space, Table, Tabs, Tag, Typography, Upload, message,
} from 'antd'
import {
  CloudServerOutlined, DatabaseOutlined, DeleteOutlined, DeploymentUnitOutlined,
  EditOutlined, HddOutlined, PlusOutlined, UploadOutlined,
} from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { InfraAssetRow } from '../../types'
import type { InventoryCardHandle } from './inventoryCommon'

const EMPTY_ASSET: InfraAssetRow = {
  asset_type: 'server', name: '', env: 'prod', ip: null, owner: '',
  holds_sensitive: false, cpu_cores: null, memory_gb: null, disk_gb: null,
  os: null, quantity: 1, purpose: null,
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  server: <CloudServerOutlined />, database: <DatabaseOutlined />,
  middleware: <HddOutlined />, network: <DeploymentUnitOutlined />,
}

export function SystemInfraCard({ systemId, onHandle, onSaved }: {
  systemId: number
  onHandle?: (h: InventoryCardHandle | null) => void
  /** 保存成功后回吐最新清单(#259): 向导步骤据此同步 WizardState, 确认页条数不陈旧 */
  onSaved?: (rows: InfraAssetRow[]) => void
}) {
  const enums = useEnums()
  const [assets, setAssets] = useState<InfraAssetRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [editing, setEditing] = useState<InfraAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [archImages, setArchImages] = useState<Partial<Record<string, string>>>({})
  // 平铺表的筛选条(DESIGN TAB6): 环境 / 资产类型 / 是否承载敏感数据
  const [envFilter, setEnvFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [sensitiveOnly, setSensitiveOnly] = useState(false)

  // 环境列表来自后端统一下发的可配置枚举(系统设置 → 基础资源环境)
  const envs = useMemo(
    () => Object.entries(labelMapOf(enums, 'infra_envs')).map(([code, name]) => ({ code, name })),
    [enums],
  )
  const envName = (code: string | null | undefined) =>
    envs.find((e) => e.code === code)?.name ?? code ?? '—'

  useEffect(() => {
    setLoaded(false)
    api.getSystemInfraAssets(systemId)
      .then((rows) => { setAssets(rows); setDirty(false) })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoaded(true))
    api.getSystemArchImages(systemId)
      .then((rows) => setArchImages(Object.fromEntries(rows.map((r) => [r.env, r.image_data_url]))))
      .catch(() => undefined)
  }, [systemId])

  const save = async (silent = false): Promise<boolean> => {
    if (!dirty) return true
    setSaving(true)
    try {
      const fresh = await api.saveSystemInfraAssets(systemId, assets)
      setAssets(fresh)
      setDirty(false)
      onSaved?.(fresh)
      if (!silent) message.success(`已保存基础设施清单(共 ${fresh.length} 项资产)`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    } finally {
      setSaving(false)
    }
  }

  /** 架构图上传(#164): 前端读为 data URL, 类型/大小由后端校验 */
  const uploadArch = (env: string, file: File): boolean => {
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) {
      message.error('仅支持 png/jpg/webp 图片')
      return false
    }
    const reader = new FileReader()
    reader.onload = () => {
      api.uploadSystemArchImage(systemId, env, String(reader.result))
        .then((row) => {
          setArchImages((prev) => ({ ...prev, [env]: row.image_data_url }))
          message.success(`已更新${envName(env)}架构图`)
        })
        .catch((e: Error) => message.error(e.message))
    }
    reader.readAsDataURL(file)
    return false
  }

  const removeArch = (env: string) => {
    api.deleteSystemArchImage(systemId, env)
      .then(() => {
        setArchImages((prev) => ({ ...prev, [env]: undefined }))
        message.success(`已删除${envName(env)}架构图`)
      })
      .catch((e: Error) => message.error(e.message))
  }

  const mutate = (rows: InfraAssetRow[]) => { setAssets(rows); setDirty(true) }

  // 每次渲染后重新注册句柄(闭包始终指向最新状态), 卸载时注销 —— 与 useRegisterStepHandle 同套路
  useEffect(() => {
    onHandle?.({ save, isDirty: () => dirty })
    return () => onHandle?.(null)
  })

  const archCard = (env: string) => {
    const url = archImages[env]
    return (
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {url ? (
          <Image src={url} width={220} style={{ borderRadius: 4, border: '1px solid #eee' }} />
        ) : (
          <div style={{
            width: 220, height: 124, border: '1px dashed #d9d9d9', borderRadius: 4,
            display: 'grid', placeItems: 'center',
          }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              暂无{envName(env)}架构图
            </Typography.Text>
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
            png/jpg/webp, 不超过 2MB, 存库不落盘
          </Typography.Text>
        </Space>
      </div>
    )
  }

  const filtered = assets.filter((a) =>
    (!envFilter || (a.env || 'prod') === envFilter)
    && (!typeFilter || a.asset_type === typeFilter)
    && (!sensitiveOnly || a.holds_sensitive))

  return (
    <Card
      size="small" variant="borderless" title="基础设施清单(系统级)"
      extra={(
        <Space>
          {dirty && <Typography.Text type="warning" style={{ fontSize: 12 }}>有未保存修改</Typography.Text>}
          <Button size="small" type="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
            保存清单
          </Button>
        </Space>
      )}
    >
      {/* 拓扑(架构图): 按环境上传与展示, 环境列表可配置(系统设置 → 基础资源环境) */}
      <Tabs
        size="small"
        items={envs.map(({ code, name }) => ({
          key: code,
          label: <span>{TYPE_ICON[code] ?? <DeploymentUnitOutlined />} {name}</span>,
          children: archCard(code),
        }))}
      />

      {/* 资产台账: 平铺一张表 + 表上方筛选(DESIGN TAB6) */}
      <Space style={{ marginBottom: 8 }} wrap>
        <Button
          size="small" icon={<PlusOutlined />}
          onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET, env: envFilter ?? envs[0]?.code ?? 'prod' }) }}
        >
          新增资产
        </Button>
        <Select
          allowClear size="small" style={{ minWidth: 130 }} placeholder="环境"
          value={envFilter}
          options={envs.map((e) => ({ value: e.code, label: e.name }))}
          onChange={(v) => setEnvFilter(v)}
        />
        <Select
          allowClear size="small" style={{ minWidth: 130 }} placeholder="资产类型"
          value={typeFilter}
          options={optionsOf(enums, 'infra_asset_types')}
          onChange={(v) => setTypeFilter(v)}
        />
        <Checkbox checked={sensitiveOnly} onChange={(e) => setSensitiveOnly(e.target.checked)}>
          仅看承载敏感数据
        </Checkbox>
        <Typography.Text type="secondary">
          共 {filtered.length} 项资产(全部 {assets.length} 项)
        </Typography.Text>
      </Space>
      <Table<InfraAssetRow>
        rowKey={(r) => r.uid ?? String(r.id ?? r.name)}
        dataSource={filtered}
        pagination={false}
        size="small"
        loading={!loaded}
        locale={{ emptyText: '没有符合筛选条件的资产, 可点「新增资产」登记' }}
        columns={[
          { title: '环境', dataIndex: 'env', width: 100,
            render: (v: string | null) => <Tag>{envName(v)}</Tag> },
          { title: '类型', dataIndex: 'asset_type', width: 110,
            render: (v) => <Tag color={v === 'network' ? 'geekblue' : 'default'}>{TYPE_ICON[v] ?? null} {labelMapOf(enums, 'infra_asset_types')[v] ?? v}</Tag> },
          { title: '名称', dataIndex: 'name' },
          { title: 'IP/地址', dataIndex: 'ip', width: 120,
            render: (v) => v || <Typography.Text type="secondary">预留</Typography.Text> },
          { title: '规格', render: (_v, r) => r.asset_type === 'server'
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
                  <Popconfirm title="删除该资产?" onConfirm={() => mutate(assets.filter((a) => a !== r))}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              )
            },
          },
        ]}
      />

      {editing !== null && (
        <InfraModal
          key={`ia-${editIndex}-${editing.name}`}
          value={editing}
          enums={enums}
          envOptions={envs.map((e) => ({ value: e.code, label: e.name }))}
          onCancel={() => setEditing(null)}
          onOk={(next) => {
            const copy = [...assets]
            if (editIndex >= 0) copy[editIndex] = next
            else copy.push({ ...next, uid: next.uid ?? crypto.randomUUID() })
            mutate(copy)
            setEditing(null)
          }}
        />
      )}
    </Card>
  )
}

function InfraModal({ value, onOk, onCancel, enums, envOptions }: {
  value: InfraAssetRow | null
  onOk: (row: InfraAssetRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
  envOptions: { value: string; label: string }[]
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
            <Select options={envOptions} />
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
