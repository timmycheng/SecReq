/* 项目列表: 全部项目表格(按角色过滤), 新建直通向导第一步; 空状态带首次使用引导。 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Empty, Popconfirm, Space, Table, Tag, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser } from '../api'
import { labelOf, useEnums } from '../enums'
import { navigate } from '../router'
import type { ProjectDetail } from '../types'

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const isSecurity = getStoredUser()?.role === 'security'

  const reload = useCallback(() => {
    setLoading(true)
    api.listProjects()
      .then(setProjects)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

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
          <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void handleCreate()}>
            新建项目
          </Button>
        )}
      >
        <Table<ProjectDetail>
          rowKey="id"
          loading={loading}
          dataSource={projects}
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
            expandedRowRender: (record) => (
              <Space size={[24, 8]} wrap>
                {Object.entries(record.counts).map(([key, count]) => (
                  <span key={key}>
                    <Tag>{count}</Tag>
                    {COUNT_LABELS[key] ?? key}
                  </span>
                ))}
              </Space>
            ),
          }}
          columns={[
            { title: '项目名称', dataIndex: 'name' },
            { title: '项目编码', dataIndex: 'code', width: 160 },
            {
              title: '类型', dataIndex: 'types', width: 180,
              render: (types: string[]) => (types ?? []).map((t) => (
                <Tag key={t}>{labelOf(enums, 'project_types', t)}</Tag>
              )),
            },
            {
              title: '定级', dataIndex: 'grading_level', width: 100,
              render: (v: string | null) => (v ? <Tag color="blue">{v}</Tag> : <Tag>未定级</Tag>),
            },
            {
              title: '状态', dataIndex: 'status', width: 110,
              render: (v: string) =>
                v === 'generated'
                  ? <Tag color="green">已生成基线</Tag>
                  : v === 'draft' ? <Tag color="orange">草稿</Tag> : <Tag>{labelOf(enums, 'project_status', v)}</Tag>,
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
