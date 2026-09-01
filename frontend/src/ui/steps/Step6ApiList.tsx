/* API 接口清单(独立步骤): 公网暴露/免认证接口触发专项需求;
   关联敏感数据资产的接口触发报文日志脱敏需求。本步允许为空。 */
import { useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, Form, Input, Modal, Popconfirm, Select, Space, Table,
  Tabs, Tag, Tooltip, Typography, Upload, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, ImportOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { useEnums } from '../../enums'
import type { ApiEndpointRow } from '../../types'
import GlossaryTip from '../GlossaryTip'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const EMPTY_EP: ApiEndpointRow = {
  name: '', path: '', method: 'GET', auth_required: true,
  public_exposed: false, sensitive_asset_uids: [], rate_limit: null,
}

const METHOD_COLOR: Record<string, string> = {
  GET: 'green', POST: 'blue', PUT: 'orange', DELETE: 'red', PATCH: 'purple',
}

export default function Step6ApiList({ ws, patch }: StepProps) {
  const [endpoints, setEndpoints] = useState<ApiEndpointRow[]>(ws.api_endpoints)
  const [editing, setEditing] = useState<ApiEndpointRow | null>(null)
  const [editIndex, setEditIndex] = useState(-1)
  const [importOpen, setImportOpen] = useState(false)
  const savedRef = useRef(JSON.stringify(endpoints))

  // 关联按资产 uid 取值(#66), 跨整卷保存稳定
  const assetNameByUid = new Map(ws.data_assets.map((a) => [a.uid as string, a.name]))

  const save = async (): Promise<boolean> => {
    try {
      const saved = await api.saveApiEndpoints(ws.project.id, endpoints)
      patch({ api_endpoints: saved })
      savedRef.current = JSON.stringify(endpoints)
      message.success(`已保存 ${saved.length} 个接口`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({
    save,
    isDirty: () => JSON.stringify(endpoints) !== savedRef.current,
  })

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        登记系统对外提供的 API 接口。公网暴露、免认证(
        <GlossaryTip term="anonymous_api">匿名</GlossaryTip>)的接口会触发专项安全评估需求;
        关联敏感数据资产的接口会触发报文日志脱敏需求。基础设施资产在下一步登记。
      </Typography.Text>

      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />}
          onClick={() => { setEditIndex(-1); setEditing({ ...EMPTY_EP }) }}>新增接口</Button>
        <Button size="small" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
          批量导入(粘贴文本/表格)
        </Button>
        <Typography.Text type="secondary">共 {endpoints.length} 个(允许为空)</Typography.Text>
      </Space>
      <Table<ApiEndpointRow>
        rowKey={(_, i) => String(i)}
        dataSource={endpoints}
        pagination={false}
        size="small"
        columns={[
          { title: '接口名', dataIndex: 'name' },
          { title: '路径', dataIndex: 'path', render: (v) => <code>{v}</code> },
          { title: '方法', dataIndex: 'method', width: 80, render: (m) => <Tag color={METHOD_COLOR[m] ?? 'default'}>{m}</Tag> },
          { title: '需认证', dataIndex: 'auth_required', width: 90,
            render: (v) => (v ? '是' : (
              <Tooltip title={<GlossaryTip term="anonymous_api" />}>
                <Tag color="red">匿名!</Tag>
              </Tooltip>
            )) },
          { title: '公网暴露', dataIndex: 'public_exposed', width: 90,
            render: (v) => (v ? <Tag color="orange">是</Tag> : '否') },
          { title: '关联敏感数据资产', dataIndex: 'sensitive_asset_uids',
            render: (uids: string[]) => uids.map((u) => assetNameByUid.get(u))
              .filter(Boolean).map((n) => <Tag key={n as string} color="purple">{n}</Tag>) },
          { title: '限流配置', dataIndex: 'rate_limit', render: (v) => v || '—' },
          {
            title: '操作', width: 110,
            render: (_v, _r, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { setEditIndex(index); setEditing({ ...endpoints[index] }) }} />
                <Popconfirm title="删除该接口?" onConfirm={() => setEndpoints(endpoints.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      {importOpen && (
        <ApiImportModal
          projectId={ws.project.id}
          existing={endpoints}
          onClose={() => setImportOpen(false)}
          onImport={(rows, added, skippedDup) => {
            setEndpoints([...endpoints, ...rows])
            setImportOpen(false)
            message.success(`已导入 ${added} 条${skippedDup ? `, 按路径+方法去重跳过 ${skippedDup} 条` : ''}, 请补全关联资产与限流后保存`)
          }}
        />
      )}
      {editing !== null && (
        <EndpointModal
          key={`ep-${editIndex}-${editing.name}`}
          value={editing}
          dataAssets={ws.data_assets.map((a) => ({ uid: a.uid as string, name: a.name, classification: a.classification }))}
          onCancel={() => setEditing(null)}
          onOk={(next) => {
            const copy = [...endpoints]
            if (editIndex >= 0) copy[editIndex] = next
            else copy.push(next)
            setEndpoints(copy)
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

function EndpointModal({ value, onOk, onCancel, dataAssets }: {
  value: ApiEndpointRow | null
  onOk: (row: ApiEndpointRow) => void
  onCancel: () => void
  dataAssets: { uid: string; name: string; classification: string }[]
}) {
  const enums = useEnums()
  const [form] = Form.useForm<ApiEndpointRow>()
  return (
    <Modal
      title="API 接口" open={value !== null} onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => { /* 校验失败, 留在弹窗 */ })}
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
        <Form.Item
          name="sensitive_asset_uids"
          label={dataAssets.length ? '请求/响应包含的敏感数据资产(关联数据字典)' : '请求/响应包含的敏感数据资产'}
          extra={dataAssets.length ? undefined : '数据字典尚未录入资产, 可先完成数据字典再回来关联'}
        >
          <Select
            mode="multiple"
            placeholder={dataAssets.length ? '选择数据资产' : '无可选资产(数据字典为空)'}
            disabled={!dataAssets.length}
            options={dataAssets.map((a) => ({ value: a.uid, label: `${a.name}(${a.classification})` }))}
          />
        </Form.Item>
        <Form.Item name="rate_limit" label="限流配置">
          <Input placeholder="如 100 QPS/IP" />
        </Form.Item>
      </Form>
    </Modal>
  )
}


/** 批量导入弹窗(#92): 粘贴文本/上传表格 → 解析预览(非法行标红) → 确认合并(按路径+方法去重)。 */
function ApiImportModal({ projectId, existing, onClose, onImport }: {
  projectId: number
  existing: ApiEndpointRow[]
  onClose: () => void
  onImport: (rows: ApiEndpointRow[], added: number, skippedDup: number) => void
}) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [parsing, setParsing] = useState(false)
  const [preview, setPreview] = useState<{ index: number; name: string; method: string; path: string; auth_required: boolean; public_exposed: boolean; error?: string | null }[] | null>(null)

  const doParse = async () => {
    setParsing(true)
    setPreview(null)
    try {
      const res = file
        ? await api.parseApiEndpointsFile(projectId, file)
        : await api.parseApiEndpoints(projectId, { text })
      if (!res.rows.length) { message.warning('未解析出任何行'); return }
      setPreview(res.rows)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setParsing(false)
    }
  }

  const doImport = () => {
    if (!preview) return
    const valid = preview.filter((r) => !r.error)
    const existingKeys = new Set(existing.map((e) => `${e.method.toUpperCase()} ${e.path}`))
    const seen = new Set<string>()
    const merged: ApiEndpointRow[] = []
    let skippedDup = 0
    for (const r of valid) {
      const key = `${r.method.toUpperCase()} ${r.path}`
      if (existingKeys.has(key) || seen.has(key)) { skippedDup += 1; continue }
      seen.add(key)
      merged.push({
        name: r.name, path: r.path, method: r.method,
        auth_required: r.auth_required, public_exposed: r.public_exposed,
        sensitive_asset_ids: [], sensitive_asset_uids: [], rate_limit: null,
      })
    }
    onImport(merged, merged.length, skippedDup)
  }

  const invalidCount = preview?.filter((r) => r.error).length ?? 0

  return (
    <Modal
      title="批量导入 API 接口" open width={860} onCancel={onClose}
      okText="确认导入" okButtonProps={{ disabled: !preview || preview.every((r) => r.error) }}
      onOk={doImport}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="每行一条: 名称,方法,路径,需要认证,公网暴露"
        description="方法用 GET/POST/PUT/DELETE/PATCH 等; 后两列容错 是/否/true/false/1/0, 缺省为 需要认证=是、公网暴露=否。xlsx/csv 需含表头(名称/方法/路径/需要认证/公网暴露); 关联资产与限流请在导入后逐条补填。"
      />
      <Tabs
        defaultActiveKey="text"
        items={[
          {
            key: 'text', label: '粘贴文本',
            children: (
              <Input.TextArea
                rows={7} value={text} onChange={(e) => setText(e.target.value)}
                placeholder={'转账汇款接口,POST,/api/v1/transfers,是,是\n外汇牌价查询,GET,/api/v1/rates'}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
              />
            ),
          },
          {
            key: 'file', label: '上传 xlsx/csv',
            children: (
              <Upload
                accept=".xlsx,.csv,.txt" maxCount={1}
                beforeUpload={(f) => { setFile(f); setPreview(null); return false }}
                onRemove={() => setFile(null)}
                fileList={file ? [file as never] : []}
              >
                <Button icon={<ImportOutlined />}>选择文件(xlsx/csv/txt)</Button>
              </Upload>
            ),
          },
        ]}
      />
      <Button type="primary" loading={parsing} disabled={!text.trim() && !file}
        onClick={() => void doParse()} style={{ margin: '12px 0' }}>
        解析预览
      </Button>
      {preview && (
        <>
          {invalidCount > 0 && (
            <Alert type="warning" showIcon style={{ marginBottom: 8 }}
              message={`${invalidCount} 行校验失败(标红), 将被跳过; 合法行不受影响`} />
          )}
          <Table
            rowKey={(r) => String(r.index)}
            dataSource={preview} size="small" pagination={false}
            rowClassName={(r) => (r.error ? 'row-obsolete' : '')}
            columns={[
              { title: '行', dataIndex: 'index', width: 50 },
              { title: '名称', dataIndex: 'name' },
              { title: '方法', dataIndex: 'method', width: 80 },
              { title: '路径', dataIndex: 'path', render: (v) => <code>{v}</code> },
              { title: '需认证', dataIndex: 'auth_required', width: 70, render: (v) => (v ? '是' : '否') },
              { title: '公网', dataIndex: 'public_exposed', width: 60, render: (v) => (v ? '是' : '否') },
              { title: '校验', dataIndex: 'error', render: (e) => e
                ? <Typography.Text type="danger" style={{ fontSize: 12 }}>{e}</Typography.Text>
                : <Tag color="green">通过</Tag> },
            ]}
          />
        </>
      )}
    </Modal>
  )
}
