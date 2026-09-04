/* 项目列表: 全部项目表格(按角色过滤), 新建直通向导第一步; 空状态带首次使用引导。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Popconfirm, Select, Space, Table, Tag, message, Typography
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser } from '../api'
import { labelOf, useEnums } from '../enums'
import { navigate } from '../router'
import type { ProjectDetail, SystemRow } from '../types'

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
  const [systems, setSystems] = useState<SystemRow[]>([])
  const [systemFilter, setSystemFilter] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const isSecurity = getStoredUser()?.role === 'security'

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

  /** 新建不再弹窗: 直接创建"未命名项目"并进入向导第一步补全信息。 */
  const handleCreate = async () => {
    setCreating(true)
    try {
      const detail = await api.createProject({ name: '未命名项目' })
      message.success('已创建, 请在第一步补全项目信息')
      navigate(`/wizard/${detail.id}`)
    } catch (e) {
      message.error((e as Error).message)
      setCreating(false)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={isSecurity ? '项目列表(全部项目)' : '我的项目'}
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
            <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void handleCreate()}>
              新建项目
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
                    <p style={{ fontWeight: 600 }}>还没有项目</p>
                    <p style={{ color: '#888' }}>
                      平台通过 8 步向导采集项目信息, 按行内安全知识库自动生成
                      安全需求清单、SBOM 漏洞清单与交付文档。
                      推荐顺序: 新建项目 → 填向导 → 生成基线 → 查看产物并确认需求。
                    </p>
                  </>
                )}
              >
                <Button type="primary" icon={<PlusOutlined />} onClick={() => void handleCreate()}>
                  新建第一个项目
                </Button>
              </Empty>
            ),
          }}
          expandable={{
            expandedRowRender: (record) => <CountsGrid counts={record.counts} />,
          }}
          columns={[
            { title: '项目名称', dataIndex: 'name' },
            { title: '项目编码', dataIndex: 'code', width: 150 },
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
              render: (v: string | null) => (v ? <Tag color="blue">{v}</Tag> : <Tag>未定级</Tag>),
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
            ...(isSecurity ? [{ title: '创建人', dataIndex: 'owner_name', width: 100 }] : []),
            { title: '安全需求', dataIndex: ['counts', 'requirements'], width: 90 },
            {
              title: '操作', width: 260,
              render: (_, record) => (
                <Space>
                  <Button size="small" onClick={() => navigate(`/wizard/${record.id}`)}>填写向导</Button>
                  <Button size="small" onClick={() => navigate(`/result/${record.id}`)}>查看产物</Button>
                  <Popconfirm
                    title="删除项目及其全部数据?"
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

/** 展开区分组(#86): 项目输入 / 生成产出, 各配 preset 色; 0 值项弱化不隐藏(空项目不突兀)。 */
const COUNT_GROUPS: { title: string; color: string; keys: string[] }[] = [
  {
    title: '项目输入',
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
