/* 评估清单(#280 新布局): PageHeader + 筛选卡 + 表格卡; 全部项目表格(按角色过滤)。
   新建弹窗强制先选系统(可按上一轮复制, #195); 业务逻辑与角色可见性不变。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Divider, Empty, Modal, Popconfirm, Radio, Select, Space, Table, Tag,
  Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { api, getStoredUser, isFullVisibilityRole } from '../api'
import { HEX } from './tokens'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import { clearWizardStepStorage } from './WizardPage'
import { GateStatusTag, LevelTag, ProjectStatusTag } from './tags'
import type { ProjectDetail, RoundSummary, SystemRow } from '../types'

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [systems, setSystems] = useState<SystemRow[]>([])
  const [systemFilter, setSystemFilter] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  // 新建弹窗(#195): 必选系统 → 有上一轮默认复制, 可切换空白; 支持跳转新建系统
  const [createOpen, setCreateOpen] = useState(false)
  const [createMode, setCreateMode] = useState<'blank' | 'copy'>('copy')
  const [createSystemId, setCreateSystemId] = useState<number | undefined>()
  const isFullView = isFullVisibilityRole(getStoredUser()?.role)

  // 清单改服务端过滤分页(#283 item9): 筛选/翻页即时下推查询
  const loadProjects = useCallback(() => {
    setLoading(true)
    api.listProjectsPaged({ page, pageSize, systemId: systemFilter, status: statusFilter })
      .then((r) => { setProjects(r.items); setTotal(r.total) })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [page, pageSize, systemFilter, statusFilter])
  useEffect(loadProjects, [loadProjects])

  const reload = useCallback(() => {
    api.listSystems().then(setSystems).catch(() => undefined)
    loadProjects()
  }, [loadProjects])
  useEffect(reload, [reload])

  const resetPage = (apply: () => void) => { apply(); setPage(1) }

  /** 单入口「进入」(#308): 未提交→填写页; 已生成未评审→产物页; 已进评审→评审页。 */
  const entryPath = (r: ProjectDetail): string => {
    if (r.status === 'draft') return `/evaluations/${r.id}/wizard`
    const gate = r.review_gate_status
    if (gate && gate !== 'pending') return `/evaluations/${r.id}/review`
    return `/evaluations/${r.id}/result`
  }

  const copySystem = systems.find((s) => s.id === createSystemId)
  const latestRound: RoundSummary | undefined =
    copySystem?.latest_round ?? copySystem?.rounds?.[0]

  /** 新建(#195): 必选系统; 有上一轮时默认整卷继承(#151 复制链路)。 */
  const handleCreate = async () => {
    if (!createSystemId) {
      message.warning('请先选择所属系统')
      return
    }
    const from = createMode === 'copy' ? latestRound?.project_id : undefined
    if (createMode === 'copy' && !from) {
      message.warning('该系统还没有可复制的历史评估, 请切换为空白新建')
      return
    }
    setCreating(true)
    try {
      const detail = await api.createProject({
        name: '未命名评估', system_id: createSystemId, from_project_id: from,
      })
      message.success(from
        ? '已按上一轮评估创建新一轮, 请在向导中核对并修改变化部分'
        : '已创建, 请在第一步补全评估信息')
      setCreateOpen(false)
      navigate(`/evaluations/${detail.id}/wizard`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setCreating(false)
    }
  }

  const openCreate = () => {
    setCreateMode('copy')
    setCreateSystemId(undefined)
    setCreateOpen(true)
  }

  const columns: ColumnsType<ProjectDetail> = [
    {
      title: '评估名称 / 编码', dataIndex: 'name', width: 250, fixed: 'left',
      render: (v: string, r) => (
        <div>
          <Typography.Link onClick={() => navigate(entryPath(r))}>{v}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>{r.code}</Typography.Text>
        </div>
      ),
    },
    {
      title: '所属系统', dataIndex: 'system_name', width: 150, ellipsis: true,
      render: (v: string | null, r) => v
        ? <a onClick={() => navigate(`/systems/${r.system_id}`)}>{v}</a>
        : <Typography.Text type="secondary">未归属</Typography.Text>,
    },
    { title: '定级', dataIndex: 'grading_level', width: 90, render: (v: string | null) => <LevelTag level={v} /> },
    {
      title: '状态', dataIndex: 'status', width: 170,
      render: (v: string, r) => (
        <Space size={4} wrap>
          <ProjectStatusTag status={v} />
          {r.is_current_baseline && <Tag color="cyan">当前基线</Tag>}
        </Space>
      ),
    },
    { title: '评审', dataIndex: 'review_gate_status', width: 100, render: (v: string | null) => <GateStatusTag status={v} /> },
    ...(isFullView ? [{ title: '创建人', dataIndex: 'owner_name', width: 100, render: (v: string | null) => v || '—' } as const] : []),
    { title: '安全需求', dataIndex: ['counts', 'requirements'], width: 90 },
    { title: '耗时', dataIndex: 'duration_seconds', width: 100, render: formatDuration },
    {
      title: '操作', key: 'ops', width: 110, fixed: 'right',
      render: (_, record) => (
        <Space size={0} split={<Divider type="vertical" />}>
          <Button type="link" size="small" onClick={() => navigate(entryPath(record))}>
            {record.status === 'draft' ? '继续填写' : '进入'}
          </Button>
          <Popconfirm
            title="删除该评估及其全部数据?"
            onConfirm={async () => {
              try {
                await api.deleteProject(record.id)
                clearWizardStepStorage(record.id)
                message.success('已删除')
              } catch (e) {
                message.error((e as Error).message)
              }
              reload()
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
        title="评估清单"
        description={isFullView
          ? '全部评估: 8 步向导采集信息, 生成安全需求清单与交付文档'
          : '我的评估: 8 步向导采集信息, 生成安全需求清单与交付文档'}
        extra={(
          <>
            <Select
              allowClear showSearch
              style={{ minWidth: 170 }}
              placeholder="按所属系统筛选"
              value={systemFilter ?? undefined}
              optionFilterProp="label"
              options={systems.map((s) => ({ value: s.id, label: s.name }))}
              onChange={(v) => resetPage(() => setSystemFilter(v ?? null))}
            />
            <Select
              allowClear
              style={{ width: 140 }}
              placeholder="状态"
              value={statusFilter ?? undefined}
              options={Object.entries(labelMapOf(enums, 'project_status')).map(([value, label]) => ({ value, label }))}
              onChange={(v) => resetPage(() => setStatusFilter(v ?? null))}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              发起新评估
            </Button>
          </>
        )}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <Table<ProjectDetail>
          rowKey="id"
          loading={loading}
          dataSource={projects}
          /* max-content: 随「创建人」条件列自适应总宽, 保证表头/表体同宽不错位(#303) */
          scroll={{ x: 'max-content' }}
          sticky
          pagination={{
            current: page, pageSize, total,
            showSizeChanger: true, pageSizeOptions: [10, 20, 50],
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          locale={{
            emptyText: (
              <Empty
                style={{ padding: '32px 0' }}
                description={(
                  <>
                    <p style={{ fontWeight: 600 }}>还没有评估</p>
                    <Typography.Text type="secondary">
                      发起新评估 → 填写向导 → 生成基线 → 查看产物并确认需求
                    </Typography.Text>
                  </>
                )}
              >
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                  发起第一个评估
                </Button>
              </Empty>
            ),
          }}
          columns={columns}
        />
      </Card>

      <Modal
        title="发起新评估" open={createOpen} onCancel={() => setCreateOpen(false)} width={520}
        footer={[
          <Button key="newsys" onClick={() => { setCreateOpen(false); navigate('/systems') }}>
            新建系统
          </Button>,
          <Button key="cancel" onClick={() => setCreateOpen(false)}>取消</Button>,
          <Button
            key="ok" type="primary" loading={creating}
            disabled={!createSystemId || (createMode === 'copy' && !latestRound)}
            onClick={() => void handleCreate()}
          >
            {createMode === 'copy' && latestRound ? '创建新一轮评估' : '创建并进向导'}
          </Button>,
        ]}
      >
        <Typography.Text style={{ display: 'block', marginBottom: 8 }}>
          选择所属系统<span style={{ color: HEX.danger }}>(必选)</span>
        </Typography.Text>
        <Select
          showSearch style={{ width: '100%' }} placeholder="选择所属系统"
          optionFilterProp="label"
          value={createSystemId}
          options={systems.map((s) => ({
            value: s.id,
            label: s.filing_name ? `${s.name}(备案: ${s.filing_name})` : s.name,
          }))}
          onChange={(v) => {
            setCreateSystemId(v)
            // 无历史评估的系统自动切空白新建, 避免「创建」按钮被复制模式禁用
            const sys = systems.find((it) => it.id === v)
            setCreateMode(sys?.latest_round ?? sys?.rounds?.[0] ? 'copy' : 'blank')
          }}
          notFoundContent="还没有系统登记, 请先新建系统"
        />
        {createSystemId && (latestRound ? (
          <>
            <Radio.Group
              value={createMode}
              onChange={(e) => setCreateMode(e.target.value as 'blank' | 'copy')}
              style={{ display: 'grid', gap: 8, marginTop: 16 }}
            >
              <Radio value="copy">按上一轮复制 —— 整卷继承向导数据, 只改变化部分</Radio>
              <Radio value="blank">空白新建 —— 从第一步开始填写</Radio>
            </Radio.Group>
            {createMode === 'copy' && (
              <Alert
                style={{ marginTop: 12 }} type="info" showIcon
                message={`将复制「${latestRound.project_name}」(${latestRound.created_at?.slice(0, 10) || ''}${latestRound.status === 'generated' ? ', 已生成基线' : ''})`}
                description="各步向导数据与上一轮一致; 组件漏洞记录不复制, 生成时重新查询。"
              />
            )}
          </>
        ) : (
          <Alert
            style={{ marginTop: 16 }} type="info" showIcon
            message="该系统还没有历史评估, 将以空白新建"
          />
        ))}
      </Modal>
    </div>
  )
}

/** 步骤耗时埋点聚合(#229)的人类可读展示; 未填报过耗时显示占位符。 */
function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}
