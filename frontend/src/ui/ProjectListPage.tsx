/* 评估清单(#280 新布局): PageHeader + 筛选卡 + 表格卡; 全部项目表格(按角色过滤)。
   新建弹窗强制先选系统(可按上一轮复制, #195); 业务逻辑与角色可见性不变。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Divider, Empty, Modal, Popconfirm, Radio, Select, Space, Table, Tag,
  Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { api, getStoredUser, isFullVisibilityRole } from '../api'
import { HEX } from './tokens'
import { useEnums } from '../enums'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import { GateStatusTag, LevelTag, ProjectStatusTag } from './tags'
import type { ProjectDetail, RoundSummary, SystemRow } from '../types'

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
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

  const reload = useCallback(() => {
    setLoading(true)
    api.listProjects()
      .then(setProjects)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
    api.listSystems().then(setSystems).catch(() => undefined)
  }, [])
  useEffect(reload, [reload])

  const visibleProjects = useMemo(
    () => projects.filter((p) =>
      (!systemFilter || p.system_id === systemFilter)
      && (!statusFilter || p.status === statusFilter)),
    [projects, systemFilter, statusFilter],
  )

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
          <Typography.Link onClick={() => navigate(
            r.status === 'draft' ? `/evaluations/${r.id}/wizard` : `/evaluations/${r.id}/result`,
          )}>{v}</Typography.Link>
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
    {
      title: '操作', key: 'ops', width: 250, fixed: 'right',
      render: (_, record) => (
        <Space size={0} split={<Divider type="vertical" />}>
          <Button type="link" size="small" onClick={() => navigate(`/evaluations/${record.id}/wizard`)}>填写向导</Button>
          <Button type="link" size="small" onClick={() => navigate(`/evaluations/${record.id}/result`)}>查看产物</Button>
          <Button type="link" size="small" onClick={() => navigate(`/evaluations/${record.id}/review`)}>评审中心</Button>
          <Popconfirm
            title="删除该评估及其全部数据?"
            onConfirm={async () => {
              try {
                await api.deleteProject(record.id)
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
          ? '全部评估: 7 步向导采集信息, 生成安全需求清单与交付文档'
          : '我的评估: 7 步向导采集信息, 生成安全需求清单与交付文档'}
        extra={(
          <>
            <Select
              allowClear showSearch
              style={{ minWidth: 170 }}
              placeholder="按所属系统筛选"
              value={systemFilter ?? undefined}
              optionFilterProp="label"
              options={systems.map((s) => ({ value: s.id, label: s.name }))}
              onChange={(v) => setSystemFilter(v ?? null)}
            />
            <Select
              allowClear
              style={{ width: 140 }}
              placeholder="状态"
              value={statusFilter ?? undefined}
              options={Object.entries(labelMapOrEmpty(enums, 'project_status')).map(([value, label]) => ({ value, label }))}
              onChange={(v) => setStatusFilter(v ?? null)}
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
          dataSource={visibleProjects}
          scroll={{ x: 1200 }}
          sticky
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50], showTotal: (t) => `共 ${t} 条` }}
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
          expandable={{
            expandedRowRender: (record) => <CountsGrid counts={record.counts} />,
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

/** labelOf 前置: project_status 的 code→label 映射(枚举由后端统一下发)。 */
function labelMapOrEmpty(enums: ReturnType<typeof useEnums>, key: string): Record<string, string> {
  const raw = enums[key]
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, string> : {}
}

const COUNT_LABELS: Record<string, string> = {
  features: '功能',
  data_assets: '数据资产',
  roles: '角色',
  resources: '资源',
  permission_entries: '权限授权项',
  components: '组件',
  api_endpoints: '接口',
  infra_assets: '基础设施资产',
  external_systems: '外部系统',
  requirements: '安全需求',
  vulnerabilities: '漏洞记录',
}

/** 展开区分组(#86): 评估输入 / 生成产出, 各配 preset 色; 0 值项弱化不隐藏(空项目不突兀)。 */
const COUNT_GROUPS: { title: string; color: string; keys: string[] }[] = [
  {
    title: '评估输入',
    color: 'geekblue',
    keys: ['features', 'data_assets', 'roles', 'resources', 'permission_entries',
      'components', 'api_endpoints', 'infra_assets', 'external_systems'],
  },
  { title: '生成产出', color: 'green', keys: ['requirements', 'vulnerabilities'] },
]

/** 展开区统计网格: 居中分布, 数字放大、标签缩小, 分组一眼可辨(#86)。 */
function CountsGrid({ counts }: { counts: Record<string, number> }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', gap: 32, flexWrap: 'wrap', padding: '8px 0' }}>
      {COUNT_GROUPS.map((group) => {
        const items = group.keys
          .map((key) => ({ key, count: counts[key] ?? 0 }))
          .filter((it) => COUNT_LABELS[it.key])
        return (
          <div key={group.title}>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              {group.title}
            </Typography.Text>
            <Space size={[8, 8]} wrap style={{ maxWidth: 520 }}>
              {items.map(({ key, count }) => (
                <Tag
                  key={key}
                  color={count > 0 ? group.color : 'default'}
                  style={{ marginRight: 0, borderRadius: 12, paddingInline: 10 }}
                >
                  <span style={{ fontSize: 15, fontWeight: 600, marginInlineEnd: 4 }}>{count}</span>
                  {COUNT_LABELS[key]}
                </Tag>
              ))}
            </Space>
          </div>
        )
      })}
    </div>
  )
}
