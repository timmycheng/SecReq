/* 向导第 6 步「基础设施」(#289 自「组件与基础设施」拆出): 评估内就地确认系统级
   基础设施清单(资产台账 + 分环境架构图)。单一事实源在系统清单, 本步内嵌
   SystemInfraCard, 修改保存写穿系统清单, 下一轮评估自动带出最新版本。 */
import { useRef } from 'react'
import { Alert } from 'antd'

import { SystemInfraCard } from '../system/SystemInfraCard'
import type { InventoryCardHandle } from '../system/inventoryCommon'
import type { StepProps } from '../WizardPage'
import { useRegisterStepHandle } from './stepContext'

export default function StepInfraAssets({ ws, patch }: StepProps) {
  const handleRef = useRef<InventoryCardHandle | null>(null)
  useRegisterStepHandle({
    save: async (silent) => (handleRef.current ? handleRef.current.save(silent) : true),
    isDirty: () => Boolean(handleRef.current?.isDirty()),
  })

  const systemId = ws.project.system_id
  if (!systemId) {
    return (
      <Alert
        style={{ maxWidth: 900, margin: '0 auto' }} type="warning" showIcon
        message="本评估未归属系统"
        description="基础设施挂在系统清单维护, 请先回到第 1 步选择所属系统。"
      />
    )
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Alert
        style={{ marginBottom: 16 }} type="info" showIcon
        message="清单默认带出系统清单的已存版本, 确认无误或就地修改后保存"
        description={(
          <span>
            基础设施是<b>系统级</b>信息: 本步展示系统清单当前版本(资产台账 + 分环境架构图),
            修改保存后同步更新系统清单, 下一轮评估自动带出最新版本; 生成时按当前清单触发需求。
          </span>
        )}
      />
      <SystemInfraCard
        systemId={systemId} onHandle={(h) => { handleRef.current = h }}
        onSaved={(rows) => patch({ infra_assets: rows })}
      />
    </div>
  )
}
