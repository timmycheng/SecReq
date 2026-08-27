/* 产物页: 安全需求清单(可筛选)/漏洞清单(高危标红)/文档下载(4 Word + SBOM + Excel)。 */
import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Select, Space, Spin, Statistic, Table, Tabs, Tag, message,
} from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'

import { api, downloadUrl } from '../api'
import { labelMapOf, useEnums } from '../enums'
import type {
  ProjectDetail, RequirementRow, VulnerabilityRow,
} from '../types'

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
]

export default function ResultPage({ projectId }: { projectId: number }) {
  const enums = useEnums()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[] | null>(null)
  const [vulns, setVulns] = useState<VulnerabilityRow[] | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>()

  const reload = () => {
    api.getProject(projectId).then(setProject).catch((e: Error) => message.error(e.message))
    api.listRequirements(projectId).then(setRequirements).catch((e: Error) => { setRequirements([]); message.error(e.message) })
    api.listVulnerabilities(projectId).then(setVulns).catch(() => setVulns([]))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, [projectId])

  if (!project || requirements === null) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 300 }}><Spin size="large" /></div>
  }

  const filtered = requirements.filter((r) =>
    (!categoryFilter || r.category === categoryLabel(enums, categoryFilter))
    && (!priorityFilter || r.priority === priorityFilter))

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        <Button onClick={() => downloadUrl(`/api/projects/${projectId}/export/xlsx`)}>
          <DownloadOutlined /> 需求跟踪表.xlsx(Jira 可导入)
        </Button>
        <Button onClick={() => downloadUrl(`/api/projects/${projectId}/sbom`)}>SBOM JSON(CycloneDX 1.5)</Button>
        <span style={{ color: '#888' }}>{project.name}({project.code})</span>
      </Space>

      <Space size={16} style={{ display: 'flex', marginBottom: 16 }} wrap>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title="安全需求" value={requirements.length} />
        </Card>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title="紧急/高优先级"
            value={requirements.filter((r) => r.priority === 'critical' || r.priority === 'high').length} />
        </Card>
        <Card size="small" style={{ minWidth: 160 }}>
          <Statistic title="漏洞记录(离线缓存)" value={vulns?.length ?? 0} />
        </Card>
        {vulns && vulns.some((v) => v.severity === 'critical') && (
          <Alert type="error" showIcon style={{ flex: 1 }}
            message={`存在 ${vulns.filter((v) => v.severity === 'critical').length} 条严重漏洞, 请优先整改(详见漏洞清单)`} />
        )}
      </Space>

      {/* ── 文档下载区 ── */}
      <Card size="small" title="生成产物下载" style={{ marginBottom: 16 }}>
        <Space wrap>
          {DOC_ITEMS.map((doc) => (
            <Button key={doc.key} type="primary" ghost icon={<DownloadOutlined />}
              onClick={() => downloadUrl(`/api/projects/${projectId}/export/docx/${doc.key}`)}>
              {doc.name}
            </Button>
          ))}
          <TypographyHint />
        </Space>
        {(project.counts.vulnerabilities ?? 0) === 0 && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon
            message="提示: 离线模式下生成的文档不含在线漏洞数据; 在向导确认页开启 OSV 在线查询后重新生成即可。" />
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
                <Space style={{ marginBottom: 12 }}>
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
                  <span style={{ color: '#888' }}>全部需求均可通过 source_entity 追溯到输入项</span>
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
                        <p><b>来源:</b> {r.source_entity_type}#{r.source_entity_id} · ASVS {r.asvs_ref ?? '—'} · 模板 {r.template_id}</p>
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
                  ]}
                  rowClassName={(r) => (r.priority === 'critical' ? 'row-critical' : '')}
                />
              </>
            ),
          },
          {
            key: 'vulns',
            label: `漏洞清单(${vulns?.length ?? 0})`,
            children: (
              <Table<VulnerabilityRow>
                rowKey={(r) => `${r.component_name}-${r.cve_id}`}
                dataSource={vulns ?? []}
                size="small"
                pagination={false}
                columns={[
                  { title: '严重度', dataIndex: 'severity', width: 90,
                    render: (s) => <Tag color={SEVERITY_COLOR[s]}>{labelMapOf(enums, 'severity_labels')[s] ?? s}</Tag> },
                  { title: 'CVE', dataIndex: 'cve_id', width: 170 },
                  { title: '组件', render: (_v, r) => `${r.component_name}@${r.component_version}`, width: 220 },
                  { title: 'CVSS', dataIndex: 'cvss_score', width: 80, render: (v) => v ?? '—' },
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

function TypographyHint() {
  return (
    <span style={{ color: '#888', fontSize: 13 }}>
      Word 文档按库内最新数据即时重渲染; 跟踪表字段与 Jira 外部导入兼容(含映射说明 Sheet)
    </span>
  )
}
