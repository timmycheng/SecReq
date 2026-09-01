/* 产物页(Web 形式展示, 走查整改): 安全需求清单平铺(描述全文/来源中文/批量确认)、
   漏洞清单、组件与许可证、定级与策略说明; 每个视图可「复制到 Word」(HTML 剪贴板, 粘贴即排版)。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import {
  Alert, Breadcrumb, Button, Card, Descriptions, Select, Space, Spin,
  Statistic, Table, Tabs, Tag, Tooltip, Typography, message,
} from 'antd'
import { CopyOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'

import { api, downloadFile } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import type { ComponentRow, ProjectDetail, RequirementRow, VulnerabilityRow } from '../types'
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

type GradingBaseline = Awaited<ReturnType<typeof api.getGradingBaseline>>

export default function ResultPage({ projectId }: { projectId: number }) {
  const enums = useEnums()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[] | null>(null)
  const [vulns, setVulns] = useState<VulnerabilityRow[] | null>(null)
  const [vulnError, setVulnError] = useState<string | null>(null)
  const [components, setComponents] = useState<ComponentRow[]>([])
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>()
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [confirming, setConfirming] = useState(false)

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
  }, [projectId])
  useEffect(() => { reload() }, [reload])

  const filtered = useMemo(() => (requirements ?? []).filter((r) =>
    (!categoryFilter || r.category === categoryLabels[categoryFilter])
    && (!priorityFilter || r.priority === priorityFilter)),
    [requirements, categoryFilter, priorityFilter, categoryLabels])

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
      const body = await batchConfirm(projectId, unconfirmedAll(requirements).map((r) => r.req_id))
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
          <Statistic title="安全需求" value={requirements.length} />
        </Card>
        <Card size="small" style={{ minWidth: 150 }}>
          <Statistic
            title="待确认"
            value={unconfirmedAll(requirements).length}
            suffix={unconfirmedRegulatory(requirements).length > 0
              ? `(报送 ${unconfirmedRegulatory(requirements).length})` : undefined}
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
                <Table<RequirementRow>
                  rowKey="req_id"
                  dataSource={filtered}
                  size="small"
                  pagination={{ pageSize: 15, showSizeChanger: false }}
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
                      {unconfirmedAll(requirements).length > 0 && (
                        <Button size="small" onClick={() => void doBatchConfirmAll()}>
                          确认全部 {unconfirmedAll(requirements).length} 条待确认需求
                        </Button>
                      )}
                      <Typography.Text type="secondary">
                        需求全文平铺展示; 确认动作替代责任人指派, 支持批量勾选
                      </Typography.Text>
                    </Space>
                  )}
                  columns={[
                    {
                      title: '优先级', dataIndex: 'priority', width: 80,
                      render: (p) => <Tag color={PRIORITY_COLOR[p]}>{priorityLabels[p] ?? p}</Tag>,
                    },
                    { title: '编号', dataIndex: 'req_id', width: 145 },
                    {
                      title: '需求内容(全文)', dataIndex: 'title',
                      render: (t, r) => (
                        <div>
                          <b>{t}</b>
                          <div style={{ color: '#555', whiteSpace: 'pre-wrap', marginTop: 2 }}>{r.description}</div>
                          <div style={{ color: '#888', marginTop: 4, fontSize: 12 }}>
                            <b>验收标准:</b> {r.acceptance_criteria}
                          </div>
                        </div>
                      ),
                    },
                    {
                      title: '类目/来源', dataIndex: 'category', width: 175,
                      render: (c, r) => (
                        <div>
                          <div>{c}</div>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {r.source_label ?? `${r.source_entity_type}#${r.source_entity_id}`}
                          </Typography.Text>
                        </div>
                      ),
                    },
                    {
                      title: '状态', dataIndex: 'status', width: 110,
                      render: (s: string) => (s === 'obsolete'
                        ? <Tooltip title="对应的输入在本轮生成中已不存在(已删除或修改), 需求保留供追溯">
                            <Tag color="default">本轮未命中</Tag>
                          </Tooltip>
                        : <Tag color="green">有效</Tag>),
                    },
                    {
                      title: '合规依据', dataIndex: 'regulatory_ref', width: 180,
                      render: (refs: RequirementRow['regulatory_ref']) => (refs ?? []).length
                        ? (refs ?? []).map((ref, i) => (
                          <Tag key={i} color="blue">《{ref.file}》{ref.clause || ''}</Tag>
                        ))
                        : '—',
                    },
                    {
                      title: '确认', dataIndex: 'reg_confirmed', width: 120,
                      render: (v: boolean, r) => (v
                        ? <Tag color="success">已确认{r.confirmed_by ? `·${r.confirmed_by}` : ''}</Tag>
                        : (r.status === 'obsolete'
                          ? <Typography.Text type="secondary">—</Typography.Text>
                          : <Button size="small" type="link" onClick={() => void doConfirmOne(r)}>确认</Button>)),
                    },
                  ]}
                  rowClassName={(r) => (r.status === 'obsolete'
                    ? 'row-obsolete'
                    : (r.priority === 'critical' ? 'row-critical' : ''))}
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
                <Table<VulnerabilityRow>
                  rowKey={(r) => `${r.component_name}-${r.cve_id}`}
                  dataSource={vulns ?? []}
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '严重度', dataIndex: 'severity', width: 90,
                      render: (s) => <Tag color={SEVERITY_COLOR[s]}>{severityLabels[s] ?? s}</Tag> },
                    { title: <GlossaryTip term="cve_cvss">CVE</GlossaryTip>, dataIndex: 'cve_id', width: 170 },
                    { title: '组件', render: (_v, r) => `${r.component_name}@${r.component_version}`, width: 220 },
                    { title: <GlossaryTip term="cve_cvss">CVSS</GlossaryTip>, dataIndex: 'cvss_score', width: 80, render: (v) => v ?? '—' },
                    { title: '受影响范围', dataIndex: 'affected_range' },
                    { title: '修复版本', dataIndex: 'fix_version',
                      render: (v) => v ? <Tag color="green">{v}</Tag> : '—' },
                    { title: '简述', dataIndex: 'summary', ellipsis: true },
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
    </div>
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
