/* 产物页: 安全需求清单(可筛选)/漏洞清单(高危标红)/文档下载(5 Word + SBOM + Excel)/门禁入口。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Breadcrumb, Button, Card, Input, Modal, Select, Space, Spin, Statistic,
  Table, Tabs, Tag, Typography, message,
} from 'antd'
import {
  DownloadOutlined, ReloadOutlined, SafetyOutlined, ThunderboltOutlined,
} from '@ant-design/icons'

import { api, downloadUrl } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import type {
  GateRow, ProjectDetail, RequirementRow, VulnerabilityRow,
} from '../types'
import GlossaryTip from './GlossaryTip'
import { batchConfirmRegulatory, batchSetOwner, criticalWithoutOwner, unconfirmedRegulatory } from './assist'

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}

const DOC_ITEMS = [
  { key: 'grading', name: '系统定级建议书.docx' },
  { key: 'requirement', name: '需求规格说明书_安全需求章节.docx' },
  { key: 'design', name: '总体设计说明书_安全设计章节.docx' },
  { key: 'sbom_vuln', name: 'SBOM及漏洞清单.docx' },
  { key: 'review', name: '项目安全评审表.docx(评审会材料)' },
]

export default function ResultPage({ projectId }: { projectId: number }) {
  const enums = useEnums()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[] | null>(null)
  const [vulns, setVulns] = useState<VulnerabilityRow[] | null>(null)
  const [vulnError, setVulnError] = useState<string | null>(null)
  const [gates, setGates] = useState<GateRow[]>([])
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>()

  const reload = useCallback(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => message.error(e.message))
    api.listRequirements(projectId)
      .then(setRequirements)
      .catch((e: Error) => { setRequirements([]); message.error(e.message) })
    setVulnError(null)
    api.listVulnerabilities(projectId)
      .then(setVulns)
      .catch((e: Error) => { setVulns([]); setVulnError(e.message) })
    api.listGates(projectId).then(setGates).catch(() => setGates([]))
  }, [projectId])
  useEffect(() => { reload() }, [reload])

  if (!project || requirements === null) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 300 }}><Spin size="large" /></div>
  }

  const confirmReg = async (r: RequirementRow) => {
    try {
      await api.confirmRegulatory(projectId, r.req_id)
      message.success(`已确认报送事项 ${r.req_id}`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const filtered = requirements.filter((r) =>
    (!categoryFilter || r.category === categoryLabel(enums, categoryFilter))
    && (!priorityFilter || r.priority === priorityFilter))

  return (
    <div style={{ padding: 24 }}>
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
        <Button type="primary" ghost icon={<SafetyOutlined />}
          onClick={() => navigate(`/review/${projectId}`)}>
          评审门禁与签核
        </Button>
        <Button onClick={() => downloadUrl(`/api/projects/${projectId}/export/xlsx`)}>
          <DownloadOutlined /> 需求跟踪表.xlsx(Jira 可导入)
        </Button>
        <Button onClick={() => downloadUrl(`/api/projects/${projectId}/sbom`)}>
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
              <span>先在向导中完成信息采集, 再到第 9 步「确认生成」页一键生成。</span>
              <Button type="primary" size="small" onClick={() => navigate(`/wizard/${projectId}`)}>
                前往向导
              </Button>
            </Space>
          )}
        />
      )}

      <Space size={16} style={{ display: 'flex', marginBottom: 16 }} wrap>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title="安全需求" value={requirements.length} />
        </Card>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title="紧急/高优先级"
            value={requirements.filter((r) => r.priority === 'critical' || r.priority === 'high').length} />
        </Card>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title={<GlossaryTip term="osv">漏洞记录</GlossaryTip>} value={vulns?.length ?? 0} />
        </Card>
        {vulns && vulns.some((v) => v.severity === 'critical') && (
          <Alert type="error" showIcon style={{ flex: 1 }}
            message={`存在 ${vulns.filter((v) => v.severity === 'critical').length} 条严重漏洞, 请优先整改(详见漏洞清单)`} />
        )}
      </Space>

      {gates.length > 0 && (
        <Card
          size="small"
          title="下一步做什么(按当前进度自动提示)"
          style={{ marginBottom: 16 }}
          extra={(
            <Button size="small" type="primary" ghost onClick={() => navigate(`/review/${projectId}`)}>
              进入安全评审 →
            </Button>
          )}
        >
          <Space size={[10, 8]} wrap align="center">
            {gates.filter((g) => ['initiation', 'requirement', 'design'].includes(g.gate_type)).map((g) => (
              <Tag
                key={g.gate_type}
                color={g.status === 'passed' ? 'success' : g.status === 'in_review' ? 'processing' : g.check.status === 'blocked' ? 'error' : 'default'}
              >
                {g.gate_label}: {g.status_label}
              </Tag>
            ))}
            <NextStepHint
              projectId={projectId}
              gates={gates}
              requirements={requirements}
              pmName={project.pm_name ?? ''}
              onDone={reload}
            />
          </Space>
        </Card>
      )}

      {/* ── 文档下载区 ── */}
      <Card size="small" title="生成产物下载" style={{ marginBottom: 16 }}>
        <Space wrap>
          {DOC_ITEMS.map((doc) => (
            <Button key={doc.key} type="primary" ghost icon={<DownloadOutlined />}
              onClick={() => downloadUrl(`/api/projects/${projectId}/export/docx/${doc.key}`)}>
              {doc.name}
            </Button>
          ))}
        </Space>
        <p style={{ color: '#888', fontSize: 13, margin: '8px 0 0' }}>
          5 份 Word 按库内最新数据即时重渲染; 跟踪表字段与 Jira 外部导入兼容(附映射说明 Sheet)。
        </p>
        {(project.counts.vulnerabilities ?? 0) === 0 && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon
            message="提示: 本次生成未包含在线漏洞数据; 在向导确认页开启「在线查询 OSV.dev」后重新生成即可。" />
        )}
      </Card>

      <Tabs
        defaultActiveKey="reqs"
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
                    options={Object.entries(labelMapOf(enums, 'category_labels')).map(([value, label]) => ({ value, label }))}
                    onChange={setCategoryFilter}
                  />
                  <Select
                    allowClear placeholder="按优先级筛选" style={{ width: 160 }}
                    value={priorityFilter}
                    options={Object.entries(labelMapOf(enums, 'priority_labels')).map(([value, label]) => ({ value, label }))}
                    onChange={setPriorityFilter}
                  />
                  <span style={{ color: '#888' }}>展开任意一行可看验收标准与触发原因(可追溯到输入项)</span>
                </Space>
                <Table<RequirementRow>
                  rowKey="id"
                  dataSource={filtered}
                  size="small"
                  pagination={{ pageSize: 20 }}
                  expandable={{
                    expandedRowRender: (r) => (
                      <div style={{ margin: 0 }}>
                        <p><b>验收标准:</b> {r.acceptance_criteria}</p>
                        <p><b>触发原因:</b> {r.trigger_reason}</p>
                        <p>
                          <b>来源:</b> {r.source_entity_type}#{r.source_entity_id} ·{' '}
                          <GlossaryTip term="asvs">ASVS</GlossaryTip> {r.asvs_ref ?? '—'} · 模板 {r.template_id}
                        </p>
                        <p>
                          <b>合规依据:</b>{' '}
                          {(r.regulatory_ref ?? []).length
                            ? (r.regulatory_ref ?? []).map((ref, i) => (
                              <Tag key={i} color="blue">
                                《{ref.file}》{ref.clause || ''}{ref.note ? `(待合规确认)` : ''}
                              </Tag>
                            ))
                            : '—'}
                        </p>
                        <Space size={8} wrap>
                          {(r.priority === 'critical') && (
                            <OwnerInput projectId={projectId} req={r} onDone={reload} />
                          )}
                          {r.category === '监管报送' && !r.reg_confirmed && (
                            <Button size="small" type="primary" ghost
                              onClick={() => void confirmReg(r)}>
                              确认该报送事项(立项门禁要求)
                            </Button>
                          )}
                        </Space>
                      </div>
                    ),
                  }}
                  columns={[
                    {
                      title: '优先级', dataIndex: 'priority', width: 80,
                      render: (p) => <Tag color={PRIORITY_COLOR[p]}>{labelMapOf(enums, 'priority_labels')[p] ?? p}</Tag>,
                    },
                    { title: '编号', dataIndex: 'req_id', width: 150 },
                    {
                      title: '需求标题', dataIndex: 'title',
                      render: (t, r) => (
                        <div>
                          <b>{t}</b>
                          <div style={{ color: '#666', fontSize: 12 }}>{r.description.slice(0, 80)}{r.description.length > 80 ? '…' : ''}</div>
                        </div>
                      ),
                    },
                    { title: '类目', dataIndex: 'category', width: 130 },
                    { title: '建议阶段', dataIndex: 'suggested_phase', width: 100,
                      render: (p) => labelMapOf(enums, 'requirement_phases')[p] ?? p },
                    {
                      title: '责任人', dataIndex: 'owner', width: 110,
                      render: (v: string | null, r) => v ?? (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {r.priority === 'critical' ? '未指定(阻塞需求门禁)' : '—'}
                        </Typography.Text>
                      ),
                    },
                    {
                      title: '报送确认', dataIndex: 'reg_confirmed', width: 100,
                      render: (_v: boolean, r) => (r.category === '监管报送'
                        ? (r.reg_confirmed ? <Tag color="success">已确认</Tag> : <Tag color="error">未确认</Tag>)
                        : '—'),
                    },
                  ]}
                  rowClassName={(r) => (r.priority === 'critical' ? 'row-critical' : '')}
                />
              </>
            ),
          },
          {
            key: 'vulns',
            label: `漏洞清单(${vulns?.length ?? 0})`,
            children: vulnError ? (
              <Alert type="error" showIcon message={`漏洞数据加载失败: ${vulnError}`} />
            ) : (
              <Table<VulnerabilityRow>
                rowKey={(r) => `${r.component_name}-${r.cve_id}`}
                dataSource={vulns ?? []}
                size="small"
                pagination={false}
                columns={[
                  { title: '严重度', dataIndex: 'severity', width: 90,
                    render: (s) => <Tag color={SEVERITY_COLOR[s]}>{labelMapOf(enums, 'severity_labels')[s] ?? s}</Tag> },
                  { title: <GlossaryTip term="cve_cvss">CVE</GlossaryTip>, dataIndex: 'cve_id', width: 170 },
                  { title: '组件', render: (_v, r) => `${r.component_name}@${r.component_version}`, width: 220 },
                  { title: <GlossaryTip term="cve_cvss">CVSS</GlossaryTip>, dataIndex: 'cvss_score', width: 80, render: (v) => v ?? '—' },
                  { title: '受影响范围', dataIndex: 'affected_range' },
                  { title: '修复版本', dataIndex: 'fix_version',
                    render: (v) => v ? <Tag color="green">{v}</Tag> : '—' },
                  { title: '简述', dataIndex: 'summary', ellipsis: true },
                ]}
              />
            ),
          },
        ]}
      />
    </div>
  )
}

function categoryLabel(enums: ReturnType<typeof useEnums>, code: string): string {
  return labelMapOf(enums, 'category_labels')[code] ?? code
}

/** 下一步指引: 按门禁校验缺口给出一句提示 + 一键修复按钮。 */
function NextStepHint({ projectId, gates, requirements, pmName, onDone }: {
  projectId: number
  gates: GateRow[]
  requirements: RequirementRow[]
  pmName: string
  onDone: () => void
}) {
  const regTodo = unconfirmedRegulatory(requirements)
  const ownerTodo = criticalWithoutOwner(requirements)
  const activeTypes = ['initiation', 'requirement', 'design']
  const firstBlocked = gates.find((g) => activeTypes.includes(g.gate_type) && g.check.status === 'blocked')
  const submittable = gates.filter(
    (g) => activeTypes.includes(g.gate_type)
      && g.check.status === 'passed' && g.status !== 'passed' && g.status !== 'in_review',
  )
  const allPassed = gates.filter((g) => activeTypes.includes(g.gate_type)).every((g) => g.status === 'passed')

  const confirmAll = async () => {
    try {
      const n = await batchConfirmRegulatory(projectId, requirements)
      message.success(`已确认 ${n} 条报送事项`)
      onDone()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const fixOwners = () => {
    let owner = pmName || '王建国'
    Modal.confirm({
      title: `为 ${ownerTodo.length} 条紧急需求统一指定责任人`,
      content: (
        <div style={{ marginTop: 12 }}>
          <Input defaultValue={owner} onChange={(e) => { owner = e.target.value }} />
        </div>
      ),
      okText: '确认指定',
      cancelText: '取消',
      onOk: async () => {
        if (!owner.trim()) { message.warning('请输入责任人'); return }
        try {
          const n = await batchSetOwner(projectId, requirements, owner.trim())
          message.success(`已为 ${n} 条紧急需求指定责任人 ${owner.trim()}`)
          onDone()
        } catch (e) {
          message.error((e as Error).message)
        }
      },
    })
  }

  if (allPassed) {
    return <Typography.Text>🎉 三个门禁全部通过, 可在评审会使用《项目安全评审表》。</Typography.Text>
  }
  if (firstBlocked) {
    return (
      <Space size={8} wrap>
        <Typography.Text>
          评审材料还差:
          {regTodo.length > 0 && <b> {regTodo.length} 条报送事项待确认</b>}
          {regTodo.length > 0 && ownerTodo.length > 0 && <span>、</span>}
          {ownerTodo.length > 0 && <b>{ownerTodo.length} 条紧急需求待指定责任人</b>}
          , 一键补齐:
        </Typography.Text>
        {regTodo.length > 0 && (
          <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={() => void confirmAll()}>
            一键确认报送事项
          </Button>
        )}
        {ownerTodo.length > 0 && (
          <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={fixOwners}>
            一键指定责任人
          </Button>
        )}
      </Space>
    )
  }
  if (submittable.length > 0) {
    return (
      <Typography.Text>
        ✓ 评审材料已齐, 可提交评审({submittable.map((g) => g.gate_label).join('、')}) —— 点右上角「进入安全评审」。
      </Typography.Text>
    )
  }
  return <Typography.Text type="secondary">门禁流程推进中, 点右上角「进入安全评审」查看进度。</Typography.Text>
}

/** critical 需求责任人指派(需求门禁要求非空)。 */
function OwnerInput({ projectId, req, onDone }: {
  projectId: number
  req: RequirementRow
  onDone: () => void
}) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  if (req.owner) return <Tag color="green">责任人: {req.owner}</Tag>
  return (
    <Space size={6}>
      <Input
        size="small" style={{ width: 140 }} placeholder="责任人姓名/工号"
        value={value} onChange={(e) => setValue(e.target.value)}
      />
      <Button
        size="small" loading={saving}
        onClick={async () => {
          if (!value.trim()) { message.warning('请输入责任人'); return }
          setSaving(true)
          try {
            await api.setRequirementOwner(projectId, req.req_id, value.trim())
            message.success(`已指定 ${req.req_id} 责任人: ${value.trim()}`)
            setValue('')
            onDone()
          } catch (e) {
            message.error((e as Error).message)
          } finally {
            setSaving(false)
          }
        }}
      >
        指定责任人
      </Button>
    </Space>
  )
}
