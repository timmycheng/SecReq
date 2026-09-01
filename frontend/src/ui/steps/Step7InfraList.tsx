/* 基础设施清单(独立步骤): 服务器(规格: CPU/内存/OS/磁盘/数量)、网络设备(设计期地址可预留)、
   数据库与中间件。设计阶段拿不到具体网络地址属正常, IP 留空即可。本步允许为空。 */
import { useRef, useState } from 'react'
import {
  Button, Checkbox, Form, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

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

export default function Step7InfraList({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [assets, setAssets] = useState<InfraAssetRow[]>(ws.infra_assets)
  const [editing, setEditing] = useState<InfraAssetRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const savedRef = useRef(JSON.stringify(assets))

  const save = async (): Promise<boolean> => {
    try {
      const saved = await api.saveInfraAssets(ws.project.id, assets)
      patch({ infra_assets: saved })
      savedRef.current = JSON.stringify(assets)
      message.success(`已保存 ${saved.length} 项基础设施资产`)
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

  return (
    <div style={{ maxWidth: 1120, margin: '0 auto' }}>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        登记系统部署所需的基础设施。服务器请尽量填规格(CPU 核数/内存/操作系统/磁盘), 供容量与
        安全基线评估; 网络设备设计阶段往往没有具体地址, IP 留空即为预留。
      </Typography.Text>

      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />}
          onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_ASSET }) }}>新增资产</Button>
        <Typography.Text type="secondary">共 {assets.length} 项(允许为空)</Typography.Text>
      </Space>
      <Table<InfraAssetRow>
        rowKey={(_, i) => String(i)}
        dataSource={assets}
        pagination={false}
        size="small"
        columns={[
          { title: '类型', dataIndex: 'asset_type', width: 100,
            render: (v) => <Tag color={v === 'network' ? 'geekblue' : 'default'}>{labelMapOf(enums, 'infra_asset_types')[v] ?? v}</Tag> },
          { title: '名称', dataIndex: 'name' },
          { title: '环境', dataIndex: 'env', width: 80,
            render: (v) => labelMapOf(enums, 'env_names')[v] ?? v },
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
            render: (_v, _r, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { setEditIndex(index); setEditing({ ...assets[index] }) }} />
                <Popconfirm title="删除该资产?" onConfirm={() => setAssets(assets.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
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
            else copy.push(next)
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
