/* 评审中心(#219): 布局模式4 —— 左侧内容(门禁卡 + 需求批注工作台 + 流转时间线)
   + 右侧固定「评审操作面板」。四类角色同页按角色与门禁状态出操作:
   pm=提交评审/整改后重新提交, 评审员=逐条批注+整体裁定, 负责人=终审会签。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, App, Button, Card, Descriptions, Empty, Input, Modal, Popconfirm,
  Radio, Space, Spin, Table, Tag, Timeline, Typography,
} from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons'
import type { RequirementRow, RequirementTransitionRow, ReviewState } from '../types'
import { api, type StoredUser } from '../api'
import { getStoredUser } from '../api'
import { GATE_STATUS_COLOR, PRIORITY_COLOR, REQUIREMENT_STATUS_COLOR } from './tokens'
import { navigate } from '../router'

const REVIEW_STATUS_LABELS: Record<string, string> = {
  open: '待确认', confirmed: '已确认', reviewed: '评审通过', rectifying: '整改中',
}

const ACTION_LABELS: Record<string, string> = {
  submit: '提交评审', approve: '裁定通过', reject: '裁定否决',
  request_change: '退回整改', sign: '终审会签', annotate: '逐条批注',
}

const TRANSITION_LABELS: Record<string, string> = {
  confirm: '确认', reconfirm: '整改后重新确认',
  review_pass: '评审通过', request_change: '退回整改',
}

const FALLBACK_GATE_LABELS: Record<string, string> = { pending: '待提交' }
const gateStatusLabel = (verb: string | undefined, status: string | null) =>
  verb ?? FALLBACK_GATE_LABELS[status ?? ''] ?? status ?? '待提交'

export default function ReviewPage({ projectId }: { projectId: number }) {
  const { message } = App.useApp()
  const [user] = useState<StoredUser | null>(getStoredUser())
  const [state, setState] = useState<ReviewState | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [acting, setActing] = useState(false)
  const [blocked, setBlocked] = useState<string[] | null>(null)
  // 批注弹窗 / 裁定意见 / 终审意见
  const [annotate, setAnnotate] = useState<{ req: RequirementRow; disposition: string } | null>(null)
  const [annotateComment, setAnnotateComment] = useState('')
  const [decide, setDecide] = useState<string | null>(null)
  const [decideComment, setDecideComment] = useState('')
  const [finalizeOpen, setFinalizeOpen] = useState(false)
  const [finalizeComment, setFinalizeComment] = useState('')
  const [expanded, setExpanded] = useState<Record<number, RequirementTransitionRow[]>>({})
  const [confirming, setConfirming] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [st, reqs] = await Promise.all([
        api.reviewState(projectId),
        api.listRequirements(projectId),
      ])
      setState(st)
      setRequirements(reqs)
    } catch (e) {
      setLoadError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { void reload() }, [reload])

  const gate = state?.gate ?? null
  const isSecuritySide = user?.role === 'security_reviewer' || user?.role === 'security_lead'
  const isLead = user?.role === 'security_lead'
  const isSubmitter = gate?.submitter_id != null && gate.submitter_id === user?.id
  const isReviewerOfGate = gate?.reviewer_id != null && gate.reviewer_id === user?.id
  const inReview = gate?.status === 'in_review'
  const canSubmit = user?.role === 'pm' || isLead
  const canAnnotate = isSecuritySide && inReview && !isSubmitter
  const canDecide = isSecuritySide && inReview && !isSubmitter
  const canFinalize = isLead && inReview && gate?.reviewer_conclusion === 'approve' && !isSubmitter && !isReviewerOfGate

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setActing(true)
    try {
      await fn()
      message.success(ok)
      setBlocked(null)
      await reload()
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    } finally {
      setActing(false)
    }
  }

  const onSubmit = async () => {
    setActing(true)
    try {
      const res = await api.reviewSubmit(projectId)
      if (res.status === 'blocked') {
        setBlocked(res.missing ?? [])
        message.warning('门禁校验未通过, 请补齐缺项后重新提交评审')
      } else {
        setBlocked(null)
        message.success('已提交评审, 等待评审员审核')
        await reload()
      }
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setActing(false)
    }
  }

  const loadTransitions = async (req: RequirementRow) => {
    if (expanded[req.id]) return
    try {
      const rows = await api.requirementTransitions(projectId, req.req_id)
      setExpanded((prev) => ({ ...prev, [req.id]: rows }))
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const summary = state?.requirement_summary ?? {}

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center' }}><Spin tip="加载评审状态..." /></div>
  }
  if (loadError || state === null) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon message="评审状态加载失败" description={loadError}
          action={<Button onClick={() => void reload()}>重试</Button>} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', padding: 16 }}>
      {/* ── 左侧内容区 ── */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回列表</Button>
          <Typography.Title level={4} style={{ margin: 0 }}>评审中心</Typography.Title>
          <Tag color={gate ? GATE_STATUS_COLOR[gate.status] ?? 'default' : 'default'}>
            {gateStatusLabel(gate?.status_verb, gate?.status ?? null)}
          </Tag>
        </Space>

        <Card
          size="small" title="门禁状态" style={{ marginBottom: 16 }}
          extra={gate ? (
            <Button size="small" icon={<DownloadOutlined />}
              onClick={async () => {
                try {
                  const url = await api.downloadReviewSheet(projectId)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = ''
                  a.click()
                  URL.revokeObjectURL(url)
                } catch (e) {
                  message.error((e as Error).message)
                }
              }}>
              下载评审表
            </Button>
          ) : undefined}
        >
          {gate ? (
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="门禁类型">需求门禁</Descriptions.Item>
              <Descriptions.Item label="当前状态">{gate.status_verb}</Descriptions.Item>
              <Descriptions.Item label="提交时间">{gate.submitted_at?.slice(0, 19).replace('T', ' ') ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="评审时间">{gate.reviewed_at?.slice(0, 19).replace('T', ' ') ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="评审员裁定">
                {gate.reviewer_conclusion
                  ? <Tag color={gate.reviewer_conclusion === 'approve' ? 'green' : 'orange'}>
                      {{ approve: '通过', reject: '否决', request_change: '退回整改' }[gate.reviewer_conclusion]}
                    </Tag>
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="终审时间">{gate.final_reviewed_at?.slice(0, 19).replace('T', ' ') ?? '—'}</Descriptions.Item>
              {gate.reviewer_opinion && <Descriptions.Item label="评审意见" span={2}>{gate.reviewer_opinion}</Descriptions.Item>}
              {gate.final_opinion && <Descriptions.Item label="终审意见" span={2}>{gate.final_opinion}</Descriptions.Item>}
              <Descriptions.Item label="交付物快照">
                <Typography.Text code copyable style={{ fontSize: 12 }}>
                  {gate.version_hash?.slice(0, 16) ?? '—'}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="留痕链校验">
                {state.chain_valid
                  ? <Tag color="green">完整</Tag>
                  : <Tag color="red">被篡改</Tag>}
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Typography.Text type="secondary">尚未提交评审。补齐需求确认后点右侧「提交评审」。</Typography.Text>
          )}
        </Card>

        <Card size="small" title={`需求批注工作台(${requirements.length})`} style={{ marginBottom: 16 }}>
          <Table<RequirementRow>
            rowKey="id" size="small"
            dataSource={requirements}
            scroll={{ x: 760 }}
            pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
            locale={{ emptyText: <Empty description="还没有安全需求, 请先在向导中生成" /> }}
            expandable={{
              expandedRowRender: (r) => (
                <Timeline
                  style={{ margin: '8px 0 0' }}
                  items={(expanded[r.id] ?? []).map((t) => ({
                    children: (
                      <>
                        <Tag>{TRANSITION_LABELS[t.action] ?? t.action}</Tag>
                        <Typography.Text type="secondary">
                          {REVIEW_STATUS_LABELS[t.from_status]} → {REVIEW_STATUS_LABELS[t.to_status]} ·
                          {' '}{t.operator_name} · {t.created_at.slice(0, 19).replace('T', ' ')}
                        </Typography.Text>
                        {t.opinion && <div><Typography.Text type="secondary">意见: {t.opinion}</Typography.Text></div>}
                      </>
                    ),
                  }))}
                />
              ),
              onExpand: (open, r) => { if (open) void loadTransitions(r) },
            }}
            columns={[
              { title: '编号', dataIndex: 'req_id', width: 150 },
              { title: '需求标题', dataIndex: 'title', ellipsis: true },
              {
                title: '优先级', dataIndex: 'priority', width: 90,
                render: (p) => <Tag color={PRIORITY_COLOR[p]}>{p === 'critical' ? '紧急' : p === 'high' ? '高' : p === 'medium' ? '中' : '低'}</Tag>,
              },
              {
                title: '评审状态', dataIndex: 'review_status', width: 110,
                render: (v) => <Tag color={REQUIREMENT_STATUS_COLOR[v] ?? 'default'}>{REVIEW_STATUS_LABELS[v] ?? v}</Tag>,
              },
              {
                title: '操作', width: 210,
                render: (_, r) => {
                  if (canAnnotate && r.review_status === 'confirmed') {
                    return (
                      <Space size={4}>
                        <Button size="small" type="link" onClick={() => { setAnnotate({ req: r, disposition: 'approve' }); setAnnotateComment('') }}>通过</Button>
                        <Button size="small" type="link" onClick={() => { setAnnotate({ req: r, disposition: 'object' }); setAnnotateComment('') }}>异议</Button>
                        <Button size="small" type="link" danger onClick={() => { setAnnotate({ req: r, disposition: 'return' }); setAnnotateComment('') }}>退回</Button>
                      </Space>
                    )
                  }
                  if (canSubmit && (r.review_status === 'open' || r.review_status === 'rectifying')) {
                    return (
                      <Button size="small" type="link" loading={confirming === r.id}
                        onClick={async () => {
                          setConfirming(r.id)
                          try {
                            await api.confirmRegulatory(projectId, r.req_id)
                            await reload()
                          } catch (e) {
                            message.error((e as Error).message)
                          } finally {
                            setConfirming(null)
                          }
                        }}>
                        确认
                      </Button>
                    )
                  }
                  return null
                },
              },
            ]}
          />
        </Card>

        <Card size="small" title="评审留痕时间线">
          {state.evidences.length === 0
            ? <Empty description="暂无评审动作留痕" />
            : (
              <Timeline
                items={state.evidences.map((e) => ({
                  color: e.action === 'submit' ? 'blue' : e.action === 'sign' ? 'green' : e.action === 'reject' || e.action === 'request_change' ? 'red' : 'gray',
                  children: (
                    <>
                      <strong>{ACTION_LABELS[e.action] ?? e.action}</strong>
                      {' '}<Typography.Text type="secondary">
                        {e.timestamp.slice(0, 19).replace('T', ' ')}{e.payload?.req_id ? ` · ${e.payload.req_id}` : ''}
                      </Typography.Text>
                      {e.comment && <div><Typography.Text type="secondary">意见: {e.comment}</Typography.Text></div>}
                    </>
                  ),
                }))}
              />
            )}
        </Card>
      </div>

      {/* ── 右侧固定评审操作面板(布局模式4) ── */}
      <Card
        size="small" title="评审操作面板"
        style={{ width: 340, flexShrink: 0, position: 'sticky', top: 16 }}
      >
        {blocked !== null && blocked.length > 0 && (
          <Alert
            type="error" showIcon style={{ marginBottom: 12 }}
            message="门禁校验未通过"
            description={
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {blocked.map((m) => <li key={m}><Typography.Text style={{ fontSize: 12 }}>{m}</Typography.Text></li>)}
              </ul>
            }
          />
        )}

        <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
          <Descriptions.Item label="待确认">{summary.open ?? 0}</Descriptions.Item>
          <Descriptions.Item label="已确认">{summary.confirmed ?? 0}</Descriptions.Item>
          <Descriptions.Item label="评审通过">{summary.reviewed ?? 0}</Descriptions.Item>
          <Descriptions.Item label="整改中">{summary.rectifying ?? 0}</Descriptions.Item>
        </Descriptions>

        {canSubmit && gate?.status !== 'in_review' && gate?.status !== 'passed' && (
          <Popconfirm
            title="提交评审后将进入评审队列, 确认提交?"
            onConfirm={() => void onSubmit()}
          >
            <Button type="primary" block loading={acting}
              disabled={requirements.length === 0}>
              {gate?.status === 'rectifying' || gate?.status === 'rejected' ? '整改后重新提交评审' : '提交评审'}
            </Button>
          </Popconfirm>
        )}
        {canSubmit && gate?.status === 'in_review' && (
          <Typography.Text type="secondary">评审进行中, 如需修改请等待评审结论。</Typography.Text>
        )}
        {canSubmit && gate?.status === 'passed' && (
          <Typography.Text type="secondary">
            <CheckCircleOutlined style={{ color: '#52c41a' }} /> 评审已通过, 本轮归档。
          </Typography.Text>
        )}

        {canDecide && (
          <div>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              整体裁定(评审员)
            </Typography.Paragraph>
            <Radio.Group
              value={decide} onChange={(e) => setDecide(e.target.value)}
              options={[
                { value: 'approve', label: '通过' },
                { value: 'request_change', label: '退回整改' },
                { value: 'reject', label: '否决' },
              ]}
              style={{ marginBottom: 8 }}
            />
            <Input.TextArea
              rows={2} placeholder="裁定意见(可空)" value={decideComment}
              onChange={(e) => setDecideComment(e.target.value)} style={{ marginBottom: 8 }}
            />
            <Button
              type="primary" block disabled={!decide} loading={acting}
              onClick={() => {
                if (!decide) return
                void run(() => api.reviewDecide(projectId, decide, decideComment), '裁定已记录').then((ok) => {
                  if (ok) { setDecide(null); setDecideComment('') }
                })
              }}
            >
              提交裁定
            </Button>
          </div>
        )}

        {isLead && inReview && gate?.reviewer_conclusion !== 'approve' && !isSubmitter && (
          <Typography.Text type="secondary">评审员裁定通过后可终审会签。</Typography.Text>
        )}
        {canFinalize && (
          <div>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              终审会签(负责人): 评审员已通过
            </Typography.Paragraph>
            <Input.TextArea
              rows={2} placeholder="终审意见(可空)" value={finalizeComment}
              onChange={(e) => setFinalizeComment(e.target.value)} style={{ marginBottom: 8 }}
            />
            <Button type="primary" block loading={acting} onClick={() => setFinalizeOpen(true)}>
              终审会签(复审通过)
            </Button>
          </div>
        )}

        {user?.role === 'auditor' && (
          <Typography.Text type="secondary">审计视角: 只读查看门禁与留痕。</Typography.Text>
        )}
      </Card>

      {/* ── 批注弹窗 ── */}
      <Modal
        title={`批注: ${annotate?.req.req_id ?? ''}`}
        open={annotate !== null}
        onCancel={() => setAnnotate(null)}
        onOk={async () => {
          if (!annotate) return
          const ok = await run(
            () => api.reviewAnnotate(projectId, annotate.req.req_id, annotate.disposition, annotateComment),
            annotate.disposition === 'approve' ? '已批注通过' : annotate.disposition === 'return' ? '已退回整改' : '已记录异议')
          if (ok) setAnnotate(null)
        }}
        okText={annotate?.disposition === 'approve' ? '确认通过' : annotate?.disposition === 'return' ? '确认退回' : '记录异议'}
      >
        <Typography.Paragraph type="secondary">{annotate?.req.title}</Typography.Paragraph>
        {annotate?.disposition === 'return' && (
          <Typography.Paragraph type="warning" style={{ marginBottom: 8 }}>
            退回后该需求进入整改中, PM 整改后重新确认方可复审。
          </Typography.Paragraph>
        )}
        <Input.TextArea
          rows={3} placeholder="批注意见(退回建议必填)"
          value={annotateComment} onChange={(e) => setAnnotateComment(e.target.value)}
        />
      </Modal>

      {/* ── 终审确认 ── */}
      <Modal
        title="终审会签确认" open={finalizeOpen} onCancel={() => setFinalizeOpen(false)}
        onOk={async () => {
          const ok = await run(() => api.reviewFinalize(projectId, finalizeComment), '终审通过, 本轮评审归档')
          if (ok) { setFinalizeOpen(false); setFinalizeComment('') }
        }}
        okText="确认复审通过"
      >
        <Typography.Paragraph>
          终审通过后门禁进入 passed, 未批注的已确认需求将随项目整体推为「评审通过」。
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">终审人与提交人/评审员不得为同一人。</Typography.Paragraph>
      </Modal>
    </div>
  )
}
