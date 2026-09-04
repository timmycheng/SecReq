/* 产物页(Web 形式展示, 走查整改): 安全需求清单平铺(描述全文/来源中文/批量确认)、
   漏洞清单、组件与许可证、定级与策略说明; 每个视图可「复制到 Word」(HTML 剪贴板, 粘贴即排版)。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Key, ReactNode } from 'react'
import {
  Alert, Breadcrumb, Button, Card, Descriptions, Modal, Progress, Select, Space, Spin,
  Statistic, Table, Tabs, Tag, Tooltip, Typography, message,
} from 'antd'
import { CopyOutlined, DiffOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'

import { api, downloadFile } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import type {
  ComponentRow, DiffRow, ProjectDetail, RequirementDiff, RequirementRow, VulnerabilityRow,
} from '../types'
import { batchConfirm, confirmOne, unconfirmedAll, unconfirmedRegulatory } from './assist'
import GlossaryTip from './GlossaryTip'
import {
  copyRichHtml, docShell, requirementsSection, vulnsSection,
} from './wordExport'

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}


/** 漏洞严重度数值序(小=严重), 供汇聚取最高严重度(#95)。 */
const SEVERITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

/** 点分版本比较(宽松数字段), 无法解析时回退字符串比较。 */
function cmpVersion(a: string, b: string): number {
  const pa = a.split(/[.\-+_]/).map((x) => parseInt(x, 10) || 0)
  const pb = b.split(/[.\-+_]/).map((x) => parseInt(x, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d) return d
  }
  return a.localeCompare(b)
}

/** 把 "1)xx; 2)yy; 3)zz" 类编号文本拆成一行一条, 便于逐条核对。 */
function numberedToLines(text: string): string {
  return text
    .replace(/[;；]\s*(?=\d+[)）])/g, '\n')
    .replace(/。\s*(?=\d+[)）])/g, '\n')
}

interface VulnGroup {
  name: string
  version: string
  rows: VulnerabilityRow[]
  maxFix: string | null
}


type GradingBaseline = Awaited<ReturnType<typeof api.getGradingBaseline>>

export default function ResultPage({ projectId }: { projectId: number }) {
  const enums = useEnums()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[] | null>(null)
  const [vulns, setVulns] = useState<VulnerabilityRow[] | null>(null)
  const [vulnError, setVulnError] = useState<string | null>(null)
  const [components, setComponents] = useState<ComponentRow[]>([])
  const vulnGroups = useMemo<VulnGroup[]>(() => {
    const map = new Map<string, VulnGroup>()
    for (const v of vulns ?? []) {
      const key = `${v.component_name}@${v.component_version}`
      const g = map.get(key) ?? { name: v.component_name, version: v.component_version, rows: [], maxFix: null }
      g.rows.push(v)
      if (v.fix_version && (!g.maxFix || cmpVersion(v.fix_version, g.maxFix) > 0)) g.maxFix = v.fix_version
      map.set(key, g)
    }
    return [...map.values()]
  }, [vulns])
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>()
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [confirming, setConfirming] = useState(false)
  // 执行摘要(#156): 明细 Tabs 受控, 支持从摘要点击带筛选跳转
  const [tab, setTab] = useState('reqs')
  // 两轮增量对比(评估继承): 有上一轮已生成评估时展示"新增/移除/变更"摘要条
  const [diff, setDiff] = useState<RequirementDiff | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)
  // 需求清单横向滚动: 表格自身滚动容器(.ant-table-body)与吸底悬浮滚动条双向同步
  const reqWrapRef = useRef<HTMLDivElement>(null)
  const reqScrollEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const wrap = reqWrapRef.current
    if (!wrap) return
    const body = () => wrap.querySelector<HTMLElement>('.ant-table-body')
    const bar = () => wrap.querySelector<HTMLElement>('.req-h-scroll')
    const onScroll = (e: Event) => {
      const target = e.target
      if (!(target instanceof HTMLElement) || !target.classList.contains('ant-table-body')) return
      const el = bar()
      if (el) el.scrollLeft = target.scrollLeft
    }
    wrap.addEventListener('scroll', onScroll, true)
    // 表格底边进入视口后原生滚动条已可用, 悬浮条隐藏避免双滚动条; 无横向溢出(超宽屏)时同样隐藏(#144)
    // IO 负责布局变化(翻页/数据刷新), window scroll/resize 兜底滚动场景
    const updateBarVisibility = () => {
      const el = bar()
      const bodyEl = body()
      if (!el || !bodyEl) return
      const noOverflow = bodyEl.scrollWidth <= bodyEl.clientWidth
      el.style.display = noOverflow || bodyEl.getBoundingClientRect().bottom <= window.innerHeight + 1
        ? 'none' : 'block'
    }
    const io = new IntersectionObserver(updateBarVisibility)
    if (reqScrollEndRef.current) io.observe(reqScrollEndRef.current)
    window.addEventListener('scroll', updateBarVisibility, true)
    window.addEventListener('resize', updateBarVisibility)
    updateBarVisibility()
    return () => {
      wrap.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('scroll', updateBarVisibility, true)
      window.removeEventListener('resize', updateBarVisibility)
      io.disconnect()
    }
  }, [requirements])

  const priorityLabels = labelMapOf(enums, 'priority_labels')
  const severityLabels = labelMapOf(enums, 'severity_labels')
  const categoryLabels = labelMapOf(enums, 'category_labels')
  const riskMap = labelMapOf(enums, 'license_risk') as unknown as Record<string, { risk: string; label: string; note: string }>

  const reload = useCallback(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => message.error(e.message))
    api.listRequirements(projectId)
      .then(setRequirements)
      .catch((e: Error) => { setRequirements([]); message.error(e.message) })
    setVulnError(null)
    api.listVulnerabilities(projectId)
      .then(setVulns)
      .catch((e: Error) => { setVulns([]); setVulnError(e.message) })
    api.listComponents(projectId).then(setComponents).catch(() => setComponents([]))
    api.requirementsDiff(projectId).then(setDiff).catch(() => setDiff(null))
  }, [projectId])
  useEffect(() => { reload() }, [reload])

  /** 本轮命中的需求(未命中仅留档追溯, 不在清单与汇总中展现)。 */
  const hitAll = useMemo(() => (requirements ?? []).filter((r) => r.status !== 'obsolete'),
    [requirements])

  const filtered = useMemo(() => hitAll.filter((r) =>
    (!categoryFilter || r.category === categoryLabels[categoryFilter])
    && (!priorityFilter || r.priority === priorityFilter)),
    [hitAll, categoryFilter, priorityFilter, categoryLabels])

  if (!project || requirements === null) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 300 }}><Spin size="large" /></div>
  }

  const doConfirmOne = async (r: RequirementRow) => {
    try {
      await confirmOne(projectId, r.req_id)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const doBatchConfirm = async () => {
    if (!selectedKeys.length) { message.warning('请先勾选需求'); return }
    setConfirming(true)
    try {
      const body = await batchConfirm(projectId, selectedKeys.map(String))
      message.success(`已确认 ${body.confirmed} 条${body.missing.length ? `, 未找到 ${body.missing.length} 条` : ''}`)
      setSelectedKeys([])
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  const doBatchConfirmAll = async () => {
    setConfirming(true)
    try {
      const body = await batchConfirm(projectId, unconfirmedAll(hitAll).map((r) => r.req_id))
      message.success(`已确认 ${body.confirmed} 条`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  const copySection = async (title: string, html: string, plain: string) => {
    try {
      await copyRichHtml(html, plain)
      message.success(`「${title}」已复制, 到 Word 中 Ctrl+V 粘贴即可(保留标题/表格格式)`)
    } catch (e) {
      message.error(((e as Error).message || '复制失败, 请检查浏览器剪贴板权限'))
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: '0 auto' }}>
      {/* 生成总结块(#95): 一屏回答"这次生成了什么、风险在哪", 数字与下方清单同源 */}
      {requirements && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space size={[32, 12]} wrap style={{ justifyContent: 'center', width: '100%' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 600 }}>{hitAll.length}</div>
              <Typography.Text type="secondary">安全需求</Typography.Text>
              <div style={{ fontSize: 12, color: '#888' }}>
                {['critical', 'high', 'medium', 'low'].map((p) => {
                  const n = hitAll.filter((r) => r.priority === p).length
                  return n ? `${priorityLabels[p] ?? p}${n}` : null
                }).filter(Boolean).join(' · ')}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 600 }}>{components.length}</div>
              <Typography.Text type="secondary">组件</Typography.Text>
              <div style={{ fontSize: 12, color: '#888' }}>
                {(() => {
                  const risky = components.filter((c) => {
                    const lic = c.license ? riskMap[c.license] : undefined
                    return lic?.risk === 'high' || lic?.risk === 'medium'
                  }).length
                  return risky ? `${risky} 个许可证中高风险` : '许可证风险均可控'
                })()}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 600 }}>{vulns?.length ?? 0}</div>
              <Typography.Text type="secondary">漏洞记录</Typography.Text>
              <div style={{ fontSize: 12, color: '#888' }}>
                {vulns?.length ? ['critical', 'high', 'medium', 'low'].map((s) => {
                  const n = vulns.filter((v) => v.severity === s).length
                  return n ? `${severityLabels[s] ?? s}${n}` : null
                }).filter(Boolean).join(' · ') || '未命中' : '未查询'}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 600 }}>
                {hitAll.filter((r) => (r.regulatory_ref ?? []).length > 0).length}
              </div>
              <Typography.Text type="secondary">含合规依据</Typography.Text>
              <div style={{ fontSize: 12, color: '#888' }}>条目附监管文件条款引用</div>
            </div>
          </Space>
        </Card>
      )}

      {/* 执行摘要(#156): 结论先行 —— 先看结论与 Top 风险, 明细在下方 Tabs */}
      {hitAll.length > 0 && (
        <ExecutiveSummaryCard
          hitAll={hitAll}
          vulns={vulns ?? []}
          complianceTargets={project.compliance_targets ?? []}
          categoryLabels={categoryLabels}
          onPickReq={(r) => { setPriorityFilter(r.priority); setTab('reqs') }}
          onPickVuln={() => setTab('vulns')}
          onPickCategory={(code) => { setCategoryFilter(code); setTab('reqs') }}
        />
      )}

      {/* 与上一轮对比摘要条(评估继承 #151): 有变化时提示, 点击看明细 */}
      {diff?.comparable && diff.summary && (diff.summary.added > 0 || diff.summary.removed > 0 || diff.summary.changed > 0) && (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          icon={<DiffOutlined />}
          message={(
            <Space size={12} wrap>
              <span>
                与上一轮 <b>{diff.previous_project?.project_code}</b> 对比:
              </span>
              <Tag color="green">新增 {diff.summary.added}</Tag>
              <Tag color="red">移除 {diff.summary.removed}</Tag>
              <Tag color="gold">变更 {diff.summary.changed}</Tag>
              <Button size="small" onClick={() => setDiffOpen(true)}>查看明细</Button>
            </Space>
          )}
        />
      )}

      <Breadcrumb
        items={[
          { title: <a onClick={(e) => { e.preventDefault(); navigate('/') }}>项目列表</a> },
          {
            title: (
              <a onClick={(e) => { e.preventDefault(); navigate(`/wizard/${projectId}`) }}>
                {project.name}({project.code})
              </a>
            ),
          },
          { title: '生成产物' },
        ]}
      />

      <Space style={{ margin: '12px 0 16px' }} wrap>
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        <Button onClick={() => navigate(`/wizard/${projectId}`)}>返回向导修改</Button>
        <Button
          type="primary" ghost icon={<DownloadOutlined />}
          onClick={() => void downloadFile(`/api/projects/${projectId}/export/docx`,
            `${project.code}_安全需求说明书.docx`)}
        >
          下载 Word 文档
        </Button>
        <Button onClick={() => void downloadFile(`/api/projects/${projectId}/export/xlsx`)}>
          <DownloadOutlined /> 需求跟踪表.xlsx(Jira 可导入)
        </Button>
        <Button onClick={() => void downloadFile(`/api/projects/${projectId}/sbom`)}>
          <GlossaryTip term="sbom">SBOM JSON(CycloneDX 1.5)</GlossaryTip>
        </Button>
      </Space>

      {requirements.length === 0 && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          message="尚未生成安全需求基线"
          description={(
            <Space>
              <span>先在向导中完成信息采集, 再到「确认生成」页一键生成。</span>
              <Button type="primary" size="small" onClick={() => navigate(`/wizard/${projectId}`)}>
                前往向导
              </Button>
            </Space>
          )}
        />
      )}

      <Space size={16} style={{ display: 'flex', marginBottom: 16 }} wrap>
        <Card size="small" style={{ minWidth: 150 }}>
          <Statistic title="安全需求" value={hitAll.length} />
        </Card>
        <Card size="small" style={{ minWidth: 150 }}>
          <Statistic
            title="待确认"
            value={unconfirmedAll(hitAll).length}
            suffix={unconfirmedRegulatory(hitAll).length > 0
              ? `(报送 ${unconfirmedRegulatory(hitAll).length})` : undefined}
          />
        </Card>
        <Card size="small" style={{ minWidth: 150 }}>
          <Statistic title={<GlossaryTip term="osv">漏洞记录</GlossaryTip>} value={vulns?.length ?? 0} />
        </Card>
        {vulns && vulns.some((v) => v.severity === 'critical') && (
          <Alert type="error" showIcon style={{ flex: 1 }}
            message={`存在 ${vulns.filter((v) => v.severity === 'critical').length} 条严重漏洞, 请优先整改(详见漏洞清单)`} />
        )}
      </Space>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'reqs',
            label: `安全需求清单(${filtered.length})`,
            children: (
              <>
                <Space style={{ marginBottom: 12 }} wrap>
                  <Select
                    allowClear placeholder="按类目筛选" style={{ width: 200 }}
                    value={categoryFilter}
                    options={Object.entries(categoryLabels).map(([value, label]) => ({ value, label }))}
                    onChange={setCategoryFilter}
                  />
                  <Select
                    allowClear placeholder="按优先级筛选" style={{ width: 160 }}
                    value={priorityFilter}
                    options={Object.entries(priorityLabels).map(([value, label]) => ({ value, label }))}
                    onChange={setPriorityFilter}
                  />
                  <Button
                    size="small" icon={<CopyOutlined />}
                    onClick={() => void copySection(
                      '安全需求清单',
                      docShell(`${project.name} 安全需求清单`, [], requirementsSection(filtered, priorityLabels)),
                      '安全需求清单',
                    )}
                  >
                    本清单复制到 Word
                  </Button>
                </Space>
                <div ref={reqWrapRef} className="req-sticky-wrap">
                <Table<RequirementRow>
                  rowKey="req_id"
                  dataSource={filtered}
                  size="small"
                  scroll={{ x: 1920 }}
                  sticky
                  pagination={{
                    defaultPageSize: 10,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100],
                  }}
                  rowSelection={{
                    selectedRowKeys: selectedKeys,
                    onChange: setSelectedKeys,
                    selections: true,
                  }}
                  title={() => (
                    <Space size={12} wrap>
                      <span>已选 {selectedKeys.length} 条</span>
                      <Button size="small" type="primary" loading={confirming} onClick={() => void doBatchConfirm()}>
                        批量确认
                      </Button>
                      {unconfirmedAll(hitAll).length > 0 && (
                        <Button size="small" onClick={() => void doBatchConfirmAll()}>
                          确认全部 {unconfirmedAll(hitAll).length} 条待确认需求
                        </Button>
                      )}
                      <Typography.Text type="secondary">
                        标题/内容合并展示, 验收标准/触发来源分列; 确认动作替代责任人指派, 支持批量勾选
                      </Typography.Text>
                    </Space>
                  )}
                  columns={[
                    {
                      title: '优先级', dataIndex: 'priority', width: 72,
                      render: (p) => <Tag color={PRIORITY_COLOR[p]}>{priorityLabels[p] ?? p}</Tag>,
                    },
                    { title: '编号', dataIndex: 'req_id', width: 140 },
                    {
                      title: '需求标题/内容', dataIndex: 'title', width: 620,
                      render: (t, r) => (
                        <div>
                          <b>{t}</b>
                          <div style={{ color: '#555', whiteSpace: 'pre-line', marginTop: 2 }}>
                            {numberedToLines(r.description)}
                          </div>
                        </div>
                      ),
                    },
                    {
                      title: '验收标准', dataIndex: 'acceptance_criteria',
                      width: 320,
                      render: (a) => (
                        <div style={{ color: '#888', fontSize: 12, whiteSpace: 'pre-line' }}>
                          {numberedToLines(a)}
                        </div>
                      ),
                    },
                    {
                      title: '类目', dataIndex: 'category', width: 100,
                      render: (c) => <Tag>{c}</Tag>,
                    },
                    {
                      title: '触发来源', dataIndex: 'trigger_reason', width: 260,
                      render: (reason, r) => (
                        <div style={{ fontSize: 12 }}>
                          <div>{r.source_label
                            ?? (r.source_entity_type ? `${r.source_entity_type}#${r.source_entity_id}` : '来源未定位')}</div>
                          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                            {reason || '触发原因未记录(存量数据)'}
                          </Typography.Text>
                        </div>
                      ),
                    },
                    {
                      title: '合规依据', dataIndex: 'regulatory_ref', width: 260,
                      render: (refs: RequirementRow['regulatory_ref']) => (refs ?? []).length
                        ? (refs ?? []).map((ref, i) => (
                          <Tag key={i} color="blue" style={{ whiteSpace: 'normal' }}>
                            《{ref.file}》{ref.clause || ''}
                          </Tag>
                        ))
                        : '—',
                    },
                    {
                      title: '确认', dataIndex: 'reg_confirmed', width: 110, fixed: 'right',
                      render: (v: boolean, r) => (v
                        ? <Tag color="success">已确认{r.confirmed_by ? `·${r.confirmed_by}` : ''}</Tag>
                        : <Button size="small" type="link" onClick={() => void doConfirmOne(r)}>确认</Button>),
                    },
                  ]}
                  rowClassName={(r) => (r.priority === 'critical' ? 'row-critical' : '')}
                />
                {/* 表格底边哨兵: 进入视口即隐藏吸底悬浮条(原生滚动条已可用), 避免 double scrollbar(#144) */}
                <div ref={reqScrollEndRef} style={{ height: 1 }} />
                {/* 吸底悬浮横向滚动条: 行高较大时免去"翻到表格底部拖滚动条再翻回"; 宽度须与表格 scroll.x 一致 */}
                <div
                  className="req-h-scroll"
                  onScroll={(e) => {
                    const body = reqWrapRef.current?.querySelector<HTMLElement>('.ant-table-body')
                    if (body) body.scrollLeft = (e.target as HTMLElement).scrollLeft
                  }}
                  style={{
                    position: 'sticky', bottom: 0, zIndex: 30, background: '#fff',
                    overflowX: 'auto', overflowY: 'hidden', height: 14,
                  }}
                >
                  <div style={{ width: 1920, height: 1 }} />
                </div>
                </div>
              </>
            ),
          },
          {
            key: 'vulns',
            label: `漏洞清单(${vulns?.length ?? 0})`,
            children: vulnError ? (
              <Alert type="error" showIcon message={`漏洞数据加载失败: ${vulnError}`} />
            ) : (
              <>
                <Space style={{ marginBottom: 8 }}>
                  <Button size="small" icon={<CopyOutlined />}
                    onClick={() => void copySection(
                      '漏洞清单',
                      docShell(`${project.name} 漏洞清单`, [], vulnsSection(vulns ?? [])),
                      '漏洞清单',
                    )}
                  >
                    复制到 Word
                  </Button>
                </Space>
                <Table<VulnGroup>
                  rowKey={(g) => `${g.name}@${g.version}`}
                  dataSource={vulnGroups}
                  size="small"
                  pagination={false}
                  expandable={{
                    defaultExpandAllRows: false,
                    expandedRowRender: (g) => (
                      <Table<VulnerabilityRow>
                        rowKey={(r) => `${r.component_name}-${r.cve_id}`}
                        dataSource={g.rows}
                        size="small"
                        pagination={false}
                        columns={[
                          { title: '严重度', dataIndex: 'severity', width: 90,
                            render: (s) => <Tag color={SEVERITY_COLOR[s]}>{severityLabels[s] ?? s}</Tag> },
                          { title: <GlossaryTip term="cve_cvss">CVE</GlossaryTip>, dataIndex: 'cve_id', width: 170 },
                          { title: <GlossaryTip term="cve_cvss">CVSS</GlossaryTip>, dataIndex: 'cvss_score', width: 80, render: (v) => v ?? '—' },
                          { title: '受影响范围', dataIndex: 'affected_range' },
                          { title: '修复版本', dataIndex: 'fix_version',
                            render: (v) => v ? <Tag color="green">{v}</Tag> : '—' },
                          { title: '简述', dataIndex: 'summary', ellipsis: true },
                        ]}
                      />
                    ),
                  }}
                  columns={[
                    { title: '组件', render: (_v, g) => `${g.name}@${g.version}` },
                    { title: '漏洞数', width: 80, render: (_v, g) => g.rows.length },
                    { title: '最高严重度', width: 110,
                      render: (_v, g) => {
                        const worst = g.rows.reduce((acc, r) =>
                          (SEVERITY_RANK[r.severity] ?? 9) < (SEVERITY_RANK[acc] ?? 9) ? r.severity : acc, 'low')
                        return <Tag color={SEVERITY_COLOR[worst]}>{severityLabels[worst] ?? worst}</Tag>
                      } },
                    { title: '建议目标版本', width: 220,
                      render: (_v, g) => {
                        if (!g.maxFix) {
                          return <Tooltip title="各条记录均未提供修复版本(如 not_covered), 需人工评估, 不虚构目标版本">
                            <Tag color="orange">需人工评估</Tag>
                          </Tooltip>
                        }
                        const note = g.rows.some((r) => !r.fix_version) ? '(部分记录无修复版, 已取最高)' : undefined
                        return (
                          <Space size={4}>
                            <Tag color="green">升级到 {g.maxFix}</Tag>
                            {note && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{note}</Typography.Text>}
                          </Space>
                        )
                      } },
                    { title: '处置结论', render: (_v, g) =>
                      `将 ${g.name} 从 ${g.version} 升级到 ${g.maxFix ?? '(人工评估)'}, 可消除以下 ${g.rows.length} 条已知漏洞` },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'sbom',
            label: `组件与许可证(${components.length})`,
            children: (
              <>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                  许可证风险来自内置风险库(强传染 Copyleft 为高风险, 生成时会触发合规评估需求)。
                </Typography.Text>
                <Table<ComponentRow>
                  rowKey={(r) => `${r.name}@${r.version}`}
                  dataSource={components}
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '层级', dataIndex: 'layer', width: 100,
                      render: (v) => <Tag>{labelMapOf(enums, 'sbom_layers')[v] ?? v}</Tag> },
                    { title: '组件', render: (_v, r) => `${r.name}@${r.version}` },
                    { title: '许可证', dataIndex: 'license', width: 230,
                      render: (lic: string | null) => {
                        if (!lic) return '—'
                        const info = riskMap[lic]
                        return (
                          <Space size={4}>
                            <span>{lic}</span>
                            {info && (
                              <Tag color={info.risk === 'high' ? 'red' : info.risk === 'medium' ? 'orange' : 'green'}>
                                {info.label}
                              </Tag>
                            )}
                          </Space>
                        )
                      } },
                    { title: '来源', dataIndex: 'source_type', width: 110,
                      render: (v) => (v === 'sbom_file' ? <Tag color="purple">SBOM文件</Tag> : <Tag>手工录入</Tag>) },
                    { title: '漏洞', width: 140, render: (_v, r) => {
                      const all = r.vulnerabilities ?? []
                      const high = all.filter((v) => v.severity === 'critical' || v.severity === 'high').length
                      const ambiguous = r.vuln_status === 'hit' && Boolean(r.vuln_status_note)
                      if (!all.length) return '—'
                      return (
                        <Space size={4}>
                          {high ? <Tag color="red">{high} 高危</Tag> : <Tag>{all.length}</Tag>}
                          {/* 疑似命中(带说明)与普通命中区分展示, 避免误导(#96 附带核查) */}
                          {ambiguous && <Tooltip title={r.vuln_status_note}><Tag color="orange">疑似</Tag></Tooltip>}
                        </Space>
                      )
                    } },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'grading',
            label: '定级与策略',
            children: <GradingView projectId={projectId} project={project} />,
          },
        ]}
      />

      <Modal
        title={`与上一轮(${diff?.previous_project?.project_code ?? ''})需求对比明细`}
        open={diffOpen}
        onCancel={() => setDiffOpen(false)}
        footer={<Button onClick={() => setDiffOpen(false)}>关闭</Button>}
        width={860}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <DiffSection
            title={(<Tag color="green">新增 {diff?.added?.length ?? 0}</Tag>)}
            rows={diff?.added ?? []}
          />
          <DiffSection
            title={(<Tag color="red">移除 {diff?.removed?.length ?? 0}</Tag>)}
            rows={diff?.removed ?? []}
          />
          {(diff?.changed?.length ?? 0) > 0 && (
            <div>
              <Space><Tag color="gold">变更 {diff!.changed!.length}</Tag></Space>
              <div style={{ marginTop: 8 }}>
                {diff!.changed!.map((c) => (
                  <Card size="small" key={c.current.req_id} style={{ marginBottom: 8 }}>
                    <Space size={8} wrap>
                      <Typography.Text code>{c.current.req_id}</Typography.Text>
                      <b>{c.current.title}</b>
                      {c.fields.map((f) => <Tag key={f}>{f}</Tag>)}
                    </Space>
                    <div style={{ color: '#888', marginTop: 4, fontSize: 12 }}>
                      原优先级: {priorityLabels[c.previous.priority] ?? c.previous.priority}
                      → 现: {priorityLabels[c.current.priority] ?? c.current.priority}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </Space>
      </Modal>
    </div>
  )
}

/** 对比明细小表: 新增/移除需求列表。 */
function DiffSection({ title, rows }: { title: ReactNode; rows: DiffRow[] }) {
  if (!rows.length) return null
  return (
    <div>
      <Space>{title}</Space>
      <Table<DiffRow>
        style={{ marginTop: 8 }}
        rowKey="req_id"
        size="small"
        dataSource={rows}
        pagination={false}
        columns={[
          { title: '编号', dataIndex: 'req_id', width: 150 },
          { title: '需求标题', dataIndex: 'title' },
          { title: '优先级', dataIndex: 'priority', width: 90,
            render: (v: string) => <Tag>{v}</Tag> },
          { title: '来源', dataIndex: 'source_label', ellipsis: true },
        ]}
      />
    </div>
  )
}

/** 合规目标 → 监管文件关键词(执行摘要的合规覆盖统计用, 与知识库出处口径一致)。 */
const COMPLIANCE_FILE_KEYWORDS: Record<string, string> = {
  djcp_l3: '等级保护',
  pipl: '个人信息',
  pci_dss: 'PCI',
}

const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

/** 执行摘要(#156): 自动结论 + Top 风险 + 合规覆盖 + 类目分布。
    金字塔第一层——审阅者 30 秒内得到"能不能过、先看什么", 点击任意条目联动下方明细筛选。 */
function ExecutiveSummaryCard({ hitAll, vulns, complianceTargets, categoryLabels, onPickReq, onPickVuln, onPickCategory }: {
  hitAll: RequirementRow[]
  vulns: VulnerabilityRow[]
  complianceTargets: string[]
  categoryLabels: Record<string, string>
  onPickReq: (r: RequirementRow) => void
  onPickVuln: () => void
  onPickCategory: (code: string) => void
}) {
  const critReqs = hitAll.filter((r) => r.priority === 'critical')
  const highReqs = hitAll.filter((r) => r.priority === 'high')
  const critVulns = vulns.filter((v) => v.severity === 'critical')
  const highVulns = vulns.filter((v) => v.severity === 'high')
  const openReqs = hitAll.filter((r) => r.status === 'open').length

  // 自动结论: 按 critical/high 的需求与漏洞分档, 不做人工填写
  const conclusion = (() => {
    if (critReqs.length || critVulns.length) {
      return {
        type: 'error' as const,
        text: `不建议直接通过: 存在 ${critReqs.length} 条关键需求与 ${critVulns.length} 个严重漏洞`,
        detail: '关键项为硬性安全要求, 建议整改闭环后复评; 详见下方 Top 风险。',
      }
    }
    if (highReqs.length || highVulns.length) {
      return {
        type: 'warning' as const,
        text: `有条件通过: 无关键(critical)项, 有 ${highReqs.length} 条高优先级需求与 ${highVulns.length} 个高危漏洞`,
        detail: '建议按下方 Top 风险排期整改, 其余需求按建议阶段落实。',
      }
    }
    return {
      type: 'success' as const,
      text: `基线整体可控: ${hitAll.length} 条需求均非 critical/high`,
      detail: '按建议阶段落实即可, 无需额外整改决策。',
    }
  })()

  const topReqs = [...critReqs, ...highReqs]
    .sort((a, b) => (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9))
    .slice(0, 5)
  const topVulns = [...critVulns, ...highVulns]
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9))
    .slice(0, 3)

  // 类目分布: 需求行的 category 存的是中文标签, 反查 code 供筛选联动
  const labelToCode = Object.fromEntries(
    Object.entries(categoryLabels).map(([code, label]) => [label, code]),
  )
  const catCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const r of hitAll) map.set(r.category, (map.get(r.category) ?? 0) + 1)
    return [...map.entries()].sort((a, b) => b[1] - a[1])
  }, [hitAll])
  const catMax = catCounts[0]?.[1] ?? 1

  const coverage = complianceTargets.map((code) => {
    const keyword = COMPLIANCE_FILE_KEYWORDS[code]
    const count = keyword
      ? hitAll.filter((r) => (r.regulatory_ref ?? []).some((f) => (f.file ?? '').includes(keyword))).length
      : 0
    return { code, label: categoryLabels[code] ?? code, count }
  })

  return (
    <Card size="small" title="执行摘要" style={{ marginBottom: 16 }}>
      <Alert
        type={conclusion.type}
        showIcon
        message={conclusion.text}
        description={conclusion.detail}
        style={{ marginBottom: 16 }}
      />
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: '2 1 380px', minWidth: 320 }}>
          <Typography.Text type="secondary" strong>Top 风险需求(点击查看)</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {topReqs.length === 0 && <Typography.Text type="secondary">无 critical/high 需求</Typography.Text>}
            {topReqs.map((r) => (
              <div
                key={r.req_id}
                onClick={() => onPickReq(r)}
                style={{ padding: '4px 0', cursor: 'pointer', borderBottom: '1px dashed #f0f0f0' }}
              >
                <Space size={8} wrap>
                  <Tag color={PRIORITY_COLOR[r.priority]}>{r.priority === 'critical' ? '紧急' : '高'}</Tag>
                  <Typography.Text code style={{ fontSize: 12 }}>{r.req_id}</Typography.Text>
                  <Typography.Text style={{ fontSize: 13 }}>{r.title}</Typography.Text>
                </Space>
              </div>
            ))}
          </div>
          {topVulns.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Typography.Text type="secondary" strong>严重/高危漏洞</Typography.Text>
              <div style={{ marginTop: 8 }}>
                {topVulns.map((v) => (
                  <div
                    key={v.cve_id}
                    onClick={onPickVuln}
                    style={{ padding: '3px 0', cursor: 'pointer', borderBottom: '1px dashed #f0f0f0' }}
                  >
                    <Space size={8} wrap>
                      <Tag color={SEVERITY_COLOR[v.severity]}>{v.severity === 'critical' ? '严重' : '高危'}</Tag>
                      <Typography.Text code style={{ fontSize: 12 }}>{v.cve_id}</Typography.Text>
                      <Typography.Text style={{ fontSize: 13 }}>{v.component_name}@{v.component_version}</Typography.Text>
                    </Space>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div style={{ flex: '1 1 260px', minWidth: 260 }}>
          <Typography.Text type="secondary" strong>合规目标覆盖</Typography.Text>
          <div style={{ marginTop: 8, marginBottom: 16 }}>
            {coverage.length === 0 && <Typography.Text type="secondary">未勾选合规目标</Typography.Text>}
            {coverage.map((c) => (
              <div key={c.code} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <Typography.Text style={{ fontSize: 13 }}>{c.label}</Typography.Text>
                {c.count > 0
                  ? <Tag color="green">{c.count} 条</Tag>
                  : <Tag>未直接命中</Tag>}
              </div>
            ))}
          </div>
          <Typography.Text type="secondary" strong>需求类目分布(点击筛选)</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {catCounts.map(([label, count]) => (
              <div
                key={label}
                onClick={() => onPickCategory(labelToCode[label] ?? label)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', cursor: 'pointer' }}
              >
                <span style={{ width: 96, fontSize: 12, color: '#555', flexShrink: 0 }}>{label}</span>
                <Progress
                  percent={Math.max(6, Math.round((count / catMax) * 100))}
                  showInfo={false}
                  size="small"
                  strokeColor="#2f5597"
                  style={{ flex: 1, margin: 0 }}
                />
                <span style={{ width: 28, fontSize: 12, textAlign: 'right' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {openReqs > 0 && (
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
          其中 {openReqs} 条尚未闭环(状态为待落实); 闭环进度见需求跟踪表。
        </Typography.Text>
      )}
    </Card>
  )
}

/** 定级与策略说明视图(原定级建议书核心信息的 Web 形态)。 */
function GradingView({ projectId, project }: {
  projectId: number
  project: ProjectDetail
}) {
  const [baseline, setBaseline] = useState<GradingBaseline | null>(null)
  const enums = useEnums()

  useEffect(() => {
    api.getGradingBaseline(projectId).then(setBaseline).catch(() => undefined)
  }, [projectId])

  if (!baseline) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  const pwd = baseline.pwd_defaults

  return (
    <div style={{ maxWidth: 900 }}>
      <Descriptions
        bordered size="small" column={1}
        items={[
          { key: 'level', label: '有效定级',
            children: project.grading_level ? <Tag color="blue">等保{project.grading_level}</Tag> : '未定级' },
          {
            key: 'policy', label: '密码与会话基线',
            children: pwd
              ? `最小长度 ${pwd.pwd_min_length} · 复杂度 ${pwd.pwd_complexity}/4 类 · 有效期 ${pwd.pwd_valid_days} 天 · ` +
                `锁定阈值 ${pwd.lockout_threshold} 次 · 会话超时 ${pwd.session_timeout_min} 分钟`
              : '—',
          },
          { key: 'methods', label: '认证方式', children: '按第 1 步登记(默认账密登录), 可回向导修改' },
          {
            key: 'targets', label: '合规目标',
            children: (project.compliance_targets ?? []).map((c) => labelMapOf(enums, 'compliance_targets')[c] ?? c).join('、') || '—',
          },
          { key: 'count', label: '基线要求数', children: `${baseline.requirements.length} 条(合规/报送/策略类)` },
        ]}
      />
      <Typography.Title level={5} style={{ margin: '20px 0 8px' }}>
        定级与合规目标触发的基线要求(生成时将包含)
      </Typography.Title>
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {baseline.requirements.map((r) => (
          <Card size="small" key={r.req_id}>
            <Space size={8} wrap>
              <Tag>{r.category}</Tag>
              <b>{r.title}</b>
            </Space>
            <div style={{ color: '#555', marginTop: 4, whiteSpace: 'pre-wrap' }}>{r.description}</div>
          </Card>
        ))}
      </Space>
    </div>
  )
}
