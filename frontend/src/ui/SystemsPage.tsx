/* 系统清单(#270, 原「系统台账」): 系统 × 所属备案/定级 × 最新评估。
   清单是"看系统"的主入口: 同一系统多次评估在系统详情页形成时间线;
   定级备案的管理已上收系统管理(安全侧权威维护 #192), 本页只在系统行上展示备案与定级。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Divider, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table,
  Tag, Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api } from '../api'
import { optionsOf, useEnums } from '../enums'
import { GRADING_LEVEL_COLOR } from './tokens'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import type { FilingRow, RoundSummary, SystemRow } from '../types'

export function LevelTag({ level }: { level?: string | null }) {
  if (!level) return <Tag>未备案</Tag>
  return <Tag color={GRADING_LEVEL_COLOR[level] ?? 'default'}>等保{level}</Tag>
}

export function RoundCell({ round }: { round?: RoundSummary | null }) {
  if (!round) return <Typography.Text type="secondary">暂无已生成评估</Typography.Text>
  return (
    <Space size={6} wrap>
      <Typography.Text copyable={{ text: round.project_code }} style={{ fontSize: 13 }}>
        {round.project_code}
      </Typography.Text>
      {round.status === 'generated'
        ? <Tag color="green">已生成</Tag>
        : <Tag color="orange">草稿</Tag>}
      {round.grading_level && <Tag color={GRADING_LEVEL_COLOR[round.grading_level] ?? 'default'}>{round.grading_level}</Tag>}
      <Typography.Text type="secondary">
        需求 {round.requirements_total} 条 / 未闭环 {round.requirements_open}
      </Typography.Text>
    </Space>
  )
}

export default function SystemsPage() {
  const enums = useEnums()
  const [rows, setRows] = useState<SystemRow[]>([])
  const [filings, setFilings] = useState<FilingRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Partial<SystemRow> | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.systemLedger()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])
  useEffect(() => { api.listFilings().then(setFilings).catch(() => undefined) }, [])

  const columns = [
    { title: '系统名称', dataIndex: 'name',
      // 最小宽度防竖排(#235 走查): 名称列过窄时中文逐字换行不可读
      onCell: () => ({ style: { whiteSpace: 'nowrap' as const } }),
      render: (v: string) => v,
    },
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
      title: '操作', width: 250,
      render: (_: unknown, record: SystemRow) => (
        <Space size={0} split={<Divider type="vertical" />}>
          <Button type="link" size="small" onClick={() => navigate(`/system/${record.id}`)}>系统详情</Button>
          <Button type="link" size="small" onClick={() => setEditing(record)}>编辑</Button>
          <Popconfirm
            title="删除该系统?"
            description="仅当下挂评估已清空才可删除"
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
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="系统清单"
        description={
          '一个系统对应多轮评估: 详情页查看评估时间线与当前基线; ' +
          '系统挂靠定级备案后评估自动继承定级, 备案管理在 系统管理 → 定级备案 维护。'
        }
        extra={(
          <>
            <Button
              icon={<PlusOutlined />} type="primary"
              onClick={() => setEditing({ user_scale: '1k_to_100k', types: [], is_public: false })}
            >
              新建系统
            </Button>
          </>
        )}
      />
      <Card variant="borderless">
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          规模/类型/公网等基本信息在系统上维护; 备案管理已上收 系统管理 → 定级备案(安全角色)
        </Typography.Text>
        <Table<SystemRow>
          rowKey="id"
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
          scroll={{ x: 1100 }}
          locale={{ emptyText: (
            <Empty description="还没有系统登记">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ user_scale: '1k_to_100k', types: [], is_public: false })}>新建系统</Button>
            </Empty>
) }}
          columns={columns}
        />
      </Card>
      {editing !== null && (
        <SystemFormModal
          value={editing}
          filings={filings}
          enums={enums}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </div>
  )
}

/** 系统新建/编辑表单(#194): 身份 + 挂靠备案 + 基本信息(规模/类型/公网)。 */
export function SystemFormModal({ value, filings, enums, onSaved, onClose }: {
  value: Partial<SystemRow>
  filings: FilingRow[]
  enums: ReturnType<typeof useEnums>
  onSaved: () => void
  onClose: () => void
}) {
  const [form] = Form.useForm<Partial<SystemRow>>()
  const isEdit = value.id !== undefined
  return (
    <Modal
      title={isEdit ? '编辑系统' : '新建系统'}
      open
      onCancel={onClose}
      onOk={() => form.validateFields()
        .then(async (v) => {
          try {
            if (isEdit) await api.updateSystem(value.id!, v)
            else await api.createSystem(v)
            message.success('已保存')
            onSaved()
          } catch (e) {
            message.error((e as Error).message)
          }
        })
        .catch(() => { /* 校验失败留在弹窗 */ })}
    >
      <Form form={form} layout="vertical" initialValues={value}>
        <Form.Item name="name" label="系统名称" rules={[{ required: true, message: '请输入系统名称' }]}>
          <Input placeholder="如: 个人网银系统" />
        </Form.Item>
        <Form.Item name="code" label="系统编号">
          <Input placeholder="内部台账编号, 选填" />
        </Form.Item>
        <Form.Item
          name="filing_id" label="挂靠定级备案"
          extra="挂靠后系统继承备案定级; 备案由安全管理员在 系统管理 → 定级备案 维护, 暂无合适项可先跳过"
        >
          <Select
            allowClear placeholder="选择备案(选填)"
            options={filings.map((f) => ({
              value: f.id, label: `${f.name}(${f.code ? `${f.code} / ` : ''}等保${f.level})`,
            }))}
          />
        </Form.Item>
        <Form.Item name="owner_name" label="系统负责人">
          <Input placeholder="选填" />
        </Form.Item>
        <Form.Item name="user_scale" label="用户规模" rules={[{ required: true, message: '请选择' }]}>
          <Select options={optionsOf(enums, 'user_scales')} placeholder="选择规模" />
        </Form.Item>
        <Form.Item
          name="types" label="业务类型(可多选)"
          extra="一个系统可能同时包含多种形态, 如 App + 后台管理; 驱动移动应用类安全需求"
        >
          <Select mode="multiple" options={optionsOf(enums, 'project_types')} placeholder="选择全部适用类型" />
        </Form.Item>
        <Form.Item name="is_public" label="是否涉及公网访问" valuePropName="checked">
          <Switch checkedChildren="是" unCheckedChildren="否" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
