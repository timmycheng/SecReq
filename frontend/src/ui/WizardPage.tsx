/* 6 步向导容器: 装载整卷状态并分步渲染(#194: 基础设施/组件已上收系统, 在系统详情页维护)。

职责划分: 各步骤组件通过 StepHandleContext 注册 save/isDirty(内聚各自的 API 调用与校验),
本容器负责状态装载、统一吸底导航(保存并下一步/上一步)、未保存修改的离开拦截、
步骤位置记忆与新手引导。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  Alert, App, Breadcrumb, Button, Card, Grid, Progress, Select, Space, Spin, Steps, Typography,
} from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, QuestionCircleOutlined } from '@ant-design/icons'

import { api } from '../api'
import type { WizardState } from '../types'
import { navigate } from '../router'
import { setLeaveAsker } from './dirtyGuard'
import { StepHandleContext, type StepHandle } from './steps/stepContext'

import Step1ProjectInfo from './steps/Step1ProjectInfo'
import Step3Features from './steps/Step3Features'
import Step4DataAssets from './steps/Step4DataAssets'
import Step5PermissionMatrix from './steps/Step5PermissionMatrix'
import Step6ApiList from './steps/Step6ApiList'
import ConfirmStep from './steps/ConfirmStep'

// 标题/描述保持短句, 避免 6 步并排时在窄屏被挤成竖排
const STEPS: { title: string; description: string }[] = [
  { title: '评估定级', description: '基本信息/外部系统' },
  { title: '功能清单', description: '功能安全' },
  { title: '数据字典', description: '分级与脱敏' },
  { title: '权限矩阵', description: '越权与SoD' },
  { title: 'API接口', description: '匿名/公网' },
  { title: '确认生成', description: '预览/生成' },
]
const LAST = STEPS.length - 1

const stepKey = (projectId: number) => `secreq.wizard.${projectId}.step`
const INTRO_DISMISSED_KEY = 'secreq.intro.dismissed'

export interface StepProps {
  ws: WizardState
  /** 向导状态局部更新(保存成功后以最新落库实体覆盖对应切片)。 */
  patch: (partial: Partial<WizardState>) => void
  /** 跳转到指定步骤(带未保存修改拦截)。 */
  goto: (index: number) => void
}

export default function WizardPage({ projectId }: { projectId: number }) {
  const { modal } = App.useApp()
  const [ws, setWs] = useState<WizardState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState(() => {
    const saved = Number(localStorage.getItem(stepKey(projectId)))
    return Number.isInteger(saved) && saved >= 0 && saved <= LAST ? saved : 0
  })
  const [advancing, setAdvancing] = useState(false)
  const [introHidden, setIntroHidden] = useState(
    () => localStorage.getItem(INTRO_DISMISSED_KEY) === '1',
  )
  const handleRef = useRef<StepHandle | null>(null)
  // 窄屏(<992px)把步骤条折叠为「下拉跳转 + 进度条」; 首帧未测得时按宽屏渲染避免闪烁
  const screens = Grid.useBreakpoint()
  const compact = screens.lg === false

  const register = useCallback((h: StepHandle | null) => { handleRef.current = h }, [])
  const patch = useCallback((partial: Partial<WizardState>) => {
    setWs((prev) => (prev ? { ...prev, ...partial } : prev))
  }, [])

  useEffect(() => {
    api.loadWizard(projectId)
      .then(setWs)
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

  if (error) return <Alert style={{ margin: 24 }} type="error" showIcon message={error} />
  if (!ws) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 400 }}><Spin size="large" /></div>
  }

  const done: boolean[] = [
    Boolean(ws.project.name && ws.survey?.effective_level),
    ws.features.length > 0,
    ws.data_assets.length > 0,
    ws.roles.length > 0 && ws.resources.length > 0,
    ws.api_endpoints.length > 0,
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
    (p) => <ConfirmStep {...p} />,
  ]

  const footerStyle: CSSProperties = {
    position: 'sticky',
    bottom: 0,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    background: '#fff',
    margin: '24px -24px -24px',
    padding: '12px 24px',
    borderTop: '1px solid #f0f0f0',
    zIndex: 10,
  }

  return (
    <div style={{ padding: 24 }}>
      <Breadcrumb
        items={[
          {
            title: (
              <a onClick={(e) => { e.preventDefault(); guardLeave(() => navigate('/')) }}>
                评估列表
              </a>
            ),
          },
          { title: `${ws.project.name}(${ws.project.code})` },
          { title: `第 ${current + 1} 步 · ${STEPS[current].title}` },
        ]}
      />

      {!introHidden && (
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          closable
          afterClose={() => {
            setIntroHidden(true)
            localStorage.setItem(INTRO_DISMISSED_KEY, '1')
          }}
          message="第一次使用?"
          description={(
            <span>
              按 1→{STEPS.length} 步完成评估信息采集, 每步点「保存并下一步」即可, 也可点击顶部步骤条随时跳转
              (有未保存修改时会先询问); 最后一步试算预览并一键生成安全需求清单与 SBOM。
              系统的基本信息、基础设施与组件清单在系统台账维护, 不在向导内重复填写。
              第 1 步完成定级后即可预览本评估的合规基线要求。
              各步骤填什么, 看每步顶部说明与术语旁的 <QuestionCircleOutlined style={{ color: '#999' }} /> 图标。
            </span>
          )}
        />
      )}

      <Card style={{ marginTop: 12 }}>
        <StepHandleContext.Provider value={{ set: register }}>
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
          <div style={{ marginTop: 24, minHeight: 240 }}>
            {renderers[current]({ ws, patch, goto: (idx) => guardLeave(() => switchTo(idx)) })}
          </div>
          <div style={footerStyle}>
            <Button
              icon={<ArrowLeftOutlined />}
              disabled={current === 0}
              onClick={() => guardLeave(() => switchTo(current - 1))}
            >
              上一步
            </Button>
            {current < LAST ? (
              <Button type="primary" loading={advancing} onClick={saveAndNext}>
                保存并下一步 <ArrowRightOutlined />
              </Button>
            ) : (
              <Typography.Text type="secondary">确认无误后, 点击本页下方「生成安全基线」按钮</Typography.Text>
            )}
          </div>
        </StepHandleContext.Provider>
      </Card>
    </div>
  )
}
