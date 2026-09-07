/* 工作台(#280): 指标卡 + 评估耗时条形图 + 需求优先级分布 + 最近评估 + 快捷入口。
   数据来自 /api/meta/dashboard 聚合端点(按当前用户数据权限过滤)。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Progress, Row, Statistic, Table, Typography,
} from 'antd'
import {
  AppstoreOutlined, AuditOutlined, CheckCircleOutlined, SyncOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { api, getStoredUser, isSecuritySideRole } from '../api'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import { LevelTag, ProjectStatusTag } from './tags'
import type { DashboardData } from '../types'

function HBar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="hbar-row">
      <div className="hbar-label">{label}</div>
      <div className="hbar-track">
        <div className="hbar-fill" style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }} />
      </div>
      <div className="hbar-value">{value.toFixed(1)} 分钟</div>
    </div>
  )
}

/** 近 6 个月需求生成条数, 按优先级三档堆叠(critical=高 / high=中 / 其余=低)。 */
function StackChart({ data }: { data: DashboardData['req_trend'] }) {
  const totals = data.map((d) => d.high + d.mid + d.low)
  const max = Math.max(...totals, 1)
  return (
    <>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div className="chart-legend">
          <span><i className="legend-dot" style={{ background: '#ff4d4f' }} />高(critical)</span>
          <span><i className="legend-dot" style={{ background: '#fa8c16' }} />中(high)</span>
          <span><i className="legend-dot" style={{ background: '#52c41a' }} />低(medium/low)</span>
        </div>
        <Typography.Text type="secondary">按评估创建月份统计</Typography.Text>
      </div>
      <div className="stack-chart">
        {data.map((d) => {
          const total = d.high + d.mid + d.low
          return (
            <div className="stack-col" key={d.month} title={`${d.month}: 高${d.high} / 中${d.mid} / 低${d.low}`}>
              <div className="stack-total">{total}</div>
              <div className="stack-bar" style={{ height: `${(total / max) * 82}%` }}>
                {total > 0 && (
                  <>
                    <div className="stack-seg-high" style={{ height: `${(d.high / total) * 100}%` }} />
                    <div className="stack-seg-mid" style={{ height: `${(d.mid / total) * 100}%` }} />
                    <div className="stack-seg-low" style={{ height: `${(d.low / total) * 100}%` }} />
                  </>
                )}
              </div>
              <div className="stack-month">{d.month}</div>
            </div>
          )
        })}
      </div>
    </>
  )
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isSecurity = isSecuritySideRole(getStoredUser()?.role)

  const reload = useCallback(() => {
    api.getDashboard().then(setData).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(reload, [reload])

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Card>
          <Typography.Text type="danger">加载失败: {error}</Typography.Text>{' '}
          <Button onClick={() => { setError(null); reload() }}>重试</Button>
        </Card>
      </div>
    )
  }

  const stepMax = Math.max(...(data?.step_minutes ?? []).map((s) => s.min), 1)
  const recentCols: ColumnsType<DashboardData['recent'][number]> = [
    {
      title: '评估名称 / 编码', dataIndex: 'name', width: 260,
      render: (v: string, r) => (
        <div>
          <Typography.Link onClick={() => navigate(
            r.status === 'draft' ? `/evaluations/${r.id}/wizard` : `/evaluations/${r.id}/result`,
          )}>{v}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>{r.code}</Typography.Text>
        </div>
      ),
    },
    { title: '所属系统', dataIndex: 'system_name', width: 170, ellipsis: true,
      render: (v: string | null) => v ?? <Typography.Text type="secondary">未归属</Typography.Text> },
    { title: '定级', dataIndex: 'grading_level', width: 90,
      render: (v: string | null) => <LevelTag level={v} /> },
    { title: '状态', dataIndex: 'status', width: 110, render: (v: string) => <ProjectStatusTag status={v} /> },
    { title: '创建时间', dataIndex: 'created_at', width: 150 },
  ]

  const shortcuts = [
    { label: '评估清单', path: '/evaluations' },
    { label: '系统清单', path: '/systems' },
    ...(isSecurity ? [
      { label: '新建备案', path: '/filings' },
      { label: '知识库管理', path: '/knowledge' },
      { label: '日志审计', path: '/audit' },
      { label: '系统管理', path: '/admin' },
    ] : []),
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader title="工作台" description="安全需求管理平台总览" />
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card loading={!data}>
            <Statistic
              title="系统数量" value={data?.system_count ?? 0}
              prefix={<AppstoreOutlined style={{ color: '#1677ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card loading={!data}>
            <Statistic
              title="评估总数" value={data?.eval_total ?? 0}
              prefix={<AuditOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card loading={!data}>
            <Statistic
              title="评估中" value={data?.eval_active ?? 0}
              prefix={<SyncOutlined spin={!!data && data.eval_active > 0} style={{ color: '#fa8c16' }} />}
              suffix={<Typography.Text type="secondary" style={{ fontSize: 14 }}>项</Typography.Text>}
            />
            <Progress
              percent={data ? Math.round((data.eval_active / Math.max(data.eval_total, 1)) * 100) : 0}
              size="small" showInfo={false} strokeColor="#fa8c16"
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card loading={!data}>
            <Statistic
              title="已生成基线" value={data?.eval_done ?? 0}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              suffix={<Typography.Text type="secondary" style={{ fontSize: 14 }}>项</Typography.Text>}
            />
            <Progress
              percent={data ? Math.round((data.eval_done / Math.max(data.eval_total, 1)) * 100) : 0}
              size="small" showInfo={false} strokeColor="#52c41a"
            />
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title="评估耗时(各步平均)"
            extra={<Typography.Text type="secondary">全程平均 {data?.avg_minutes ?? 0} 分钟</Typography.Text>}
            loading={!data}
          >
            {(data?.step_minutes ?? []).length === 0
              ? <Typography.Text type="secondary">还没有填报耗时记录, 完成一轮评估后这里展示各步平均用时。</Typography.Text>
              : (data?.step_minutes ?? []).map((s) => (
                <HBar key={s.step} label={s.step} value={s.min} max={stepMax} />
              ))}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="需求生成数量(优先级分布)" loading={!data}>
            {data && <StackChart data={data.req_trend} />}
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Card
            title="最近评估"
            extra={<Button type="link" size="small" onClick={() => navigate('/evaluations')}>查看全部</Button>}
          >
            <Table
              rowKey="id" size="small" loading={!data} pagination={false}
              columns={recentCols}
              dataSource={data?.recent ?? []}
              locale={{ emptyText: '还没有评估, 到评估清单发起新评估' }}
              onRow={(r) => ({
                onClick: () => navigate(r.status === 'draft' ? `/evaluations/${r.id}/wizard` : `/evaluations/${r.id}/result`),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="快捷入口">
            <Row gutter={[8, 8]}>
              {shortcuts.map((q) => (
                <Col span={12} key={q.path}>
                  <Button block onClick={() => navigate(q.path)}>{q.label}</Button>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
