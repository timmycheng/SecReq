/* 评审门禁页(引导式): 每个门禁用「提交 → 评审员审核 → 负责人终审」三步图示标明进度,
   顶部一句话告诉当前身份"现在可以做什么"; 被门禁阻断时给出一键修复按钮,
   不需要理解门禁/哈希链等概念也能走完流程。 */
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert, App, Breadcrumb, Button, Card, Drawer, Input, Space, Spin, Steps, Tag,
  Timeline, Tooltip, Typography,
} from 'antd'
import {
  AuditOutlined, CheckCircleOutlined, ReloadOutlined, SafetyOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

import { api, getStoredUsername, IDENTITY_EVENT, parseGateBlocked } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import type {
  ChainVerify, EvidenceRow, GateRow, ProjectDetail, RequirementRow,
} from '../types'
import { batchConfirmRegulatory, batchSetOwner, criticalWithoutOwner, unconfirmedRegulatory } from './assist'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', in_review: 'processing', passed: 'success',
  rejected: 'error', rectifying: 'warning',
}

const STEP_TITLES = ['项目经理提交', '安全中心评审员审核', '安全中心负责人终审']
const INTRO_KEY = 'secreq.review.intro.dismissed'

/** 门禁当前推进到三步图的第几步。 */
function gateProgress(g: GateRow): { current: number; status: 'process' | 'error' | 'finish' } {
  if (g.status === 'passed') return { current: 3, status: 'finish' }
  if (g.status === 'rejected') return { current: 1, status: 'error' }
  if (g.status === 'rectifying') return { current: 0, status: 'error' }
  if (g.status === 'in_review') {
    return g.reviewer_conclusion === 'approve'
      ? { current: 2, status: 'process' }
      : { current: 1, status: 'process' }
  }
  return { current: 0, status: 'process' } // pending: 待提交
}

export default function ReviewPage({ projectId }: { projectId: number }) {
  const { modal, message } = App.useApp()
  const enums = useEnums()
  const [gates, setGates] = useState<GateRow[] | null>(null)
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [requirements, setRequirements] = useState<RequirementRow[]>([])
  const [role, setRole] = useState<string | null>(null)
  const [acting, setActing] = useState(false)
  const [introHidden, setIntroHidden] = useState(
    () => localStorage.getItem(INTRO_KEY) === '1',
  )
  const [evidenceFor, setEvidenceFor] = useState<GateRow | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRow[] | null>(null)
  const [chain, setChain] = useState<ChainVerify | null>(null)

  const reload = useCallback(() => {
    api.getProject(projectId).then(setProject).catch(() => undefined)
    api.listRequirements(projectId).then(setRequirements).catch(() => undefined)
    api.listGates(projectId).then(setGates).catch((e: Error) => message.error(e.message))
    const username = getStoredUsername()
    if (username) {
      api.login(username).then((info) => setRole(info.role)).catch(() => setRole(null))
    }
  }, [projectId, message])
  useEffect(() => { reload() }, [reload])

  // 右上角切换身份后, 立即刷新"现在可以做什么"的角色提示
  useEffect(() => {
    const onIdentityChange = () => {
      const username = getStoredUsername()
      if (!username) { setRole(null); return }
      api.login(username).then((info) => setRole(info.role)).catch(() => setRole(null))
    }
    window.addEventListener(IDENTITY_EVENT, onIdentityChange)
    return () => window.removeEventListener(IDENTITY_EVENT, onIdentityChange)
  }, [])

  if (!gates || !project) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 300 }}><Spin size="large" /></div>
  }

  const canSubmit = role === 'pm' || role === 'developer'
  const canReview = role === 'security_reviewer'
  const canFinal = role === 'security_lead'
  const enabledTypes = ['initiation', 'requirement', 'design']
  const regTodo = unconfirmedRegulatory(requirements)
  const ownerTodo = criticalWithoutOwner(requirements)

  /* ── 一键修复 ── */
  const fixRegulatory = async () => {
    setActing(true)
    try {
      const n = await batchConfirmRegulatory(projectId, requirements)
      message.success(`已确认 ${n} 条报送事项`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setActing(false)
    }
  }

  const fixOwners = () => {
    let owner = project.pm_name || '王建国'
    modal.confirm({
      title: `为 ${ownerTodo.length} 条紧急需求统一指定责任人`,
      content: (
        <div style={{ marginTop: 12 }}>
          <Input
            defaultValue={owner}
            onChange={(e) => { owner = e.target.value }}
            placeholder="责任人姓名(如本人姓名, 留痕用)"
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            也可稍后在产物页逐条指定不同责任人。
          </Typography.Text>
        </div>
      ),
      okText: '确认指定',
      cancelText: '取消',
      onOk: async () => {
        if (!owner.trim()) { message.warning('请输入责任人'); return Promise.reject() }
        try {
          const n = await batchSetOwner(projectId, requirements, owner.trim())
          message.success(`已为 ${n} 条紧急需求指定责任人 ${owner.trim()}`)
          reload()
        } catch (e) {
          message.error((e as Error).message)
          return Promise.reject()
        }
      },
    })
  }

  /* ── 提交评审 ── */
  const doSubmit = async (gate: GateRow) => {
    setActing(true)
    try {
      await api.submitGate(projectId, gate.gate_type)
      message.success(`「${gate.gate_label}」已提交评审, 等待评审员审核`)
      reload()
    } catch (e) {
      const blocked = parseGateBlocked(e as Error)
      if (blocked) {
        message.warning('还差几步材料才能提交, 已在下方红字列出')
      } else {
        message.error((e as Error).message)
      }
    } finally {
      setActing(false)
    }
  }

  const askOpinion = (title: string, okText: string, needOpinion: boolean,
                      onOk: (opinion: string) => Promise<unknown>) => {
    let opinion = ''
    modal.confirm({
      title,
      content: (
        <Input.TextArea
          placeholder={needOpinion ? '请填写意见(必填)' : '评审意见(可填: 同意)'}
          rows={3}
          onChange={(e) => { opinion = e.target.value }}
          style={{ marginTop: 12 }}
        />
      ),
      okText,
      cancelText: '取消',
      onOk: async () => {
        if (needOpinion && !opinion.trim()) {
          message.warning('请填写意见')
          return Promise.reject()
        }
        try {
          await onOk(opinion.trim() || '同意')
          reload()
        } catch (e) {
          message.error((e as Error).message)
          return Promise.reject()
        }
      },
    })
  }

  const openEvidence = async (gate: GateRow) => {
    setEvidenceFor(gate)
    setEvidence(null)
    setChain(null)
    try {
      setEvidence(await api.listEvidence(projectId, gate.id))
      setChain(await api.verifyChain(projectId, gate.id))
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  /** 按当前身份与门禁状态, 给出"现在可以做什么"。 */
  function nextActionHint(g: GateRow): { text: string; actions?: ReactNode } {
    if (g.status === 'passed') return { text: '该门禁已通过 ✓ 无需操作' }
    if (g.check.status === 'blocked') {
      const fix = (
        <Space size={8} wrap>
          {canSubmit && regTodo.length > 0 && (
            <Button size="small" type="primary" ghost icon={<ThunderboltOutlined />}
              loading={acting} onClick={() => void fixRegulatory()}>
              一键确认全部报送事项({regTodo.length})
            </Button>
          )}
          {canSubmit && ownerTodo.length > 0 && (
            <Button size="small" type="primary" ghost icon={<ThunderboltOutlined />}
              onClick={fixOwners}>
              一键指定责任人({ownerTodo.length})
            </Button>
          )}
          {!canSubmit && (
            <Typography.Text type="secondary">请通知项目经理补齐</Typography.Text>
          )}
        </Space>
      )
      if (g.gate_type === 'initiation' && regTodo.length > 0) {
        return {
          text: `还差最后一步: 确认 ${regTodo.length} 条监管报送事项`,
          actions: fix,
        }
      }
      if (g.gate_type === 'requirement' && ownerTodo.length > 0) {
        return {
          text: `还差最后一步: 为 ${ownerTodo.length} 条紧急需求指定责任人`,
          actions: fix,
        }
      }
      return { text: '材料未齐(红字清单见下方), 补齐后才能提交评审', actions: fix }
    }
    if (g.status === 'pending') {
      return canSubmit
        ? {
            text: '材料已齐, 可以进入评审:',
            actions: (
              <Button size="small" type="primary" loading={acting} onClick={() => void doSubmit(g)}>
                提交评审
              </Button>
            ),
          }
        : { text: '等待项目经理提交评审' }
    }
    if (g.status === 'in_review' && g.reviewer_conclusion !== 'approve') {
      return canReview
        ? {
            text: '你是评审员, 请给出审核结论:',
            actions: (
              <Space size={8} wrap>
                <Button size="small" onClick={() => askOpinion('退回整改', '退回', true,
                  (op) => api.reviewGate(projectId, g.id, 'request_change', op))}>退回整改</Button>
                <Button size="small" danger onClick={() => askOpinion('否决该门禁', '确认否决', true,
                  (op) => api.reviewGate(projectId, g.id, 'reject', op))}>否决</Button>
                <Button size="small" type="primary" onClick={() => askOpinion('审核通过', '通过', false,
                  (op) => api.reviewGate(projectId, g.id, 'approve', op))}>审核通过</Button>
              </Space>
            ),
          }
        : { text: '等待安全中心评审员审核' }
    }
    if (g.status === 'in_review' && g.reviewer_conclusion === 'approve') {
      return canFinal
        ? {
            text: '评审员已通过, 你是负责人, 终审签核后即完成:',
            actions: (
              <Space size={8} wrap>
                <Button size="small" danger onClick={() => askOpinion('终审否决', '确认否决', true,
                  (op) => api.finalizeGate(projectId, g.id, 'reject', op))}>终审否决</Button>
                <Button size="small" type="primary" onClick={() => askOpinion('终审签核(通过)', '签核放行', true,
                  (op) => api.finalizeGate(projectId, g.id, 'sign', op))}>终审签核</Button>
              </Space>
            ),
          }
        : { text: '评审员已通过 ✓ 等待安全中心负责人终审签核' }
    }
    if (g.status === 'rectifying') return { text: '已退回整改, 项目经理修改后可重新提交' }
    return { text: '已否决, 项目经理整改后可重新提交' }
  }

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <Breadcrumb
        items={[
          { title: <a onClick={(e) => { e.preventDefault(); navigate('/') }}>项目列表</a> },
          { title: <a onClick={(e) => { e.preventDefault(); navigate(`/result/${projectId}`) }}>{project.name}</a> },
          { title: '评审门禁' },
        ]}
      />

      <Space style={{ margin: '12px 0 8px' }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <SafetyOutlined /> 安全评审
        </Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        {role && (
          <Tag color="geekblue">我的身份: {labelMapOf(enums, 'platform_roles')[role] ?? role}</Tag>
        )}
      </Space>

      {!introHidden && (
        <Alert
          style={{ marginBottom: 14 }}
          type="info" showIcon closable
          afterClose={() => {
            setIntroHidden(true)
            localStorage.setItem(INTRO_KEY, '1')
          }}
          message="评审就三步, 不用记流程"
          description={(
            <span>
              每个门禁(立项/需求/设计)都是同样三步:
              <b> 项目经理「提交评审」→ 评审员「审核通过」→ 负责人「终审签核」</b>。
              页面会根据你的身份提示现在该点哪个按钮; 材料没备齐时会红字列出缺什么, 并提供一键补齐。
              替别人审核时, 到页面右上角切换身份即可。
            </span>
          )}
        />
      )}

      {enabledTypes.map((type) => {
        const gate = gates.find((g) => g.gate_type === type)
        if (!gate) return null
        const progress = gateProgress(gate)
        const hint = nextActionHint(gate)
        return (
          <Card
            key={type}
            size="small"
            style={{ marginBottom: 14 }}
            title={(
              <Space>
                {gate.status === 'passed'
                  ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  : <SafetyOutlined />}
                <b>{gate.gate_label}</b>
                <Tag color={STATUS_COLOR[gate.status]}>{gate.status_label}</Tag>
              </Space>
            )}
            extra={(
              <Button size="small" type="text" icon={<AuditOutlined />}
                onClick={() => void openEvidence(gate)}>
                评审记录({gate.evidence_count})
              </Button>
            )}
          >
            <Steps
              size="small"
              current={progress.current}
              status={progress.status}
              items={STEP_TITLES.map((t) => ({ title: t }))}
            />
            <div style={{
              marginTop: 14, padding: '10px 14px', background: '#fafafa',
              borderRadius: 6,
            }}>
              <Space size={10} wrap>
                <Typography.Text>{hint.text}</Typography.Text>
                {hint.actions}
              </Space>
            </div>

            {gate.check.status === 'blocked' && (
              <Alert
                style={{ marginTop: 10 }} type="error" showIcon
                message="还差这些材料:"
                description={(
                  <ul style={{ paddingLeft: 18, margin: '6px 0 0' }}>
                    {gate.check.missing.map((m, i) => <li key={i}>{m}</li>)}
                  </ul>
                )}
              />
            )}
            {(gate.reviewer_opinion || gate.final_opinion) && (
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                {gate.reviewer_opinion && <>评审员意见: {gate.reviewer_opinion}　</>}
                {gate.final_opinion && <>负责人意见: {gate.final_opinion}</>}
              </Typography.Text>
            )}
          </Card>
        )
      })}

      {gates.filter((g) => !enabledTypes.includes(g.gate_type)).length > 0 && (
        <Card size="small" title="后续门禁(当前阶段用不到)">
          <Space wrap>
            {gates.filter((g) => !enabledTypes.includes(g.gate_type)).map((g) => (
              <Tag key={g.gate_type}>{g.gate_label}</Tag>
            ))}
          </Space>
        </Card>
      )}

      <Drawer
        title={`评审记录: ${evidenceFor?.gate_label ?? ''}`}
        width={620}
        open={evidenceFor !== null}
        onClose={() => setEvidenceFor(null)}
      >
        {chain && (
          <Alert
            style={{ marginBottom: 16 }}
            type={chain.valid ? 'success' : 'error'}
            showIcon
            message={chain.valid
              ? `记录完整(${chain.count} 条, 防篡改校验通过)`
              : `第 #${chain.broken_at} 条记录校验异常, 可能被篡改!`}
          />
        )}
        {!evidence ? <Spin /> : evidence.length === 0 ? (
          <Typography.Text type="secondary">还没有评审动作记录。</Typography.Text>
        ) : (
          <Timeline
            items={evidence.map((e) => ({
              color: e.action === 'submit' ? 'blue'
                : e.action === 'sign' ? 'green'
                  : e.action === 'reject' ? 'red' : 'gray',
              children: (
                <div>
                  <Space wrap>
                    <b>{e.action_label}</b>
                    <Tag>{e.actor}</Tag>
                    <Typography.Text type="secondary">
                      {new Date(e.timestamp).toLocaleString('zh-CN')}
                    </Typography.Text>
                  </Space>
                  {e.comment && <div style={{ marginTop: 2 }}>{e.comment}</div>}
                  <Tooltip title={`校验哈希: ${e.curr_hash}`}>
                    <Typography.Text type="secondary" code style={{ fontSize: 11, display: 'block' }}>
                      {e.curr_hash.slice(0, 24)}…
                    </Typography.Text>
                  </Tooltip>
                </div>
              ),
            }))}
          />
        )}
      </Drawer>
    </div>
  )
}
