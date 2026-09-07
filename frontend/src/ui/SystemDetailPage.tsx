/* 系统详情(#272 重构): 以 Tab 组织系统的全部事实 ——
   基本信息(含基础设施/组件清单)、功能清单/数据资产/权限矩阵/接口清单(读当前基线, 只读)、
   评估历史(轮次时间线)、变动历史(相邻已生成轮次需求 diff + 基线履历)、合规基线(D 区)。
   清单类数据来源: features 读基线来源轮次, 其余读 system_baselines 快照(#272 后端 detail-section)。 */
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert, Button, Card, Descriptions, Empty, Modal, Space, Spin, Table, Tabs, Tag, Timeline,
  Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser, isSecuritySideRole } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import { DATA_LEVEL_COLOR, PRIORITY_COLOR } from './tokens'
import { LevelTag, RoundCell, SystemFormModal } from './SystemsPage'
import PageHeader from './PageHeader'
import { SystemComponentsCard, SystemInfraCard } from './system/SystemInventoryCards'
import type {
  BaselineApiEndpoint, BaselineDataAsset, BaselineDataTable, BaselinePermissionBundle,
  DetailSectionMeta, DiffRow, FilingRow, RoundSummary, SystemDetailFeature,
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

/** 清单类 Tab 未写回基线时的统一引导。 */
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

/* ── 功能清单 ─────────────────────────────────────── */

function FeaturesSection({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const categoryLabels = labelMapOf(enums, 'feature_categories')
  const sensitivityLabels = labelMapOf(enums, 'sensitivity_levels')
  const { meta, rows, loading, error, reload } = useSection<SystemDetailFeature[]>(useCallback(
    () => api.systemDetailFeatures(systemId), [systemId]))
  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (error) return <SectionError error={error} onRetry={reload} />
  if (!meta?.has_baseline) return <NoBaselineHint />
  return (
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
  )
}

/* ── 数据资产(资产 → 表 → 字段) ───────────────────── */

function DataAssetsSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselineDataAsset[]>(useCallback(
    () => api.systemDetailDataAssets(systemId), [systemId]))
  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (error) return <SectionError error={error} onRetry={reload} />
  if (!meta?.has_baseline) return <NoBaselineHint />
  return (
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
  )
}

/* ── 权限矩阵 ─────────────────────────────────────── */

function PermissionsSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselinePermissionBundle>(useCallback(
    () => api.systemDetailPermissions(systemId), [systemId]))
  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (error) return <SectionError error={error} onRetry={reload} />
  if (!meta?.has_baseline) return <NoBaselineHint />
  const bundle = rows ?? { roles: [], resources: [], permission_entries: [] }
  const roleNameOf = (uid?: string | null) =>
    bundle.roles.find((r) => r.uid === uid)?.name ?? uid ?? '—'
  const resourceNameOf = (uid?: string | null) =>
    bundle.resources.find((r) => r.uid === uid)?.name ?? uid ?? '—'
  return (
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
  )
}

/* ── 接口清单 ─────────────────────────────────────── */

function ApisSection({ systemId }: { systemId: number }) {
  const { meta, rows, loading, error, reload } = useSection<BaselineApiEndpoint[]>(useCallback(
    () => api.systemDetailApis(systemId), [systemId]))
  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (error) return <SectionError error={error} onRetry={reload} />
  if (!meta?.has_baseline) return <NoBaselineHint />
  return (
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
  )
}

/* ── 评估历史 ─────────────────────────────────────── */

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
      style={{ marginTop: 8 }}
      items={rounds.map((r, idx) => ({
        color: r.status === 'generated' ? 'green' : 'gray',
        children: (
          <div style={{ paddingBottom: idx === rounds.length - 1 ? 0 : 8 }}>
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
              <Button size="small" onClick={() => navigate(`/wizard/${r.project_id}`)}>
                {r.status === 'generated' ? '再编辑' : '继续填写'}
              </Button>
              {r.status === 'generated' && (
                <Button size="small" type="primary" ghost onClick={() => navigate(`/result/${r.project_id}`)}>
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

/** 旧载荷无 field_values 时的字段名中文兜底(与产物页口径一致)。 */
const DIFF_FIELD_FALLBACK_LABELS: Record<string, string> = {
  title: '需求标题', description: '需求内容', priority: '优先级',
  acceptance_criteria: '验收标准', category: '类目', regulatory_ref: '合规出处',
}

/* ── 页面容器 ─────────────────────────────────────── */

/** 基本信息 Tab: 描述区 + 定级来源 + 基础设施/组件清单卡(系统级, 各 Tab 中唯一直接编辑区)。 */
function OverviewSection({ system, enums }: {
  system: SystemRow
  enums: ReturnType<typeof useEnums>
}) {
  const typeLabels = labelMapOf(enums, 'project_types')
  const scaleLabels = labelMapOf(enums, 'user_scales')
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Descriptions size="small" column={3}>
        <Descriptions.Item label="系统编号">{system.code || '—'}</Descriptions.Item>
        <Descriptions.Item label="所属备案">
          {system.filing_name
            ? <Space size={6}>{system.filing_name}<LevelTag level={system.filing_level} /></Space>
            : <Typography.Text type="secondary">未挂备案(定级走评估问卷)</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="负责人">{system.owner_name || '—'}</Descriptions.Item>
        <Descriptions.Item label="用户规模">{scaleLabels[system.user_scale ?? ''] ?? (system.user_scale || '—')}</Descriptions.Item>
        <Descriptions.Item label="业务类型">
          {(system.types ?? []).map((t) => typeLabels[t] ?? t).join('、') || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="公网访问">
          {system.is_public ? <Tag color="orange">涉及公网</Tag> : <Tag>无公网</Tag>}
        </Descriptions.Item>
      </Descriptions>
      {system.filing_level && (
        <Alert
          type="info"
          showIcon
          message={`定级来源: 备案「${system.filing_name}」(等保${system.filing_level})`}
          description="向导中的定级问卷会预填备案定级; 若评估后人工调整了定级, 结果页会提示与备案不一致。"
        />
      )}
      <SystemInfraCard systemId={system.id} />
      <SystemComponentsCard systemId={system.id} />
    </Space>
  )
}

/** 合规基线 Tab(D 区): 级别变更确认待办 + 基线概要; 变更履历在「变动历史」Tab。 */
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
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="数据资产">{baseline.summary?.data_assets ?? 0}</Descriptions.Item>
          <Descriptions.Item label="数据字典表">{baseline.summary?.data_tables ?? 0}</Descriptions.Item>
          <Descriptions.Item label="API 清单">{baseline.summary?.api_endpoints ?? 0}</Descriptions.Item>
          <Descriptions.Item label="权限矩阵">
            角色 {baseline.summary?.roles ?? 0} · 资源 {baseline.summary?.resources ?? 0} ·
            授权 {baseline.summary?.permission_entries ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="来源轮次">
            {baseline.source_project_id
              ? <Button type="link" size="small" style={{ padding: 0 }}
                  onClick={() => navigate(`/result/${baseline.source_project_id}`)}>
                  第 {baseline.source_project_id} 轮评估
                </Button>
              : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="写回时间">
            {fmtDateTime(baseline.updated_at)}
            {baseline.updated_by ? ` · ${baseline.updated_by}` : ''}
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Typography.Text type="secondary">
          暂无安全基线。评估轮次终审通过后, 本轮资产/字典/权限/接口快照将写回为系统基线(v3.0 #225)。
        </Typography.Text>
      )}
    </Space>
  )
}

export default function SystemDetailPage({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const [system, setSystem] = useState<SystemRow | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [filings, setFilings] = useState<FilingRow[]>([])
  const [confirming, setConfirming] = useState(false)
  const isSecuritySide = isSecuritySideRole(getStoredUser()?.role)

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

  const reload = useCallback(() => {
    api.getSystem(systemId)
      .then(setSystem)
      .catch((e: Error) => message.error(e.message))
  }, [systemId])
  useEffect(reload, [reload])
  useEffect(() => { api.listFilings().then(setFilings).catch(() => undefined) }, [])

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
      navigate(`/wizard/${detail.id}`)
    } catch (e) {
      message.error((e as Error).message)
      setCreating(false)
    }
  }

  const rounds = system.rounds ?? []
  return (
    <div style={{ padding: 24, maxWidth: 1080, margin: '0 auto' }}>
      <PageHeader
        title={system.name}
        backLabel="返回清单"
        onBack={() => navigate('/systems')}
        extra={(
          <>
            <Button onClick={() => setEditing(true)}>编辑信息</Button>
            <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void startNewRound()}>
              发起新一轮评估
            </Button>
          </>
        )}
      />
      <Card variant="borderless">
        <Tabs items={[
          { key: 'overview', label: '基本信息', children: <OverviewSection system={system} enums={enums} /> },
          { key: 'features', label: '功能清单', children: <FeaturesSection systemId={system.id} /> },
          { key: 'data_assets', label: '数据资产', children: <DataAssetsSection systemId={system.id} /> },
          { key: 'permissions', label: '权限矩阵', children: <PermissionsSection systemId={system.id} /> },
          { key: 'apis', label: '接口清单', children: <ApisSection systemId={system.id} /> },
          { key: 'history', label: '评估历史', children: <HistorySection system={system} rounds={rounds} /> },
          { key: 'changes', label: '变动历史', children: <ChangesSection system={system} /> },
          { key: 'baseline', label: '合规基线', children: <BaselineSection system={system} confirming={confirming} onConfirm={confirmLevel} isSecuritySide={isSecuritySide} /> },
        ]} />
      </Card>

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
