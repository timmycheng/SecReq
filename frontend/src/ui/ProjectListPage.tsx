/* 评估列表: 全部项目表格(按角色过滤); 新建弹窗强制先选系统(可按上一轮复制, #195);
   空状态带首次使用引导。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Empty, Modal, Popconfirm, Radio, Select, Space, Table, Tag, message,
  Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser, isFullVisibilityRole } from '../api'
import { GATE_STATUS_COLOR } from './tokens'
import { GRADING_LEVEL_COLOR, HEX } from './tokens'
import { labelOf, useEnums } from '../enums'
import { navigate } from '../router'
import type { ProjectDetail, RoundSummary, SystemRow } from '../types'

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
  const [systems, setSystems] = useState<SystemRow[]>([])
  const [systemFilter, setSystemFilter] = useState<number | null>(null)
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
    () => (systemFilter ? projects.filter((p) => p.system_id === systemFilter) : projects),
    [projects, systemFilter],
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
      navigate(`/wizard/${detail.id}`)
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

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={isFullView ? '评估列表(全部评估)' : '我的评估'}
        extra={(
          <Space>
            <Select
              allowClear showSearch
              style={{ minWidth: 180 }}
              placeholder="按所属系统筛选"
              value={systemFilter ?? undefined}
              optionFilterProp="label"
              options={systems.map((s) => ({ value: s.id, label: s.name }))}
              onChange={(v) => setSystemFilter(v ?? null)}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              发起新评估
            </Button>
          </Space>
        )}
      >
        <Table<ProjectDetail>
          rowKey="id"
          loading={loading}
          dataSource={visibleProjects}
          pagination={{ pageSize: 15 }}
          locale={{
            emptyText: (
              <Empty
                style={{ padding: '32px 0' }}
                description={(
                  <>
                    <p style={{ fontWeight: 600 }}>还没有评估</p>
                    <p style={{ color: '#888' }}>
                      平台通过 6 步向导完成评估信息采集, 按行内安全知识库自动生成
                      安全需求清单、SBOM 漏洞清单与交付文档。
                      推荐顺序: 发起新评估 → 填写向导 → 生成基线 → 查看产物并确认需求。
                    </p>
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
          columns={[
            { title: '评估名称', dataIndex: 'name' },
            { title: '评估编码', dataIndex: 'code', width: 150 },
            {
              title: '所属系统', dataIndex: 'system_name', width: 150,
              render: (v: string | null, record) => v
                ? <a onClick={() => navigate(`/system/${record.system_id}`)}>{v}</a>
                : <Typography.Text type="secondary">未归属</Typography.Text>,
            },
            {
              title: '类型', dataIndex: 'types', width: 160,
              render: (types: string[]) => (types ?? []).map((t) => (
                <Tag key={t}>{labelOf(enums, 'project_types', t)}</Tag>
              )),
            },
            {
              title: '定级', dataIndex: 'grading_level', width: 90,
              render: (v: string | null) => (v ? <Tag color={GRADING_LEVEL_COLOR[v] ?? 'default'}>{v}</Tag> : <Tag>未定级</Tag>),
            },
            {
              title: '状态', dataIndex: 'status', width: 150,
              render: (v: string, record) => (
                <Space size={4} wrap>
                  {v === 'generated'
                    ? <Tag color="green">已生成基线</Tag>
                    : v === 'draft' ? <Tag color="orange">草稿</Tag> : <Tag>{labelOf(enums, 'project_status', v)}</Tag>}
                  {record.is_current_baseline && <Tag color="cyan">当前基线</Tag>}
                </Space>
              ),
            },
            {
              title: '评审', dataIndex: 'review_gate_status', width: 100,
              render: (v: string | null) => (v
                ? <Tag color={GATE_STATUS_COLOR[v] ?? 'default'}>
                    {{ pending: '待提交', in_review: '评审中', passed: '已通过', rejected: '已否决', rectifying: '整改中' }[v] ?? v}
                  </Tag>
                : <Tag>未提交</Tag>),
            },
            ...(isFullView ? [{ title: '创建人', dataIndex: 'owner_name', width: 100 }] : []),
            { title: '安全需求', dataIndex: ['counts', 'requirements'], width: 90 },
            {
              title: '操作', width: 330,
              render: (_, record) => (
                <Space>
                  <Button size="small" onClick={() => navigate(`/wizard/${record.id}`)}>填写向导</Button>
                  <Button size="small" onClick={() => navigate(`/result/${record.id}`)}>查看产物</Button>
                  <Button size="small" onClick={() => navigate(`/project/${record.id}/review`)}>评审中心</Button>
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
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
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
                message={`将复制「${latestRound.project_name}」(${latestRound.created_at?.slice(0, 10) || ''}{latestRound.status === 'generated' ? ', 已生成基线' : ''})`}
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
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 16, fontSize: 12 }}>
          没有合适的系统? 点左下角「新建系统」先去系统台账登记(基本信息/基础设施/组件都在系统上维护)。
        </Typography.Text>
      </Modal>
    </div>
  )
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
