/* 基础设施步骤(独立步骤): 架构图上传预览(每环境一张, #164)+ 设备清单手填。
   拓扑画布回退后, 架构关系以架构图表达, 清单沿用 uid upsert 契约(#66)。 */
import { useEffect, useRef, useState } from 'react'
import {
  Button, Checkbox, Form, Image, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tabs, Tag, Typography, Upload, message,
} from 'antd'
import {
  CloudServerOutlined, DatabaseOutlined, DeleteOutlined, DeploymentUnitOutlined,
  EditOutlined, HddOutlined, PlusOutlined, UploadOutlined,
} from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { InfraAssetRow } from '../../types'
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

export default function Step7InfraList({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [assets, setAssets] = useState<InfraAssetRow[]>(ws.infra_assets)
  const [editing, setEditing] = useState<InfraAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [activeEnv, setActiveEnv] = useState<'test' | 'prod' | 'dev'>('prod')
  const [archImages, setArchImages] = useState<Partial<Record<string, string>>>({})
  const savedRef = useRef(JSON.stringify(assets))

  useEffect(() => {
    // 加载三环境架构图; 失败不阻塞清单编辑
    api.listArchImages(ws.project.id)
      .then((rows) => setArchImages(Object.fromEntries(rows.map((r) => [r.env, r.image_data_url]))))
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
        按环境上传架构图并手填资产清单: 架构图表达整体拓扑关系, 规格等明细在清单里登记。
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
              <Space style={{ marginBottom: 8 }}>
                <Button
                  size="small" icon={<PlusOutlined />}
                  onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET, env }) }}
                >
                  新增资产
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
