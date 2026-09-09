/* 系统清单(#280 新布局): PageHeader + 筛选卡 + 表格卡。系统 × 所属备案/定级 × 最新评估;
   清单是"看系统"的主入口: 同一系统多次评估在系统详情页形成时间线;
   备案的维护入口在 平台设置 → 备案管理(安全侧权威维护 #192)。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Divider, Empty, Form, Input, Modal, Popconfirm, Row, Select, Space,
  Switch, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import { InfoCircleOutlined, PlusOutlined } from '@ant-design/icons'

/** 重要程度标签色(DESIGN 系统清单字段, #283)。 */
const IMPORTANCE_COLOR: Record<string, string> = { 高: 'volcano', 中: 'gold', 低: 'default' }
const IMPORTANCE_LEVELS = ['高', '中', '低']
import type { ColumnsType } from 'antd/es/table'

import { api } from '../api'
import { labelMapOf, optionsOf, useEnums } from '../enums'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import { LevelTag, RoundCell } from './tags'
import type { FilingRow, SystemRow } from '../types'

export default function SystemsPage() {
  const enums = useEnums()
  const [rows, setRows] = useState<SystemRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filings, setFilings] = useState<FilingRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Partial<SystemRow> | null>(null)
  // 筛选: 关键词(名称/编号) + 备案 + 重要程度 + 标签(#283); 服务端过滤分页(item9)
  const [kwInput, setKwInput] = useState('')
  const [kw, setKw] = useState('')
  const [filingId, setFilingId] = useState<number | null>(null)
  const [importance, setImportance] = useState<string | undefined>()
  const [tagFilter, setTagFilter] = useState<string | undefined>()

  const reload = useCallback(() => {
    setLoading(true)
    api.systemLedgerPaged({
      page, pageSize, keyword: kw, filingId, importance, tag: tagFilter,
    })
      .then((r) => { setRows(r.items); setTotal(r.total) })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [page, pageSize, kw, filingId, importance, tagFilter])
  useEffect(reload, [reload])
  useEffect(() => { api.listFilings().then(setFilings).catch(() => undefined) }, [])

  const resetPage = (apply: () => void) => { apply(); setPage(1) }
  const list = rows

  const typeLabels = labelMapOf(enums, 'project_types')

  const columns: ColumnsType<SystemRow> = [
    {
      title: '系统名称 / 编号', dataIndex: 'name', width: 240, fixed: 'left',
      render: (v: string, r) => (
        <div>
          <Typography.Link onClick={() => navigate(`/systems/${r.id}`)}>{v}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>{r.code || '—'}</Typography.Text>
        </div>
      ),
    },
    {
      title: '所属备案 / 定级', dataIndex: 'filing_name', width: 220,
      render: (v: string | null, r) => (
        <Space size={6} wrap>
          {v ?? <Typography.Text type="secondary">未挂备案</Typography.Text>}
          <LevelTag level={r.filing_level} />
        </Space>
      ),
    },
    { title: '归属部门', dataIndex: 'department', width: 120, render: (v: string | null) => v || '—' },
    { title: '重要程度', dataIndex: 'importance', width: 90,
      render: (v: string | null) => (v ? <Tag color={IMPORTANCE_COLOR[v] ?? 'default'}>{v}</Tag> : '—') },
    {
      title: '责任人(开发/运维/业务)', dataIndex: 'owner_dev_name', width: 160,
      render: (_: unknown, r) => (
        <div style={{ fontSize: 12, lineHeight: 1.7 }}>
          <div>开发: {r.owner_dev_name || '—'}</div>
          <div>运维: {r.owner_ops_name || '—'}</div>
          <div>业务: {r.owner_biz_name || '—'}</div>
        </div>
      ),
    },
    { title: '系统类型', dataIndex: 'types', width: 150,
      render: (v: string[] | undefined) => (v ?? []).map((t) => typeLabels[t] ?? t).join('、') || '—' },
    { title: '标签', dataIndex: 'tags', width: 170,
      render: (v: string[] | undefined, r) => (v ?? []).length
        ? <Space size={4} wrap>{(r.tags ?? []).map((t) => <Tag key={t} color="blue" style={{ marginRight: 0 }}>{t}</Tag>)}</Space>
        : '—' },
    { title: '最新评估', dataIndex: 'latest_round', width: 330, render: (_: unknown, r) => <RoundCell round={r.latest_round} /> },
    {
      title: '操作', key: 'ops', width: 200, fixed: 'right',
      render: (_: unknown, record) => (
        <Space size={0} split={<Divider type="vertical" />}>
          <Button type="link" size="small" onClick={() => navigate(`/systems/${record.id}`)}>详情</Button>
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
        description="登记在册的系统资产, 作为安全评估的对象; 一个系统对应多轮评估"
        extra={(
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ user_scale: '1k_to_100k', types: [], tags: [], is_public: false })}>
            新建系统
          </Button>
        )}
      />
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input.Search
            allowClear placeholder="名称 / 编号(回车查询)" style={{ width: 220 }}
            value={kwInput}
            onChange={(e) => {
              setKwInput(e.target.value)
              if (!e.target.value) resetPage(() => setKw(''))
            }}
            onSearch={(v) => resetPage(() => setKw(v.trim()))}
          />
          <Select
            allowClear placeholder="所属备案" style={{ width: 200 }}
            value={filingId ?? undefined}
            options={filings.map((f) => ({ value: f.id, label: f.name }))}
            onChange={(v) => resetPage(() => setFilingId(v ?? null))}
          />
          <Select
            allowClear placeholder="重要程度" style={{ width: 120 }}
            value={importance}
            options={IMPORTANCE_LEVELS.map((v) => ({ value: v, label: v }))}
            onChange={(v) => resetPage(() => setImportance(v))}
          />
          <Select
            allowClear placeholder="标签" style={{ width: 160 }}
            value={tagFilter}
            options={(enums['system_tags'] as string[] | undefined ?? []).map((v) => ({ value: v, label: v }))}
            onChange={(v) => resetPage(() => setTagFilter(v))}
          />
          <Typography.Text type="secondary">共 {list.length} 个系统</Typography.Text>
        </Space>
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <Table<SystemRow>
          rowKey="id"
          loading={loading}
          dataSource={list}
          pagination={{
            current: page, pageSize, total,
            showSizeChanger: true, pageSizeOptions: [10, 20, 50],
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          scroll={{ x: 1700 }}
          locale={{ emptyText: (
            <Empty description="还没有系统登记">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ user_scale: '1k_to_100k', types: [], tags: [], is_public: false })}>新建系统</Button>
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
  const tip = (text: string, tip: string) => (
    <span>
      {text}{' '}
      <Tooltip title={tip}>
        <InfoCircleOutlined style={{ color: '#bfbfbf', fontSize: 12 }} />
      </Tooltip>
    </span>
  )
  return (
    <Modal
      title={isEdit ? '编辑系统' : '新建系统'}
      width={720}
      centered
      open
      onCancel={onClose}
      onOk={() => form.validateFields()
        .then(async (v) => {
          try {
            if (isEdit && value.id != null) await api.updateSystem(value.id, v)
            else await api.createSystem(v)
            message.success('已保存')
            onSaved()
          } catch (e) {
            message.error((e as Error).message)
          }
        })
        .catch(() => { /* 校验失败留在弹窗 */ })}
    >
      {/* #295: 紧凑两列栅格 + extra 收进 label Tooltip, 全表单一屏填完不滚动 */}
      <Form form={form} layout="vertical" initialValues={value} style={{ marginBottom: -8 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="name" label="系统名称" rules={[{ required: true, message: '请输入系统名称' }]}>
              <Input placeholder="如: 个人网银系统" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="code" label="系统编号">
              <Input placeholder="内部台账编号, 选填" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="department" label="归属部门">
              <Input placeholder="选填, 如: 个人金融部" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="importance" label="重要程度">
              <Select allowClear placeholder="选择重要程度" options={IMPORTANCE_LEVELS.map((v) => ({ value: v, label: v }))} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="user_scale" label="用户规模" rules={[{ required: true, message: '请选择' }]}>
              <Select options={optionsOf(enums, 'user_scales')} placeholder="选择规模" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item
              name="filing_id" label={tip('挂靠定级备案', '挂靠后系统继承备案定级; 备案在 平台设置 → 备案管理 维护, 暂无合适项可先跳过')}
            >
              <Select
                allowClear placeholder="选择备案(选填)"
                options={filings.map((f) => ({
                  value: f.id, label: `${f.name}(${f.code ? `${f.code} / ` : ''}等保${f.level})`,
                }))}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="owner_dev_name" label="开发侧责任人">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="owner_ops_name" label="运维侧责任人">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="owner_biz_name" label="业务侧责任人">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="types" label={tip('业务类型(可多选)', '一个系统可能同时包含多种形态, 如 App + 后台管理; 驱动移动应用类安全需求')}
            >
              <Select mode="multiple" options={optionsOf(enums, 'project_types')} placeholder="选择全部适用类型" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="compliance_targets" label={tip('合规目标(可多选)', '评估向导按此生成对应合规要求(知识库触发条件); 单次评估不改, 在系统侧统一维护(#319)')}
            >
              <Select mode="multiple" options={optionsOf(enums, 'compliance_targets')} placeholder="如 等级保护 / 个人信息保护法" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="tags" label={tip('标签(可多选/自定义)', '标签字典在 平台设置 → 系统设置 维护; 直接输入可临时自定义')}
            >
              <Select
                mode="tags" placeholder="如 重要信息系统 / 人行上报"
                options={(enums['system_tags'] as string[] | undefined ?? []).map((v) => ({ value: v, label: v }))}
              />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="is_public" label="是否涉及公网访问" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Switch checkedChildren="是" unCheckedChildren="否" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
