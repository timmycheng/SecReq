/* Step8 API 接口清单与基础设施资产清单。
   接口的敏感数据关联引用 Step4 数据资产 id(联动规则引擎接口安全维度)。 */
import { useState } from 'react'
import {
  Button, Checkbox, Form, Input, Modal, Popconfirm, Select, Space, Table,
  Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { ApiEndpointRow, InfraAssetRow } from '../../types'
import type { StepProps } from '../WizardPage'

const EMPTY_EP: ApiEndpointRow = {
  name: '', path: '', method: 'GET', auth_required: true,
  public_exposed: false, sensitive_asset_ids: [], rate_limit: null,
}
const EMPTY_ASSET: InfraAssetRow = {
  asset_type: 'server', name: '', env: 'prod', ip: '', owner: '', holds_sensitive: false,
}

export default function Step8Inventory({ ws, patch, advance }: StepProps) {
  const enums = useEnums()
  const [endpoints, setEndpoints] = useState<ApiEndpointRow[]>(ws.api_endpoints)
  const [infraAssets, setInfraAssets] = useState<InfraAssetRow[]>(ws.infra_assets)
  const [epEditing, setEpEditing] = useState<ApiEndpointRow | null>(null)
  const [epEditIndex, setEpEditIndex] = useState(-1)
  const [iaEditing, setIaEditing] = useState<InfraAssetRow | null>(null)
  const [iaEditIndex, setIaEditIndex] = useState(-1)
  const [saving, setSaving] = useState(false)

  const assetNameById = new Map(ws.data_assets.map((a) => [a.id as number, a.name]))

  const save = async () => {
    setSaving(true)
    try {
      const resp = await api.saveInventory(ws.project.id, endpoints, infraAssets)
      patch({ api_endpoints: resp.api_endpoints, infra_assets: resp.infra_assets })
      message.success(`已保存 ${resp.saved?.api_endpoints ?? endpoints.length} 个接口、${resp.saved?.infra_assets ?? infraAssets.length} 个资产`)
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Text strong>API 接口清单</Typography.Text>
        <Button size="small" icon={<PlusOutlined />}
          onClick={() => { setEpEditIndex(-1); setEpEditing({ ...EMPTY_EP }) }}>新增接口</Button>
      </Space>
      <Table<ApiEndpointRow>
        rowKey={(r) => `${r.method} ${r.path}`}
        dataSource={endpoints}
        pagination={false}
        size="small"
        columns={[
          { title: '接口名', dataIndex: 'name' },
          { title: '路径', dataIndex: 'path', render: (v) => <code>{v}</code> },
          { title: '方法', dataIndex: 'method', width: 80, render: (m) => <Tag color={METHOD_COLOR[m] ?? 'default'}>{m}</Tag> },
          { title: '需认证', dataIndex: 'auth_required', width: 90,
            render: (v) => (v ? '是' : <Tag color="red">匿名!</Tag>) },
          { title: '公网暴露', dataIndex: 'public_exposed', width: 90,
            render: (v) => (v ? <Tag color="orange">是</Tag> : '否') },
          { title: '关联敏感数据资产', dataIndex: 'sensitive_asset_ids',
            render: (ids: number[]) => ids.map((id) => assetNameById.get(id))
              .filter(Boolean).map((n) => <Tag key={n as string} color="purple">{n}</Tag>) },
          { title: '限流配置', dataIndex: 'rate_limit', render: (v) => v || '—' },
          {
            title: '操作', width: 110,
            render: (_v, _r, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => { setEpEditIndex(index); setEpEditing({ ...endpoints[index] }) }} />
                <Popconfirm title="删除该接口?" onConfirm={() => setEndpoints(endpoints.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Space style={{ margin: '16px 0 8px' }}>
        <Typography.Text strong>基础设施资产清单</Typography.Text>
        <Button size="small" icon={<PlusOutlined />}
          onClick={() => { setIaEditIndex(-1); setIaEditing({ ...EMPTY_ASSET }) }}>新增资产</Button>
      </Space>
      <Table<InfraAssetRow>
        rowKey={(r) => r.name}
        dataSource={infraAssets}
        pagination={false}
        size="small"
        columns={[
          { title: '类型', dataIndex: 'asset_type', width: 120,
            render: (v) => labelMapOf(enums, 'infra_asset_types')[v] ?? v },
          { title: '名称', dataIndex: 'name' },
          { title: '环境', dataIndex: 'env', width: 100,
            render: (v) => labelMapOf(enums, 'env_names')[v] ?? v },
          { title: 'IP', dataIndex: 'ip' },
          { title: '负责人', dataIndex: 'owner' },
          { title: '承载敏感数据', dataIndex: 'holds_sensitive', width: 110,
            render: (v) => (v ? <Tag color="red">是</Tag> : '否') },
          {
            title: '操作', width: 110,
            render: (_v, _r, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => { setIaEditIndex(index); setIaEditing({ ...infraAssets[index] }) }} />
                <Popconfirm title="删除该资产?" onConfirm={() => setInfraAssets(infraAssets.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <div style={{ marginTop: 20 }}>
        <Button type="primary" loading={saving} onClick={save}>保存并进入确认页</Button>
      </div>

      {epEditing !== null && (
        <EndpointModal
          key={`ep-${epEditIndex}-${epEditing.name}`}
          value={epEditing}
          dataAssets={ws.data_assets.map((a) => ({ id: a.id as number, name: a.name, classification: a.classification }))}
          onCancel={() => setEpEditing(null)}
          onOk={(next) => {
            const copy = [...endpoints]
            if (epEditIndex >= 0) copy[epEditIndex] = next
            else copy.push(next)
            setEndpoints(copy)
            setEpEditing(null)
          }}
        />
      )}
      {iaEditing !== null && (
        <InfraModal
          key={`ia-${iaEditIndex}-${iaEditing.name}`}
          value={iaEditing}
          enums={enums}
          onCancel={() => setIaEditing(null)}
          onOk={(next) => {
            const copy = [...infraAssets]
            if (iaEditIndex >= 0) copy[iaEditIndex] = next
            else copy.push(next)
            setInfraAssets(copy)
            setIaEditing(null)
          }}
        />
      )}
    </div>
  )
}

const METHOD_COLOR: Record<string, string> = {
  GET: 'green', POST: 'blue', PUT: 'orange', DELETE: 'red', PATCH: 'purple',
}

function EndpointModal({ value, onOk, onCancel, dataAssets }: {
  value: ApiEndpointRow | null
  onOk: (row: ApiEndpointRow) => void
  onCancel: () => void
  dataAssets: { id: number; name: string; classification: string }[]
}) {
  const enums = useEnums()
  const [form] = Form.useForm<ApiEndpointRow>()
  return (
    <Modal
      title="API 接口" open={value !== null} onCancel={onCancel}
      onOk={async () => onOk(await form.validateFields())}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY_EP}>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="name" label="接口名" rules={[{ required: true }]} style={{ flex: '1 1 200px' }}>
            <Input placeholder="如: 转账汇款接口" />
          </Form.Item>
          <Form.Item name="method" label="HTTP 方法" rules={[{ required: true }]} style={{ width: 110 }}>
            <Select options={(enums['http_methods'] as string[] ?? []).map((m) => ({ value: m, label: m }))} />
          </Form.Item>
        </Space>
        <Form.Item name="path" label="路径" rules={[{ required: true }]}>
          <Input placeholder="/api/v1/transfers" />
        </Form.Item>
        <Space size={24}>
          <Form.Item name="auth_required" label="需要认证" valuePropName="checked">
            <Checkbox>勾选=需认证</Checkbox>
          </Form.Item>
          <Form.Item name="public_exposed" label="公网暴露" valuePropName="checked">
            <Checkbox>可从公网访问</Checkbox>
          </Form.Item>
        </Space>
        <Form.Item name="sensitive_asset_ids" label="请求/响应包含的敏感数据资产(关联 Step4)">
          <Select
            mode="multiple"
            placeholder="选择数据资产"
            options={dataAssets.map((a) => ({ value: a.id, label: `${a.name}(${a.classification})` }))}
          />
        </Form.Item>
        <Form.Item name="rate_limit" label="限流配置"><Input placeholder="如 100 QPS/IP" /></Form.Item>
      </Form>
    </Modal>
  )
}

function InfraModal({ value, onOk, onCancel, enums }: {
  value: InfraAssetRow | null
  onOk: (row: InfraAssetRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
}) {
  const [form] = Form.useForm<InfraAssetRow>()
  return (
    <Modal
      title="基础设施资产" open={value !== null} onCancel={onCancel}
      onOk={async () => onOk(await form.validateFields())}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY_ASSET}>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="asset_type" label="资产类型" rules={[{ required: true }]} style={{ width: 180 }}>
            <Select options={optionsOf(enums, 'infra_asset_types')} />
          </Form.Item>
          <Form.Item name="env" label="环境" rules={[{ required: true }]} style={{ width: 140 }}>
            <Select options={optionsOf(enums, 'env_names')} />
          </Form.Item>
        </Space>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input placeholder="如: 核心Oracle RAC" />
        </Form.Item>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="ip" label="IP"><Input placeholder="10.x.x.x" /></Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
        </Space>
        <Form.Item name="holds_sensitive" label="是否承载敏感数据" valuePropName="checked">
          <Checkbox>承载敏感数据</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  )
}
