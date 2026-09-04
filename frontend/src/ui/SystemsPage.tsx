/* 系统台账: 系统视角(系统 × 所属备案 × 最新评估) + 备案视角(备案 × 定级 × 下挂系统)。
   台账是"看系统"的主入口: 同一系统多次评估在系统详情页形成时间线, 避免项目列表平行记录。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Tabs, Tag,
  Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api } from '../api'
import { navigate } from '../router'
import NetboxSystemImportModal from './NetboxSystemImportModal'
import type { FilingRow, NetboxSystemRow, RoundSummary, SystemRow } from '../types'

const LEVEL_COLORS: Record<string, string> = { 一级: 'blue', 二级: 'gold', 三级: 'red' }

function LevelTag({ level }: { level?: string | null }) {
  if (!level) return <Tag>未备案</Tag>
  return <Tag color={LEVEL_COLORS[level] ?? 'default'}>等保{level}</Tag>
}

function RoundCell({ round }: { round?: RoundSummary | null }) {
  if (!round) return <Typography.Text type="secondary">暂无已生成评估</Typography.Text>
  return (
    <Space size={6} wrap>
      <Typography.Text copyable={{ text: round.project_code }} style={{ fontSize: 13 }}>
        {round.project_code}
      </Typography.Text>
      {round.status === 'generated'
        ? <Tag color="green">已生成</Tag>
        : <Tag color="orange">草稿</Tag>}
      {round.grading_level && <Tag color="blue">{round.grading_level}</Tag>}
      <Typography.Text type="secondary">
        需求 {round.requirements_total} 条 / 未闭环 {round.requirements_open}
      </Typography.Text>
    </Space>
  )
}

export default function SystemsPage() {
  return (
    <div style={{ padding: 24 }}>
      <Card title="系统台账" variant="borderless">
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          一个系统对应多次评估(项目): 系统详情页查看评估时间线与当前基线;
          对外备案按"定级备案"维护, 实际系统以备案子系统形式挂靠并继承其定级。
        </Typography.Text>
        <Tabs
          defaultActiveKey="systems"
          items={[
            { key: 'systems', label: '系统视角', children: <SystemsTab /> },
            { key: 'filings', label: '定级备案', children: <FilingsTab /> },
          ]}
        />
      </Card>
    </div>
  )
}

/* ── 系统视角 ─────────────────────────────────────── */

function SystemsTab() {
  const [rows, setRows] = useState<SystemRow[]>([])
  const [loading, setLoading] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [pushing, setPushing] = useState<number | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.systemLedger()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  /** 导入所选(#154): 按名称/netbox_object_id 查重后逐个登记, 重复行跳过 */
  const handleImported = async (selected: NetboxSystemRow[]) => {
    let created = 0
    const failures: string[] = []
    for (const row of selected) {
      const refId = String(row.id)
      const dup = rows.some((r) => r.netbox_object_id === refId
        || r.name.toLowerCase() === (row.name || '').toLowerCase())
      if (dup) { continue }
      try {
        await api.createSystem({
          name: row.name || `NetBox#${row.id}`,
          code: row.code ?? undefined,
          owner_name: row.owner ?? undefined,
          netbox_object_id: refId,
        })
        created += 1
      } catch (e) {
        failures.push(`${row.name || refId}: ${(e as Error).message}`)
      }
    }
    setImportOpen(false)
    message.success(`已导入 ${created} 个系统${failures.length ? `; ${failures.length} 个失败` : ''}`)
    if (failures.length) Modal.info({
      title: '导入失败明细', width: 560,
      content: failures.map((f, i) => <div key={i} style={{ fontSize: 12 }}>{f}</div>),
    })
    reload()
  }

  /** 推送到 NetBox(#154): 仅未关联行; 失败不回滚可重试 */
  const handlePush = async (record: SystemRow) => {
    setPushing(record.id)
    try {
      const res = await api.pushNetboxSystem({
        system_id: record.id, name: record.name,
        code: record.code ?? undefined, owner: record.owner_name ?? undefined,
      })
      message.success(`已推送到 NetBox${res.url ? ', 可点击名称旁徽标查看' : ''}`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setPushing(null)
    }
  }

  /** 外链地址: 台账页挂载时拉一次 base_url(未配置静默) */
  const [nbBaseUrl, setNbBaseUrl] = useState<string | undefined>(undefined)
  useEffect(() => {
    api.getNetboxStatus()
      .then((s) => { if (s.configured) setNbBaseUrl(s.base_url) })
      .catch(() => undefined)
  }, [])

  const columns = [
    { title: '系统名称', dataIndex: 'name',
      render: (v: string, record: SystemRow) => {
        const link = nbBaseUrl && record.netbox_object_id
          ? `${nbBaseUrl}/api/plugins/custom-objects/object-types/system/objects/${record.netbox_object_id}`
          : undefined
        return (
          <Space size={6}>
            <span>{v}</span>
            {record.netbox_object_id && (
              <Tag color="blue" style={{ marginRight: 0 }}>
                {link ? <a href={link} target="_blank" rel="noreferrer">NetBox</a> : 'NetBox'}
              </Tag>
            )}
          </Space>
        )
      } },
    { title: '系统编号', dataIndex: 'code', width: 140, render: (v: string | null) => v || '—' },
    {
      title: '所属备案 / 定级', dataIndex: 'filing_name', width: 220,
      render: (v: string | null, record: SystemRow) => (
        <Space size={6} wrap>
          {v ? <Typography.Text>{v}</Typography.Text> : <Typography.Text type="secondary">未挂备案</Typography.Text>}
          <LevelTag level={record.filing_level} />
        </Space>
      ),
    },
    { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v: string | null) => v || '—' },
    { title: '最新评估', dataIndex: 'latest_round', width: 330, render: (_: unknown, r: SystemRow) => <RoundCell round={r.latest_round} /> },
    {
      title: '操作', width: 220,
      render: (_: unknown, record: SystemRow) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/system/${record.id}`)}>评估时间线</Button>
          {!record.netbox_object_id && (
            <Button
              size="small" loading={pushing === record.id}
              onClick={() => void handlePush(record)}
            >
              推送到 NetBox
            </Button>
          )}
          <Popconfirm
            title="删除该系统?"
            description="仅当下挂项目已清空才可删除"
            onConfirm={async () => {
              try {
                await api.deleteSystem(record.id)
                message.success('已删除')
                reload()
              } catch (e) {
                message.error((e as Error).message)
              }
            }}
          >
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<PlusOutlined />} type="primary" onClick={() => setImportOpen(true)}>
          从 NetBox 导入
        </Button>
        <Typography.Text type="secondary">
          NetBox 是旁路增强: 未配置或断连时, 系统登记与建项流程完全不受影响
        </Typography.Text>
      </Space>
      <Table<SystemRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 15 }}
        locale={{ emptyText: <Empty description="还没有系统登记" /> }}
        columns={columns}
      />
      <NetboxSystemImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSelected={(sel) => void handleImported(sel)}
      />
    </>
  )
}

/* ── 备案视角 ─────────────────────────────────────── */

function FilingsTab() {
  const [rows, setRows] = useState<FilingRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Partial<FilingRow> | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.listFilings()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ level: '二级' })}>
          新增备案
        </Button>
        <Typography.Text type="secondary">
          备案是对外备案测评的少数主体, 定级在此登记; 系统挂靠备案后自动继承定级
        </Typography.Text>
      </Space>
      <Table<FilingRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: <Empty description="还没有备案登记" /> }}
        columns={[
          { title: '备案名称', dataIndex: 'name' },
          { title: '备案编号', dataIndex: 'code', width: 160, render: (v: string | null) => v || '—' },
          { title: '定级', dataIndex: 'level', width: 110, render: (v: string) => <LevelTag level={v} /> },
          { title: '下挂系统数', dataIndex: 'system_count', width: 110 },
          { title: '备注', dataIndex: 'note', ellipsis: true, render: (v: string | null) => v || '—' },
          { title: '最新评估', dataIndex: 'latest_round', width: 300, render: (_: unknown, r: FilingRow) => <RoundCell round={r.latest_round} /> },
          {
            title: '操作', width: 150,
            render: (_: unknown, record: FilingRow) => (
              <Space>
                <Button size="small" onClick={() => setEditing(record)}>编辑</Button>
                <Popconfirm
                  title="删除该备案?"
                  description="下挂系统需先解除关联"
                  onConfirm={async () => {
                    try {
                      await api.deleteFiling(record.id)
                      message.success('已删除')
                      reload()
                    } catch (e) {
                      message.error((e as Error).message)
                    }
                  }}
                >
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      {editing !== null && (
        <FilingModal
          value={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </>
  )
}

function FilingModal({ value, onSaved, onClose }: {
  value: Partial<FilingRow>
  onSaved: () => void
  onClose: () => void
}) {
  const [form] = Form.useForm<Partial<FilingRow>>()
  const isEdit = value.id !== undefined
  return (
    <Modal
      title={isEdit ? '编辑备案' : '新增备案'}
      open
      onCancel={onClose}
      onOk={() => form.validateFields()
        .then(async (v) => {
          try {
            if (isEdit) await api.updateFiling(value.id!, v)
            else await api.createFiling(v)
            message.success('已保存')
            onSaved()
          } catch (e) {
            message.error((e as Error).message)
          }
        })
        .catch(() => { /* 校验失败留在弹窗 */ })}
    >
      <Form form={form} layout="vertical" initialValues={value}>
        <Form.Item name="name" label="备案名称" rules={[{ required: true, message: '请输入备案名称' }]}>
          <Input placeholder="如: 个人网银系统(等保三级备案)" />
        </Form.Item>
        <Form.Item name="code" label="备案编号">
          <Input placeholder="备案证明上的编号, 选填" />
        </Form.Item>
        <Form.Item name="level" label="备案定级" rules={[{ required: true, message: '请选择定级' }]}>
          <Select options={['一级', '二级', '三级'].map((l) => ({ value: l, label: `等保${l}` }))} />
        </Form.Item>
        <Form.Item name="note" label="备注">
          <Input.TextArea rows={2} placeholder="如: 备案日期 / 测评机构 / 测评有效期" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export { LevelTag, RoundCell }
