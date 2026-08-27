/* 8 步向导容器: 装载整卷状态并分步渲染。

职责划分: 每个步骤组件自带"保存并下一步"按钮(内聚各自的 API 调用与校验),
本容器只负责状态装载、步骤条流转与向导状态的局部更新。
*/
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Card, Spin, Steps } from 'antd'

import { api } from '../api'
import type { WizardState } from '../types'

import Step1BasicInfo from './steps/Step1BasicInfo'
import Step2Survey from './steps/Step2Survey'
import Step3Features from './steps/Step3Features'
import Step4DataAssets from './steps/Step4DataAssets'
import Step5PermissionMatrix from './steps/Step5PermissionMatrix'
import Step6AuthPolicy from './steps/Step6AuthPolicy'
import Step7Components from './steps/Step7Components'
import Step8Inventory from './steps/Step8Inventory'
import ConfirmStep from './steps/ConfirmStep'

const STEP_TITLES = ['项目基本信息', '等保定级问卷', '功能清单', '数据字典',
  '用户权限矩阵', '认证与密码策略', '软件/框架清单', '接口与资产清单', '确认生成']

export interface StepProps {
  ws: WizardState
  /** 向导状态局部更新(保存成功后以最新落库实体覆盖对应切片)。 */
  patch: (partial: Partial<WizardState>) => void
  /** 进入下一步(由各步骤保存成功后调用)。 */
  advance: () => void
}

export default function WizardPage({ projectId }: { projectId: number }) {
  const [ws, setWs] = useState<WizardState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState(0)

  const patch = (partial: Partial<WizardState>) => {
    setWs((prev) => (prev ? { ...prev, ...partial } : prev))
  }

  useEffect(() => {
    api.loadWizard(projectId)
      .then(setWs)
      .catch((e: Error) => setError(e.message))
  }, [projectId])

  if (error) return <Alert style={{ margin: 24 }} type="error" showIcon message={error} />
  if (!ws) {
    return <div style={{ display: 'grid', placeItems: 'center', height: 400 }}><Spin size="large" /></div>
  }

  const renderers: ((props: StepProps) => ReactNode)[] = [
    (p) => <Step1BasicInfo {...p} />,
    (p) => <Step2Survey {...p} />,
    (p) => <Step3Features {...p} />,
    (p) => <Step4DataAssets {...p} />,
    (p) => <Step5PermissionMatrix {...p} />,
    (p) => <Step6AuthPolicy {...p} />,
    (p) => <Step7Components {...p} />,
    (p) => <Step8Inventory {...p} />,
    (p) => <ConfirmStep {...p} />,
  ]

  return (
    <div style={{ padding: 24 }}>
      <Card>
        <Steps
          current={current}
          items={STEP_TITLES.map((title) => ({ title }))}
          onChange={(idx) => setCurrent(idx)}
          size="small"
        />
        <div style={{ marginTop: 20 }}>{renderers[current]({ ws, patch, advance: () => setCurrent((c) => c + 1) })}</div>
      </Card>
    </div>
  )
}
