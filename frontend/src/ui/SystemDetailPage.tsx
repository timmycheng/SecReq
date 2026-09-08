/* 系统详情(#280 改版): Tab 改为锚点分节 —— 左栏「栏目链接 + 评估时间线」sticky 固定
   (滚动页面不滚走), 右侧内容卡片纵向排布; 基本信息卡对齐新原型样式。
   数据事实与业务逻辑沿用 #272: 清单类分节读 system_baselines 快照(features 读来源轮次),
   基础设施/组件清单为系统级直接编辑区, 变动历史为相邻轮次需求 diff + 基线履历。 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  Alert, Button, Card, Descriptions, Empty, Modal, Space, Spin, Table, Tag, Timeline,
  Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser, isSecuritySideRole } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import { DATA_LEVEL_COLOR, PRIORITY_COLOR } from './tokens'
import { DIFF_FIELD_FALLBACK_LABELS } from './common'
import { LevelTag, RoundCell } from './tags'
import { SystemFormModal } from './SystemsPage'
import PageHeader from './PageHeader'
import { SystemComponentsCard } from './system/SystemComponentsCard'
import { SystemInfraCard } from './system/SystemInfraCard'
import type {
  BaselineApiEndpoint, BaselineDataAsset, BaselineDataTable, BaselinePermissionBundle,
  DetailSectionMeta, DiffRow, ExternalSystemRow, FilingRow, RoundSummary, SystemDetailFeature,
  SystemRow,
} from '../types'

const fmtDateTime = (v?: string | null) => v?.slice(0, 19).replace('T', ' ') ?? '—'

/** 分节数据通用加载态: 挂载即拉取, 三态齐备。 */
function useSection<T>(loader: () => Promise<DetailSectionMeta & { rows: T }>) {
  const [meta, setMeta] = useState<DetailSectionMeta | null>(null)
  const [rows, setRows] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    loader()
      .then((res) => { setMeta(res); setRows(res.rows) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [loader])
  useEffect(reload, [reload])
  return { meta, rows, loading, error, reload }
}

/** 清单类分节未写回基线时的统一引导。 */
function NoBaselineHint() {
  return (
    <Alert
      type="info" showIcon
      message="尚未生成安全基线"
      description="评估轮次终审通过后, 本轮清单快照会写回为系统基线; 到时这里即可查看。可先在「评估历史」发起或继续评估。"
    />
  )
}

function SectionError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return <Alert type="error" showIcon message="数据加载失败" description={error}
    action={<Button size="small" onClick={onRetry}>重试</Button>} />
}

/** 内容分节容器: 锚点 id + 标题卡, 对齐详情页布局模式(#280)。 */
function Section({ id, title, extra, children }: {
  id: string
  title: string
  extra?: ReactNode
  children: ReactNode
}) {
  return (
    <Card id={`sec-${id}`} className="anchor-section" title={title} extra={extra}>
      {children}
    </Card>
  )
}

/* ── 基本信息(#280 新样式): 描述表 + 定级来源 + 编辑入口在页头 ── */

function BasicSection({ system, enums, onEdit }: {
  system: SystemRow
  enums: ReturnType<typeof useEnums>
  onEdit: () => void
}) {
  const typeLabels = labelMapOf(enums, 'project_types')
  const scaleLabels = labelMapOf(enums, 'user_scales')
  const directionLabels = labelMapOf(enums, 'external_system_directions')
  // 外部连接系统清单(#289, DESIGN TAB1): 与功能清单同口径读基线来源轮次
  const { meta, rows, loading, error, reload } = useSection<ExternalSystemRow[]>(useCallback(
    () => api.systemDetailExternalSystems(system.id), [system.id]))
  return (
    <Section
      id="basic" title="基本信息"
      extra={<Button size="small" onClick={onEdit}>编辑信息</Button>}
    >
      <Descriptions
        column={{ xs: 1, sm: 2, md: 3 }} size="small" bordered
        items={[
          { key: 'code', label: '系统编号', children: system.code || '—' },
          {
            key: 'filing', label: '所属备案',
            children: system.filing_name
              ? <Space size={6}>{system.filing_name}<LevelTag level={system.filing_level} /></Space>
              : <Typography.Text type="secondary">未挂备案(定级走评估问卷)</Typography.Text>,
          },
          { key: 'owner', label: '负责人', children: system.owner_name || '—' },
          { key: 'department', label: '归属部门', children: system.department || '—' },
          { key: 'scale', label: '用户规模', children: scaleLabels[system.user_scale ?? ''] ?? (system.user_scale || '—') },
          { key: 'types', label: '业务类型', children: (system.types ?? []).map((t) => typeLabels[t] ?? t).join('、') || '—' },
          {
            key: 'public', label: '公网访问',
            children: system.is_public ? <Tag color="orange">涉及公网</Tag> : <Tag>无公网</Tag>,
          },
          {
            key: 'importance', label: '重要程度',
            children: system.importance
              ? <Tag color={system.importance === '高' ? 'volcano' : system.importance === '中' ? 'gold' : 'default'}>{system.importance}</Tag>
              : '—',
          },
          {
            key: 'responsibles', label: '责任人(开发/运维/业务)',
            children: (
              <span style={{ fontSize: 12 }}>
                开发: {system.owner_dev_name || '—'} · 运维: {system.owner_ops_name || '—'} · 业务: {system.owner_biz_name || '—'}
              </span>
            ),
          },
          {
            key: 'tags', label: '标签',
            children: (system.tags ?? []).length
              ? <Space size={4} wrap>{(system.tags ?? []).map((t) => <Tag key={t} color="blue" style={{ marginRight: 0 }}>{t}</Tag>)}</Space>
              : '—',
          },
        ]}
      />
      {system.filing_level && (
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          定级来源: 备案「{system.filing_name}」(等保{system.filing_level}); 评估后人工调整定级会在产物页提示与备案不一致。
        </Typography.Text>
      )}

      <Typography.Title level={5} style={{ marginTop: 20, marginBottom: 8 }}>外部连接系统清单</Typography.Title>
      {error
        ? <SectionError error={error} onRetry={reload} />
        : (
          <Table<ExternalSystemRow>
            rowKey={(r) => r.uid || r.name}
            size="small" loading={loading} dataSource={rows ?? []}
            pagination={false}
            locale={{ emptyText: meta?.has_baseline
              ? <Empty description="基线来源轮次没有外部系统连接记录" />
              : <Empty description="完成评估并终审通过后, 这里展示基线轮次维护的外部连接系统" /> }}
            columns={[
              { title: '系统名称', dataIndex: 'name' },
              { title: '对接用途', dataIndex: 'purpose', render: (v: string | null) => v || '—' },
              { title: '数据方向', dataIndex: 'direction', width: 160,
                render: (v: string) => directionLabels[v] ?? v },
              { title: '是否涉敏', dataIndex: 'involves_sensitive', width: 100,
                render: (v: boolean) => (v ? <Tag color="red">涉敏</Tag> : <Tag>否</Tag>) },
              {
                title: '操作', width: 100,
                render: () => meta?.source_project_id
                  ? <a onClick={() => navigate(`/evaluations/${meta.source_project_id}/wizard`)}>去维护</a>
                  : <Typography.Text type="secondary">—</Typography.Text>,
              },
            ]}
          />
        )}
    </Section>
  )
}

/* ── 功能清单 ─────────────────────────────────────── */

function FeaturesSection({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const categoryLabels = labelMapOf(enums, 'feature_categories')
  const sensitivityLabels = labelMapOf(enums, 'sensitivity_levels')
  const { meta, rows, loading, error, reload } = useSection<SystemDetailFeature[]>(useCallback(
    () => api.systemDetailFeatures(systemId), [systemId]))
  if (loading) return <Section id="features" title="功能清单"><div style={{ padding: 24, textAlign: 'center' }}><Spin /></div></Section>
  if (error) return <Section id="features" title="功能清单"><SectionError error={error} onRetry={reload} /></Section>
  if (!meta?.has_baseline) return <Section id="features" title="功能清单"><NoBaselineHint /></Section>
  return (
    <Section id="features" title="功能清单">
      <Table<SystemDetailFeature>
        rowKey={(r) => r.uid || r.name}
        size="small" loading={loading} dataSource={rows ?? []}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
        locale={{ emptyText: <Empty description="基线来源轮次没有功能记录" /> }}
        columns={[
          { title: '功能名称', dataIndex: 'name' },
          { title: '所属模块', dataIndex: 'module', width: 140, render: (v) => v || '—' },
          { title: '功能分类', dataIndex: 'categories', width: 240,
            render: (codes: string[]) => (codes ?? []).map((c) => (
              <Tag key={c}>{categoryLabels[c] ?? c}</Tag>
            )) },
          { title: '敏感级别', dataIndex: 'sensitivity', width: 100,
            render: (v) => (v ? sensitivityLabels[v] ?? v : '—') },
          { title: '标记', width: 140,
            render: (_: unknown, r: SystemDetailFeature) => (
              <Space size={4} wrap>
                {r.involves_payment && <Tag color="gold">涉及资金</Tag>}
                {r.exposed_to_internet && <Tag color="orange">公网暴露</Tag>}
                {!r.involves_payment && !r.exposed_to_internet && '—'}
              </Space>
            ) },
          { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '—' },
        ]}
      />
    </Section>
  )
}

/* ── 数据资产(资产 → 表 → 字段) ───────────────────── */

function DataAssetsSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselineDataAsset[]>(useCallback(
    () => api.systemDetailDataAssets(systemId), [systemId]))
  if (loading) return <Section id="assets" title="数据资产"><div style={{ padding: 24, textAlign: 'center' }}><Spin /></div></Section>
  if (error) return <Section id="assets" title="数据资产"><SectionError error={error} onRetry={reload} /></Section>
  if (!meta?.has_baseline) return <Section id="assets" title="数据资产"><NoBaselineHint /></Section>
  return (
    <Section id="assets" title="数据资产">
      <Table<BaselineDataAsset>
        rowKey={(r) => r.uid || r.name}
        size="small" loading={loading} dataSource={rows ?? []}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
        locale={{ emptyText: <Empty description="基线中没有数据资产记录" /> }}
        expandable={{
          expandedRowRender: (asset) => (
            <Table<BaselineDataTable>
              rowKey="table_name" size="small" pagination={false}
              dataSource={asset.tables ?? []}
              locale={{ emptyText: <Empty description="该资产未登记数据字典表" /> }}
              expandable={{
                expandedRowRender: (t) => (
                  <Table size="small" pagination={false} rowKey="field_name"
                    dataSource={t.fields ?? []}
                    columns={[
                      { title: '字段名', dataIndex: 'field_name' },
                      { title: '字段类型', dataIndex: 'field_type', width: 120, render: (v) => v || '—' },
                      { title: '加密', dataIndex: 'need_encrypt', width: 80,
                        render: (v: boolean) => (v ? <Tag color="blue">加密</Tag> : '—') },
                      { title: '脱敏', dataIndex: 'need_mask', width: 80,
                        render: (v: boolean) => (v ? <Tag color="gold">脱敏</Tag> : '—') },
                      { title: '脱敏规则', dataIndex: 'mask_rule', render: (v) => v || '—' },
                    ]}
                  />
                ),
              }}
              columns={[
                { title: '数据表', dataIndex: 'table_name' },
                { title: '字段数', width: 90, render: (_: unknown, t) => (t.fields ?? []).length },
              ]}
            />
          ),
        }}
        columns={[
          { title: '资产名称', dataIndex: 'name' },
          { title: '数据类型', dataIndex: 'data_type', width: 120, render: (v) => v || '—' },
          { title: '安全分级', dataIndex: 'classification', width: 170,
            render: (v: string | null) => (v
              ? <Tag color={DATA_LEVEL_COLOR[v] ?? 'default'}>{v}</Tag> : '—') },
          { title: '标记', width: 160,
            render: (_: unknown, r: BaselineDataAsset) => (
              <Space size={4} wrap>
                {r.c3_tag && <Tag color="red">C3</Tag>}
                {(r.is_pii || r.is_sensitive_pii) && <Tag color="gold">PII</Tag>}
                {r.cross_border_transfer && <Tag color="orange">跨境</Tag>}
                {!r.c3_tag && !r.is_pii && !r.is_sensitive_pii && !r.cross_border_transfer && '—'}
              </Space>
            ) },
          { title: '字典表数', width: 90, render: (_: unknown, r) => (r.tables ?? []).length },
        ]}
      />
    </Section>
  )
}

/* ── 权限矩阵 ─────────────────────────────────────── */

function PermissionsSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselinePermissionBundle>(useCallback(
    () => api.systemDetailPermissions(systemId), [systemId]))
  if (loading) return <Section id="permissions" title="权限矩阵"><div style={{ padding: 24, textAlign: 'center' }}><Spin /></div></Section>
  if (error) return <Section id="permissions" title="权限矩阵"><SectionError error={error} onRetry={reload} /></Section>
  if (!meta?.has_baseline) return <Section id="permissions" title="权限矩阵"><NoBaselineHint /></Section>
  const bundle = rows ?? { roles: [], resources: [], permission_entries: [] }
  const roleNameOf = (uid?: string | null) =>
    bundle.roles.find((r) => r.uid === uid)?.name ?? uid ?? '—'
  const resourceNameOf = (uid?: string | null) =>
    bundle.resources.find((r) => r.uid === uid)?.name ?? uid ?? '—'
  return (
    <Section id="permissions" title="权限矩阵">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Table size="small" rowKey="uid" pagination={false} dataSource={bundle.roles}
          locale={{ emptyText: <Empty description="基线中没有角色记录" /> }}
          columns={[
            { title: '角色', dataIndex: 'name' },
            { title: '角色类型', dataIndex: 'role_type', width: 140, render: (v) => v || '—' },
            { title: '预估用户数', dataIndex: 'user_count_estimate', width: 120, render: (v) => v ?? '—' },
          ]} />
        <Table size="small" rowKey="uid" pagination={false} dataSource={bundle.resources}
          locale={{ emptyText: <Empty description="基线中没有资源记录" /> }}
          columns={[
            { title: '资源', dataIndex: 'name' },
            { title: '资源类型', dataIndex: 'resource_type', width: 160, render: (v) => v || '—' },
            { title: '重要度', dataIndex: 'criticality', width: 120, render: (v) => v || '—' },
          ]} />
        <Typography.Text strong>授权项({bundle.permission_entries.length})</Typography.Text>
        <Table size="small" rowKey={(r) => `${r.role_uid}-${r.resource_uid}-${r.action}`}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
          dataSource={bundle.permission_entries}
          locale={{ emptyText: <Empty description="基线中没有授权记录" /> }}
          columns={[
            { title: '角色', dataIndex: 'role_uid', render: (v) => roleNameOf(v) },
            { title: '资源', dataIndex: 'resource_uid', render: (v) => resourceNameOf(v) },
            { title: '操作', dataIndex: 'action', width: 140, render: (v) => v || '—' },
            { title: '需审批', dataIndex: 'requires_approval', width: 100,
              render: (v: boolean) => (v ? <Tag color="orange">需审批</Tag> : '—') },
          ]} />
      </Space>
    </Section>
  )
}

/* ── 接口清单 ─────────────────────────────────────── */

function ApisSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselineApiEndpoint[]>(useCallback(
    () => api.systemDetailApis(systemId), [systemId]))
  if (loading) return <Section id="apis" title="接口清单"><div style={{ padding: 24, textAlign: 'center' }}><Spin /></div></Section>
  if (error) return <Section id="apis" title="接口清单"><SectionError error={error} onRetry={reload} /></Section>
  if (!meta?.has_baseline) return <Section id="apis" title="接口清单"><NoBaselineHint /></Section>
  return (
    <Section id="apis" title="接口清单">
      <Table<BaselineApiEndpoint>
        rowKey={(r) => r.uid || `${r.method}-${r.path}`}
        size="small" loading={loading} dataSource={rows ?? []}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
        locale={{ emptyText: <Empty description="基线中没有接口记录" /> }}
        columns={[
          { title: '接口名称', dataIndex: 'name' },
          { title: '方法', dataIndex: 'method', width: 90,
            render: (v: string | null) => (v ? <Tag color="geekblue">{v.toUpperCase()}</Tag> : '—') },
          { title: '路径', dataIndex: 'path', ellipsis: true, render: (v) => v || '—' },
          { title: '需认证', dataIndex: 'auth_required', width: 90,
            render: (v: boolean) => (v ? '是' : <Tag color="red">匿名</Tag>) },
          { title: '公网暴露', dataIndex: 'public_exposed', width: 90,
            render: (v: boolean) => (v ? <Tag color="orange">公网</Tag> : '—') },
          { title: '限流', dataIndex: 'rate_limit', width: 120, render: (v) => v || '—' },
        ]}
      />
    </Section>
  )
}

/* ── 基础设施 / 组件清单(系统级, 唯一直接编辑区) ──── */

function InfraSection({ systemId }: { systemId: number }) {
  return (
    <Section id="infra" title="基础设施">
      <SystemInfraCard systemId={systemId} />
    </Section>
  )
}

function ComponentsSection({ systemId }: { systemId: number }) {
  return (
    <Section id="components" title="组件清单(SBOM)">
      <SystemComponentsCard systemId={systemId} />
    </Section>
  )
}

/* ── 评估历史(内容分节完整版) ─────────────────────── */

function HistorySection({ system, rounds }: { system: SystemRow; rounds: RoundSummary[] }) {
  if (rounds.length === 0) {
    return (
      <Typography.Text type="secondary">
        还没有评估记录, 点右上角「发起新一轮评估」开始。
      </Typography.Text>
    )
  }
  return (
    <Timeline
      items={rounds.map((r) => ({
        color: r.status === 'generated' ? 'green' : 'gray',
        children: (
          <div style={{ paddingBottom: 8 }}>
            <Space size={8} wrap align="center">
              <Typography.Text strong>{r.project_name}</Typography.Text>
              {system.current_baseline_project_id === r.project_id && (
                <Tag color="cyan">当前基线</Tag>
              )}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {r.created_at?.slice(0, 10) || ''}
              </Typography.Text>
            </Space>
            <div style={{ marginTop: 4 }}><RoundCell round={r} /></div>
            <Space size={8} style={{ marginTop: 6 }}>
              <Button size="small" onClick={() => navigate(`/evaluations/${r.project_id}/wizard`)}>
                {r.status === 'generated' ? '再编辑' : '继续填写'}
              </Button>
              {r.status === 'generated' && (
                <Button size="small" type="primary" ghost onClick={() => navigate(`/evaluations/${r.project_id}/result`)}>
                  查看产物
                </Button>
              )}
            </Space>
          </div>
        ),
      }))}
    />
  )
}

/* ── 变动历史: 基线履历 + 相邻已生成轮次需求 diff ─────────── */

function DiffRows({ rows }: { rows: DiffRow[] }) {
  return (
    <Table size="small" rowKey="req_id" pagination={false} dataSource={rows}
      columns={[
        { title: '编号', dataIndex: 'req_id', width: 150 },
        { title: '需求标题', dataIndex: 'title' },
        { title: '优先级', dataIndex: 'priority', width: 90,
          render: (p: string) => <Tag color={PRIORITY_COLOR[p]}>{p}</Tag> },
        { title: '来源', dataIndex: 'source_label', ellipsis: true, render: (v) => v || '—' },
      ]} />
  )
}

/** 需求 diff 变更条目(RequirementDiff['changed'] 元素的非空别名)。 */
interface DiffRowChange {
  fields: string[]
  field_values?: Record<string, { label: string; previous: string; current: string }>
  previous: DiffRow
  current: DiffRow
}

function ChangesSection({ system }: { system: SystemRow }) {
  const [detail, setDetail] = useState<{
    title: ReactNode; added: DiffRow[]; removed: DiffRow[]; changed: DiffRowChange[]
  } | null>(null)
  const [rows, setRows] = useState<{
    project_id: number; code: string; created_at: string | null
    prev_code: string | null; added: DiffRow[]; removed: DiffRow[]; changed: DiffRowChange[]
  }[] | null>(null)
  const histories = system.baseline_histories ?? []

  useEffect(() => {
    // 对每个已生成轮次取与上一轮的需求 diff(comparable=false 的轮次跳过)
    const generated = (system.rounds ?? []).filter((r) => r.status === 'generated')
    Promise.all(generated.map(async (r) => {
      try {
        const diff = await api.requirementsDiff(r.project_id)
        if (!diff.comparable) return null
        return {
          project_id: r.project_id, code: r.project_code,
          created_at: r.created_at ?? null, prev_code: diff.previous_project?.project_code ?? null,
          added: diff.added ?? [], removed: diff.removed ?? [], changed: diff.changed ?? [],
        }
      } catch {
        return null
      }
    })).then((list) => setRows(list.filter((x): x is NonNullable<typeof x> => x !== null)))
      .catch(() => setRows([]))
  }, [system])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Typography.Text strong>需求变动(相邻已生成轮次对比)</Typography.Text>
        <Table size="small" style={{ marginTop: 8 }}
          rowKey="project_id" loading={rows === null}
          dataSource={rows ?? []}
          locale={{ emptyText: <Empty description="暂无可对比的相邻轮次(至少两轮已生成评估)" /> }}
          columns={[
            { title: '轮次', dataIndex: 'code', width: 180 },
            { title: '评估时间', dataIndex: 'created_at', width: 120,
              render: (v: string | null) => v?.slice(0, 10) ?? '—' },
            { title: '对比基准', dataIndex: 'prev_code', width: 180, render: (v) => v ?? '—' },
            { title: '新增', width: 80, render: (_: unknown, r) => <Tag color="green">+{r.added.length}</Tag> },
            { title: '移除', width: 80, render: (_: unknown, r) => <Tag color="red">-{r.removed.length}</Tag> },
            { title: '变更', width: 80, render: (_: unknown, r) => <Tag color="gold">~{r.changed.length}</Tag> },
            { title: '操作', width: 100,
              render: (_: unknown, r) => (
                <Button type="link" size="small" style={{ padding: 0 }}
                  onClick={() => setDetail({
                    title: `${r.code} vs ${r.prev_code}`,
                    added: r.added, removed: r.removed, changed: r.changed,
                  })}>
                  查看明细
                </Button>
              ) },
          ]}
        />
      </div>
      <div>
        <Typography.Text strong>基线变更履历</Typography.Text>
        {histories.length === 0 ? (
          <div style={{ marginTop: 8 }}>
            <Typography.Text type="secondary">暂无基线变更记录。</Typography.Text>
          </div>
        ) : (
          <Timeline
            style={{ marginTop: 12 }}
            items={histories.map((h) => ({
              children: (
                <div>
                  <Typography.Text>{h.summary}</Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                    {fmtDateTime(h.created_at)}
                    {h.operator_name ? ` · ${h.operator_name}` : ''}
                    {h.project_id ? ` · 依据第 ${h.project_id} 轮评审` : ''}
                  </Typography.Text>
                </div>
              ),
            }))}
          />
        )}
      </div>
      <Modal
        title={`需求变动明细: ${detail?.title ?? ''}`} open={detail !== null}
        onCancel={() => setDetail(null)} footer={null} width={860}
      >
        {detail && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <div>
              <Typography.Text strong type="success">新增 {detail.added.length} 条</Typography.Text>
              <DiffRows rows={detail.added} />
            </div>
            <div>
              <Typography.Text strong type="danger">移除 {detail.removed.length} 条</Typography.Text>
              <DiffRows rows={detail.removed} />
            </div>
            <div>
              <Typography.Text strong type="warning">变更 {detail.changed.length} 条</Typography.Text>
              <Table size="small" rowKey={(r) => r.current.req_id} pagination={false}
                dataSource={detail.changed}
                columns={[
                  { title: '编号', width: 150, render: (_: unknown, c) => <Typography.Text code>{c.current.req_id}</Typography.Text> },
                  { title: '需求标题', render: (_: unknown, c) => c.current.title },
                  { title: '变更字段', width: 200, render: (_: unknown, c) =>
                    c.fields.map((f) => DIFF_FIELD_FALLBACK_LABELS[f] ?? f).join('、') },
                ]} />
            </div>
          </Space>
        )}
      </Modal>
    </Space>
  )
}

/* ── 合规基线(D 区): 级别变更确认待办 + 基线概要 ──── */

function BaselineSection({ system, confirming, onConfirm, isSecuritySide }: {
  system: SystemRow
  confirming: boolean
  onConfirm: (decision: 'adopt_suggested' | 'keep_filing') => void
  isSecuritySide: boolean
}) {
  const baseline = system.baseline
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {baseline?.pending_level_confirmation && (
        <Alert
          type="warning" showIcon
          message="等保级别变更确认"
          description={
            <Space direction="vertical" size={4}>
              <Typography.Text>
                第 {baseline.pending_level_confirmation.project_id} 轮评估建议定级为
                <Tag color="gold" style={{ margin: '0 4px' }}>{baseline.pending_level_confirmation.suggested_level}</Tag>
                当前备案定级为
                <Tag color="blue" style={{ margin: '0 4px' }}>{baseline.pending_level_confirmation.filing_level}</Tag>
                请确认是否采纳评估建议覆盖备案定级。
              </Typography.Text>
              {isSecuritySide ? (
                <Space>
                  <Button size="small" type="primary" loading={confirming}
                    onClick={() => onConfirm('adopt_suggested')}>
                    采纳评估级(覆盖备案)
                  </Button>
                  <Button size="small" loading={confirming}
                    onClick={() => onConfirm('keep_filing')}>
                    维持备案级(留痕)
                  </Button>
                </Space>
              ) : (
                <Typography.Text type="secondary">请联系安全管理员确认。</Typography.Text>
              )}
            </Space>
          }
        />
      )}
      {baseline ? (
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} bordered
          items={[
            { key: 'assets', label: '数据资产', children: baseline.summary?.data_assets ?? 0 },
            { key: 'tables', label: '数据字典表', children: baseline.summary?.data_tables ?? 0 },
            { key: 'apis', label: 'API 清单', children: baseline.summary?.api_endpoints ?? 0 },
            {
              key: 'matrix', label: '权限矩阵',
              children: `角色 ${baseline.summary?.roles ?? 0} · 资源 ${baseline.summary?.resources ?? 0} · 授权 ${baseline.summary?.permission_entries ?? 0}`,
            },
            {
              key: 'source', label: '来源轮次',
              children: baseline.source_project_id
                ? <Button type="link" size="small" style={{ padding: 0 }}
                    onClick={() => navigate(`/evaluations/${baseline.source_project_id}/result`)}>
                  第 {baseline.source_project_id} 轮评估
                </Button>
                : '—',
            },
            {
              key: 'updated', label: '写回时间',
              children: `${fmtDateTime(baseline.updated_at)}${baseline.updated_by ? ` · ${baseline.updated_by}` : ''}`,
            },
          ]}
        />
      ) : (
        <Typography.Text type="secondary">
          暂无安全基线。评估轮次终审通过后, 本轮资产/字典/权限/接口快照将写回为系统基线。
        </Typography.Text>
      )}
    </Space>
  )
}

/* ── 页面容器: 左栏(栏目链接 + 时间线) sticky ─────── */

const NAV_ITEMS = [
  { key: 'basic', label: '基本信息' },
  { key: 'features', label: '功能清单' },
  { key: 'assets', label: '数据资产' },
  { key: 'permissions', label: '权限矩阵' },
  { key: 'apis', label: '接口清单' },
  { key: 'infra', label: '基础设施' },
  { key: 'components', label: '组件清单' },
  { key: 'history', label: '评估历史' },
  { key: 'changes', label: '变动历史' },
  { key: 'baseline', label: '合规基线' },
]

export default function SystemDetailPage({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const [system, setSystem] = useState<SystemRow | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [filings, setFilings] = useState<FilingRow[]>([])
  const [confirming, setConfirming] = useState(false)
  const [active, setActive] = useState('basic')
  const isSecuritySide = isSecuritySideRole(getStoredUser()?.role)

  const reload = useCallback(() => {
    api.getSystem(systemId)
      .then(setSystem)
      .catch((e: Error) => message.error(e.message))
  }, [systemId])
  useEffect(reload, [reload])
  useEffect(() => { api.listFilings().then(setFilings).catch(() => undefined) }, [])

  // 滚动跟随: 视口顶部最近的分节高亮左栏栏目
  useEffect(() => {
    const onScroll = () => {
      let current = NAV_ITEMS[0].key
      for (const item of NAV_ITEMS) {
        const el = document.getElementById(`sec-${item.key}`)
        if (el && el.getBoundingClientRect().top <= 120) current = item.key
      }
      setActive(current)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const jumpTo = (key: string) => {
    setActive(key)
    document.getElementById(`sec-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const confirmLevel = async (decision: 'adopt_suggested' | 'keep_filing') => {
    setConfirming(true)
    try {
      const res = await api.confirmBaselineLevel(systemId, decision)
      message.success(res.summary)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  if (!system) {
    return <div style={{ padding: 24 }}><Spin /></div>
  }

  const startNewRound = async () => {
    setCreating(true)
    try {
      const rounds = system.rounds ?? []
      const detail = await api.createProject({
        name: `${system.name} 评估`,
        system_id: system.id,
        // 评估继承: 有历史轮次时整卷复制(含定级问卷), 只改变化部分(#151)
        from_project_id: rounds.length ? rounds[0].project_id : undefined,
      })
      message.success(rounds.length
        ? '已按上一轮评估创建新一轮, 请在向导中核对并修改变化部分'
        : '已创建新一轮评估, 请在向导第一步核对信息')
      navigate(`/evaluations/${detail.id}/wizard`)
    } catch (e) {
      message.error((e as Error).message)
      setCreating(false)
    }
  }

  const rounds = system.rounds ?? []
  const railStyle: CSSProperties = {
    width: 188, flex: 'none',
    position: 'sticky', top: 16,
    display: 'flex', flexDirection: 'column', gap: 16,
    maxHeight: 'calc(100vh - 32px)', overflow: 'auto',
  }

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        onBack={() => navigate('/systems')}
        title={system.name}
        description={[system.code, system.filing_name, system.owner_name]
          .filter(Boolean).join(' · ') || undefined}
        extra={(
          <Button
            type="primary" icon={<PlusOutlined />} loading={creating}
            onClick={() => void startNewRound()}
          >
            发起新一轮评估
          </Button>
        )}
      />
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* 左栏: 栏目链接 + 时间线, 一起 sticky 固定(#280 修正) */}
        <div style={railStyle}>
          <Card styles={{ body: { padding: 8 } }}>
            {NAV_ITEMS.map((s) => (
              <Button
                key={s.key}
                type="text"
                block
                size="small"
                style={{
                  justifyContent: 'flex-start',
                  fontWeight: active === s.key ? 600 : 400,
                  color: active === s.key ? 'var(--secreq-primary)' : undefined,
                }}
                onClick={() => jumpTo(s.key)}
              >
                {s.label}
              </Button>
            ))}
          </Card>
          {/* 时间线卡片(#280 修正): 固定在栏目链接下方, 滚动不滚走 */}
          <Card size="small" title="评估时间线" styles={{ body: { maxHeight: 320, overflow: 'auto' } }}>
            {rounds.length === 0 ? (
              <Typography.Text type="secondary">暂无评估</Typography.Text>
            ) : (
              <Timeline
                items={rounds.map((r) => ({
                  color: r.status === 'generated' ? 'green' : 'gray',
                  children: (
                    <div style={{ cursor: 'pointer' }} onClick={() =>
                      navigate(r.status === 'generated'
                        ? `/evaluations/${r.project_id}/result`
                        : `/evaluations/${r.project_id}/wizard`)
                    }>
                      <Typography.Text style={{ fontSize: 12 }}>{r.project_name}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                        {r.created_at?.slice(0, 10) || ''}
                        {system.current_baseline_project_id === r.project_id ? ' · 当前基线' : ''}
                      </Typography.Text>
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </div>

        {/* 右侧内容分节 */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <BasicSection system={system} enums={enums} onEdit={() => setEditing(true)} />
          <FeaturesSection systemId={system.id} />
          <DataAssetsSection systemId={system.id} />
          <PermissionsSection systemId={system.id} />
          <ApisSection systemId={system.id} />
          <InfraSection systemId={system.id} />
          <ComponentsSection systemId={system.id} />
          <Section id="history" title="评估历史">
            <HistorySection system={system} rounds={rounds} />
          </Section>
          <Section id="changes" title="变动历史">
            <ChangesSection system={system} />
          </Section>
          <Section id="baseline" title="合规基线">
            <BaselineSection
              system={system} confirming={confirming}
              onConfirm={confirmLevel} isSecuritySide={isSecuritySide}
            />
          </Section>
        </div>
      </div>

      {editing && (
        <SystemFormModal
          value={system}
          filings={filings}
          enums={enums}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); reload() }}
        />
      )}
    </div>
  )
}
