/* 第 6 步「组件与基础设施」(#259): 评估内就地确认系统清单。
   单一事实源仍在系统台账(#194): 本步内嵌系统清单卡, 进入即默认带出系统已存版本
   ("每次评估从系统复制信息"的默认功能), 修改保存写穿系统台账、下一轮评估自动带出
   最新版本 —— "评估确认的信息补充系统"。生成仍按当前清单触发需求, 口径不变。 */
import { useRef } from 'react'
import { Alert, Space } from 'antd'

import {
  SystemComponentsCard, SystemInfraCard,
  type InventoryCardHandle,
} from '../system/SystemInventoryCards'
import type { StepProps } from '../WizardPage'
import { useRegisterStepHandle } from './stepContext'

export default function Step7Inventory({ ws }: StepProps) {
  const infraRef = useRef<InventoryCardHandle | null>(null)
  const compsRef = useRef<InventoryCardHandle | null>(null)

  // 两张卡各自通过 onHandle 上报 save/isDirty, 本步聚合成一个步骤句柄
  useRegisterStepHandle({
    save: async (silent) => {
      const results: boolean[] = []
      for (const h of [infraRef.current, compsRef.current]) {
        if (h) results.push(await h.save(silent))
      }
      return results.every(Boolean)
    },
    isDirty: () => Boolean(infraRef.current?.isDirty() || compsRef.current?.isDirty()),
  })

  const systemId = ws.project.system_id
  if (!systemId) {
    return (
      <Alert
        style={{ maxWidth: 900, margin: '0 auto' }} type="warning" showIcon
        message="本评估未归属系统"
        description="组件与基础设施挂在系统台账维护, 请先回到第 1 步选择所属系统。"
      />
    )
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Alert
        style={{ marginBottom: 16 }} type="info" showIcon
        message="清单默认带出系统台账的已存版本, 确认无误或就地修改后保存"
        description={(
          <span>
            组件与基础设施是<b>系统级</b>信息集合: 本步展示系统台账当前版本, 修改保存后同步更新系统台账,
            下一轮评估自动带出最新版本; 生成时按当前清单触发需求(旧版本漏洞 / 高风险许可证)。
          </span>
        )}
      />
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <SystemComponentsCard systemId={systemId} onHandle={(h) => { compsRef.current = h }} />
        <SystemInfraCard systemId={systemId} onHandle={(h) => { infraRef.current = h }} />
      </Space>
    </div>
  )
}
