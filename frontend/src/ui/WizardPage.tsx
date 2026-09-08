/* 8 步向导容器(#280 新框架): 页头 + 步骤卡 + 吸底导航, 步骤内容组件沿用原业务逻辑。
   #194 基础设施/组件上收系统; #259 恢复「组件与基础设施」步骤; #289 按 DESIGN 拆为
   「基础设施」与「组件与许可证」两步(内嵌系统清单卡, 默认带出系统已存版本,
   修改写穿系统清单), 基本信息仍在系统详情页维护。

职责划分: 各步骤组件通过 StepHandleContext 注册 save/isDirty(内聚各自的 API 调用与校验),
本容器负责状态装载、统一吸底导航(保存并下一步/上一步)、未保存修改的离开拦截、
步骤位置记忆与草稿自动保存。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  App, Alert, Button, Card, Grid, Input, Modal, Progress, Select, Space, Spin, Steps,
  Typography,
} from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons'

import { api } from '../api'
import type { WizardState } from '../types'
import { navigate } from '../router'
import { setLeaveAsker } from './dirtyGuard'
import { StepFooterSlotContext, StepHandleContext, type StepHandle } from './steps/stepContext'
import PageHeader from './PageHeader'

import Step1ProjectInfo from './steps/Step1ProjectInfo'
import Step3Features from './steps/Step3Features'
import Step4DataAssets from './steps/Step4DataAssets'
import Step5PermissionMatrix from './steps/Step5PermissionMatrix'
import Step6ApiList from './steps/Step6ApiList'
import StepInfraAssets from './steps/StepInfraAssets'
import StepSbomComponents from './steps/StepSbomComponents'
import ConfirmStep from './steps/ConfirmStep'

// 标题/描述保持短句, 避免多步并排时在窄屏被挤成竖排
const STEPS: { title: string; description: string }[] = [
  { title: '评估定级', description: '基本信息/外部系统' },
  { title: '功能清单', description: '功能安全' },
  { title: '数据字典', description: '分级与脱敏' },
  { title: '权限矩阵', description: '越权与SoD' },
  { title: 'API接口', description: '匿名/公网' },
  { title: '基础设施', description: '资产/架构图' },
  { title: '组件与许可证', description: 'SBOM' },
  { title: '确认生成', description: '预览/生成' },
]
const LAST = STEPS.length - 1

const stepKey = (projectId: number) => `secreq.wizard.${projectId}.step`

/** 删除评估时同步清理其步骤位置记忆, 避免 localStorage 残留孤儿键。 */
export function clearWizardStepStorage(projectId: number): void {
  try {
    localStorage.removeItem(stepKey(projectId))
  } catch {
    // localStorage 不可用(隐私模式等)时忽略
  }
}

export interface StepProps {
  ws: WizardState
  /** 向导状态局部更新(保存成功后以最新落库实体覆盖对应切片)。 */
  patch: (partial: Partial<WizardState>) => void
  /** 跳转到指定步骤(带未保存修改拦截)。 */
  goto: (index: number) => void
}

export default function WizardPage({ projectId }: { projectId: number }) {
  const { modal, message } = App.useApp()
  const [ws, setWs] = useState<WizardState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState(() => {
    const saved = Number(localStorage.getItem(stepKey(projectId)))
    return Number.isInteger(saved) && saved >= 0 && saved <= LAST ? saved : 0
  })
  const [advancing, setAdvancing] = useState(false)
  // 一键清空(#210): 向导容器级动作, 吸底导航各步可用; 输入评估编码二次确认防误触
  const [resetOpen, setResetOpen] = useState(false)
  const [resetCode, setResetCode] = useState('')
  const [resetting, setResetting] = useState(false)
  // 吸底导航右槽 DOM(#287): 确认页经 Portal 把「生成安全基线」挂进吸底栏
  const [footerSlotEl, setFooterSlotEl] = useState<HTMLDivElement | null>(null)
  // 清空后整卷换新, 递增 key 强制各步骤组件重挂载(避免表单残留旧值)
  const [resetEpoch, setResetEpoch] = useState(0)
  // 草稿恢复提示(#228): 打开向导时已有填报数据则提示一次
  const [resumeNotice] = useState(() => ({ done: false }))
  const handleRef = useRef<StepHandle | null>(null)
  // 草稿自动保存(#228): 30s 间隔静默保存脏步骤; 记录最近一次自动保存时间
  const [autosavedAt, setAutosavedAt] = useState<string | null>(null)
  const autosaveTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  // 窄屏(<992px)把步骤条折叠为「下拉跳转 + 进度条」; 首帧未测得时按宽屏渲染避免闪烁
  const screens = Grid.useBreakpoint()
  const compact = screens.lg === false

  const register = useCallback((h: StepHandle | null) => { handleRef.current = h }, [])
  const patch = useCallback((partial: Partial<WizardState>) => {
    setWs((prev) => (prev ? { ...prev, ...partial } : prev))
  }, [])

  useEffect(() => {
    api.loadWizard(projectId)
      .then((state) => {
        if (!resumeNotice.done) {
          resumeNotice.done = true
          const has = (v: unknown[] | undefined | null) => Array.isArray(v) && v.length > 0
          const hasDraft = has(state.features) || has(state.data_assets) || has(state.external_systems)
            || has(state.api_endpoints) || has(state.roles) || state.survey != null
          if (hasDraft && state.project.status === 'draft') {
            message.info('已恢复上次填报草稿(数据实时保存在服务端), 可从任意步骤继续填写', 4)
          }
        }
        setWs(state)
      })
      .catch((e: Error) => setError(e.message))
  }, [projectId])

  const switchTo = useCallback((idx: number) => {
    setCurrent(idx)
    localStorage.setItem(stepKey(projectId), String(idx))
  }, [projectId])

  /** 弹出「未保存修改」三选确认: 取消 / 不保存 / 保存并离开。 */
  const openLeaveConfirm = useCallback((decide: (d: 'saved' | 'discard' | 'cancel') => void) => {
    const inst = modal.confirm({
      title: '当前步骤有未保存的修改',
      content: '离开前是否保存?选择「不保存」将丢失本次修改。',
      footer: (
        <Space>
          <Button onClick={() => { inst.destroy(); decide('cancel') }}>取消</Button>
          <Button type="primary" danger onClick={() => { inst.destroy(); decide('discard') }}>不保存</Button>
          <Button
            type="primary"
            onClick={() => {
              const h = handleRef.current
              if (!h) { inst.destroy(); decide('cancel'); return }
              void h.save().then((ok) => {
                inst.destroy()
                decide(ok ? 'saved' : 'cancel')
              })
            }}
          >
            保存并离开
          </Button>
        </Space>
      ),
    })
  }, [modal])

  /** 带脏拦截的跳转: 无未保存修改直接走, 有则先弹确认。 */
  const guardLeave = useCallback((go: () => void) => {
    const h = handleRef.current
    if (!h?.isDirty()) { go(); return }
    openLeaveConfirm((d) => {
      if (d === 'cancel') return
      go()
    })
  }, [openLeaveConfirm])

  // 顶部 logo 等全局导航入口的离开询问
  useEffect(() => {
    setLeaveAsker(() => new Promise<boolean>((resolve) => {
      const h = handleRef.current
      if (!h?.isDirty()) { resolve(true); return }
      openLeaveConfirm((d) => {
        if (d === 'cancel') resolve(false)
        else resolve(true)
      })
    }))
    return () => setLeaveAsker(null)
  }, [openLeaveConfirm])

  // 关闭标签页前的浏览器原生保护
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (handleRef.current?.isDirty()) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  // 切步后回到页面顶部
  useEffect(() => { window.scrollTo(0, 0) }, [current])

  // 草稿自动保存(#228): 30s 间隔, 当前步骤有未保存修改时静默保存
  useEffect(() => {
    autosaveTimer.current = setInterval(() => {
      const h = handleRef.current
      if (!h?.isDirty()) return
      void h.save(true)
        .then((ok) => { if (ok) setAutosavedAt(new Date().toLocaleTimeString()) })
        .catch(() => undefined)
    }, 30_000)
    return () => { if (autosaveTimer.current) clearInterval(autosaveTimer.current) }
  }, [])

  const saveAndNext = async () => {
    const h = handleRef.current
    if (!h) { switchTo(current + 1); return }
    setAdvancing(true)
    try {
      const ok = await h.save()
      if (ok) switchTo(current + 1)
    } finally {
      setAdvancing(false)
    }
  }

  /** 一键清空(#172→#210): 清空全部向导输入回到空白模板; 生成产出与系统绑定不动。 */
  const doResetWizard = async () => {
    setResetting(true)
    try {
      await api.resetProjectWizard(projectId)
      setWs(await api.loadWizard(projectId))
      setResetEpoch((n) => n + 1)
      switchTo(0)
      setResetOpen(false)
      setResetCode('')
      message.success('已清空全部向导数据')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setResetting(false)
    }
  }

  if (error) return <Alert style={{ margin: 24 }} type="error" showIcon message={error} />
  if (!ws) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 400 }}><Spin size="large" /></div>
  }

  const done: boolean[] = [
    Boolean(ws.project.name && ws.project.system_id && ws.survey?.effective_level),
    ws.features.length > 0,
    ws.data_assets.length > 0,
    ws.roles.length > 0 && ws.resources.length > 0,
    ws.api_endpoints.length > 0,
    ws.infra_assets.length > 0,
    ws.components.length > 0,
    false,
  ]
  const statusOf = (i: number): 'process' | 'finish' | 'wait' =>
    i === current ? 'process' : done[i] ? 'finish' : 'wait'

  const renderers: ((props: StepProps) => ReactNode)[] = [
    (p) => <Step1ProjectInfo {...p} />,
    (p) => <Step3Features {...p} />,
    (p) => <Step4DataAssets {...p} />,
    (p) => <Step5PermissionMatrix {...p} />,
    (p) => <Step6ApiList {...p} />,
    (p) => <StepInfraAssets {...p} />,
    (p) => <StepSbomComponents {...p} />,
    (p) => <ConfirmStep {...p} />,
  ]

  const footerStyle: CSSProperties = {
    position: 'sticky',
    bottom: 0,
    display: 'grid',
    gridTemplateColumns: '1fr auto 1fr',
    alignItems: 'center',
    background: '#fff',
    margin: '24px -24px -24px',
    padding: '12px 24px',
    borderTop: '1px solid #f0f0f0',
    zIndex: 10,
  }

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        onBack={() => guardLeave(() => navigate('/evaluations'))}
        title={ws.project.name}
        description={[ws.project.code, ws.project.system_name].filter(Boolean).join(' · ') || undefined}
      />

      <Card style={{ marginBottom: 16 }}>
        {compact ? (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Select
                value={current}
                onChange={(idx) => guardLeave(() => switchTo(idx))}
                style={{ flex: 1, minWidth: 0 }}
                options={STEPS.map((s, i) => ({
                  value: i,
                  label: `${done[i] && i !== current ? '✓ ' : ''}${i + 1}. ${s.title}`,
                }))}
              />
              <Typography.Text type="secondary" style={{ whiteSpace: 'nowrap' }}>
                {current + 1} / {STEPS.length}
              </Typography.Text>
            </div>
            <Progress
              percent={Math.round(((current + 1) / STEPS.length) * 100)}
              size="small"
              showInfo={false}
            />
          </Space>
        ) : (
          <Steps
            size="small"
            labelPlacement="vertical"
            current={current}
            onChange={(idx) => idx !== current && guardLeave(() => switchTo(idx))}
            items={STEPS.map((s, i) => ({
              title: s.title,
              description: s.description,
              status: statusOf(i),
            }))}
          />
        )}
      </Card>

      <Card>
        <StepHandleContext.Provider value={{ set: register }}>
          <StepFooterSlotContext.Provider value={footerSlotEl}>
            <div key={resetEpoch} style={{ minHeight: 240 }}>
              {renderers[current]({ ws, patch, goto: (idx) => guardLeave(() => switchTo(idx)) })}
            </div>
            <div style={footerStyle}>
              <div style={{ justifySelf: 'start' }}>
                <Button
                  icon={<ArrowLeftOutlined />}
                  disabled={current === 0}
                  onClick={() => guardLeave(() => switchTo(current - 1))}
                >
                  上一步
                </Button>
              </div>
              {/* 一键清空(DESIGN): 独占底部中间, 不与下一步/提交按钮贴着 */}
              <Button danger disabled={resetting} onClick={() => { setResetCode(''); setResetOpen(true) }}>
                一键清空
              </Button>
              {current < LAST ? (
                <Space size={12} style={{ justifySelf: 'end' }}>
                  {autosavedAt && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      草稿已自动保存 {autosavedAt}
                    </Typography.Text>
                  )}
                  <Button type="primary" loading={advancing} onClick={saveAndNext}>
                    保存并下一步 <ArrowRightOutlined />
                  </Button>
                </Space>
              ) : (
                /* 最后一步(确认页): 主操作经 Portal 挂进此插槽, 长在吸底栏右下角(#287) */
                <div ref={setFooterSlotEl} style={{ justifySelf: 'end', display: 'flex' }} />
              )}
            </div>
          </StepFooterSlotContext.Provider>
        </StepHandleContext.Provider>
      </Card>

      <Modal
        title="一键清空全部向导数据?" open={resetOpen}
        onCancel={() => setResetOpen(false)}
        okText="确认清空" cancelText="取消"
        okButtonProps={{ danger: true, disabled: resetCode.trim() !== ws.project.code }}
        confirmLoading={resetting}
        onOk={() => void doResetWizard()}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="warning" showIcon
            message="不可恢复"
            description="各步骤输入将回到空白模板(系统绑定与已生成的安全需求/SBOM 等产出不受影响)。"
          />
          <div>
            <Typography.Paragraph style={{ marginBottom: 8 }}>
              防误触确认: 请输入本评估编码 <Typography.Text code>{ws.project.code}</Typography.Text> 后再点「确认清空」。
            </Typography.Paragraph>
            <Input
              value={resetCode}
              placeholder={ws.project.code}
              onChange={(e) => setResetCode(e.target.value)}
              onPressEnter={() => { if (resetCode.trim() === ws.project.code && !resetting) void doResetWizard() }}
            />
          </div>
        </Space>
      </Modal>
    </div>
  )
}
