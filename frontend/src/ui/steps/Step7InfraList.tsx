/* 基础设施步骤(独立步骤): 拓扑画布(测试/生产两套, #93)+设备清单双向联动, 开发环境走纯清单。
   设备/区域/连线/位置存拓扑端点, 不进规则引擎; 设备清单沿用 uid upsert 契约(#66)。 */
import { useEffect, useRef, useState } from 'react'
import {
  Button, Checkbox, Form, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tabs, Tag, Typography, message,
} from 'antd'
import {
  CloudServerOutlined, DatabaseOutlined, DeleteOutlined, DeploymentUnitOutlined,
  EditOutlined, HddOutlined, PlusOutlined,
} from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { InfraAssetRow } from '../../types'
import InfraTopologyCanvas, { DEVICE_TYPES, type TopoAsset, type TopoLayout, type TopoLink, type TopoZone } from './InfraTopologyCanvas'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const EMPTY_ASSET: InfraAssetRow = {
  asset_type: 'server', name: '', env: 'prod', ip: null, owner: '',
  holds_sensitive: false, cpu_cores: null, memory_gb: null, disk_gb: null,
  os: null, quantity: 1, purpose: null,
}

interface EnvTopo {
  zones: TopoZone[]
  links: TopoLink[]
  positions: { nodes: Record<string, { x: number; y: number }>; zones: Record<string, { x: number; y: number }> }
}

const EMPTY_TOPO: EnvTopo = { zones: [], links: [], positions: { nodes: {}, zones: {} } }
const CANVAS_ENVS = ['test', 'prod'] as const
const ALL_ENVS = ['test', 'prod', 'dev'] as const

const TYPE_ICON: Record<string, React.ReactNode> = {
  server: <CloudServerOutlined />, database: <DatabaseOutlined />,
  middleware: <HddOutlined />, network: <DeploymentUnitOutlined />,
}

export default function Step7InfraList({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [assets, setAssets] = useState<InfraAssetRow[]>(ws.infra_assets)
  const [editing, setEditing] = useState<InfraAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [activeEnv, setActiveEnv] = useState<'test' | 'prod' | 'dev'>('prod')
  const [topo, setTopo] = useState<Record<string, EnvTopo>>({ test: EMPTY_TOPO, prod: EMPTY_TOPO })
  const savedRef = useRef(JSON.stringify(assets))

  useEffect(() => {
    // 加载测试/生产两套画布(区域/连线/位置); 失败不阻塞清单编辑
    for (const env of CANVAS_ENVS) {
      api.getInfraTopology(ws.project.id, env)
        .then((t) => setTopo((prev) => ({
          ...prev,
          [env]: { zones: t.zones, links: t.links, positions: { nodes: t.layout.nodes ?? {}, zones: t.layout.zones ?? {} } },
        })))
        .catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const assetsOf = (env: string) => assets.filter((a) => (a.env || 'prod') === env)

  const canvasAssets = (env: string): InfraAssetRow[] => assetsOf(env)
  void canvasAssets
  const save = async (): Promise<boolean> => {
    try {
      let total = 0
      for (const env of ALL_ENVS) {
        const envAssets = assetsOf(env)
        const t = topo[env] ?? EMPTY_TOPO
        const res = await api.saveInfraTopology(ws.project.id, {
          env,
          zones: env === 'dev' ? [] : t.zones,
          links: env === 'dev' ? [] : t.links,
          layout: env === 'dev' ? {} : t.positions,
          assets: envAssets.map((a) => ({
            uid: a.uid, asset_type: a.asset_type, name: a.name, ip: a.ip, owner: a.owner,
            holds_sensitive: a.holds_sensitive, cpu_cores: a.cpu_cores, memory_gb: a.memory_gb,
            disk_gb: a.disk_gb, os: a.os, quantity: a.quantity, purpose: a.purpose,
            zone_uid: a.zone_uid ?? null,
          })),
        })
        total = res.assets
      }
      const fresh = await api.getInfraAssets(ws.project.id)
      setAssets(fresh)
      patch({ infra_assets: fresh })
      savedRef.current = JSON.stringify(fresh)
      message.success(`已保存基础设施拓扑与清单(共 ${total} 项设备)`)
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

  const updateEnvAssets = (env: string, rows: InfraAssetRow[]) => {
    // 替换该 env 的设备, 其余环境保持不变
    setAssets((prev) => [...prev.filter((a) => (a.env || 'prod') !== env), ...rows])
  }

  const isServer = (row: InfraAssetRow) => row.asset_type === 'server'

  /** 工具栏加设备: 画布当前位置生成节点 + 清单加一行(uid 前端生成, 保存时落库) */
  const addDevice = (assetType: string) => {
    if (activeEnv === 'dev') { message.info('开发环境走下方清单录入, 画布仅测试/生产'); return }
    const uid = crypto.randomUUID()
    const env = activeEnv === 'test' ? 'test' : 'prod'
    setAssets((prev) => [...prev, {
      ...EMPTY_ASSET, uid, asset_type: assetType, env, name: `${DEVICE_TYPES.find((d) => d.value === assetType)?.label ?? '设备'}`,
    }])
    setTopo((prev) => ({
      ...prev,
      [env]: {
        ...prev[env],
        positions: {
          ...prev[env].positions,
          nodes: { ...prev[env].positions.nodes, [uid]: { x: 260 + (prev[env].positions.nodes ? Object.keys(prev[env].positions.nodes).length % 4 : 0) * 30, y: 60 + (prev[env].positions.nodes ? Object.keys(prev[env].positions.nodes).length % 3 : 0) * 40 } },
        },
      },
    }))
  }

  const addZone = () => {
    if (activeEnv === 'dev') { message.info('开发环境走下方清单录入, 画布仅测试/生产'); return }
    const uid = crypto.randomUUID()
    setTopo((prev) => ({
      ...prev,
      [activeEnv]: {
        ...prev[activeEnv],
        zones: [...prev[activeEnv].zones, { uid, name: `区域${prev[activeEnv].zones.length + 1}` }],
      },
    }))
  }

  /** 画布变更回写: 设备/区域/连线与位置 */
  const onCanvasChange = (env: 'test' | 'prod') => (next: { assets?: TopoAsset[]; zones?: TopoZone[]; links?: TopoLink[]; positions?: TopoLayout }) => {
    if (next.assets !== undefined) {
      // 画布删除设备 → 用画布资产覆盖该 env 清单(保留表单已有规格字段)
      updateEnvAssets(env, next.assets.map((a) => {
        const existing = assets.find((x) => x.uid === a.uid)
        return existing ?? { ...EMPTY_ASSET, uid: a.uid, env, asset_type: a.asset_type, name: a.name, zone_uid: a.zone_uid ?? null }
      }))
    }
    if (next.zones !== undefined) {
      const zones = next.zones
      const links = next.links ?? (topo[env] ?? EMPTY_TOPO).links
      setTopo((prev) => {
        const cur = prev[env] ?? EMPTY_TOPO
        return { ...prev, [env]: { ...cur, zones, links } }
      })
    }
    if (next.links !== undefined) {
      const links = next.links
      setTopo((prev) => {
        const cur = prev[env] ?? EMPTY_TOPO
        return { ...prev, [env]: { ...cur, links } }
      })
    }
    if (next.positions !== undefined) {
      const positions = next.positions
      setTopo((prev) => {
        const cur = prev[env] ?? EMPTY_TOPO
        return { ...prev, [env]: { ...cur, positions } }
      })
    }
  }

  const topoFor = (env: 'test' | 'prod') => {
    const t = topo[env] ?? EMPTY_TOPO
    const canvasAssets: TopoAsset[] = assetsOf(env).map((a) => ({
      uid: a.uid ?? '', asset_type: a.asset_type, name: a.name, env: a.env,
      zone_uid: a.zone_uid ?? null, ip: a.ip, holds_sensitive: a.holds_sensitive,
    }))
    return { assets: canvasAssets, zones: t.zones, links: t.links, positions: t.positions }
  }

  const envTable = (env: string) => {
    const rows = assetsOf(env)
    return (
      <Table<InfraAssetRow>
        rowKey={(r) => r.uid ?? String(r.id ?? r.name)}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: '类型', dataIndex: 'asset_type', width: 100,
            render: (v) => <Tag color={v === 'network' ? 'geekblue' : 'default'}>{TYPE_ICON[v] ?? null} {labelMapOf(enums, 'infra_asset_types')[v] ?? v}</Tag> },
          { title: '名称', dataIndex: 'name' },
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

  return (
    <div style={{ maxWidth: 1120, margin: '0 auto' }}>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        测试与生产各有一套拓扑画布: 从工具栏添加设备与区域, 拖到合适位置, 连线(双击可写说明);
        画布与下方清单双向联动, 规格等字段在清单里补填。开发环境用清单登记即可。
      </Typography.Text>

      <Tabs
        activeKey={activeEnv}
        onChange={(k) => setActiveEnv(k as 'test' | 'prod' | 'dev')}
        items={[
          ...CANVAS_ENVS.map((env) => ({
            key: env,
            label: <span>{TYPE_ICON[env === 'test' ? 'middleware' : 'server'] ?? null} {env === 'test' ? '测试环境' : '生产环境'}</span>,
            children: (
              <div>
                <Space style={{ marginBottom: 8 }} wrap>
                  {DEVICE_TYPES.map((d) => (
                    <Button key={d.value} size="small" icon={TYPE_ICON[d.value]}
                      onClick={() => addDevice(d.value)}>添加{d.label}</Button>
                  ))}
                  <Button size="small" icon={<PlusOutlined />} onClick={addZone}>添加区域</Button>
                  <Typography.Text type="secondary">
                    {activeEnv === 'test' ? '测试环境' : '生产环境'}画布 · 共 {assetsOf(env).length} 项设备
                  </Typography.Text>
                </Space>
                <InfraTopologyCanvas
                  assets={topoFor(env).assets}
                  zones={topoFor(env).zones}
                  links={topoFor(env).links}
                  positions={topoFor(env).positions}
                  onChange={onCanvasChange(env)}
                />
                <div style={{ marginTop: 12 }}>{envTable(env)}</div>
              </div>
            ),
          })),
          {
            key: 'dev',
            label: '开发环境(仅清单)',
            children: (
              <div>
                <Space style={{ marginBottom: 8 }}>
                  <Button size="small" icon={<PlusOutlined />}
                    onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET, env: 'dev' }) }}>新增资产</Button>
                  <Typography.Text type="secondary">共 {assetsOf('dev').length} 项(允许为空)</Typography.Text>
                </Space>
                {envTable('dev')}
              </div>
            ),
          },
        ]}
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
