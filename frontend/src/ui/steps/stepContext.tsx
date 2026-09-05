/* 步骤句柄上下文: 各步骤把 save/isDirty 注册给向导容器,
   容器的吸底导航与离开拦截通过句柄调用, 步骤自身不再渲染保存按钮。 */
import { createContext, useContext, useEffect, useRef, useState } from 'react'

import { api } from '../../api'

export interface StepHandle {
  /** 保存本步; 校验失败或请求出错时返回 false(错误提示由步骤内部负责)。
   *  silent=true 为草稿自动保存(#228), 不弹成功提示。 */
  save: (silent?: boolean) => Promise<boolean>
  /** 本步是否有未保存修改。 */
  isDirty: () => boolean
}

export const StepHandleContext = createContext<{ set: (h: StepHandle | null) => void }>({
  set: () => {},
})

/** 每次渲染后重新注册(句柄闭包始终指向最新状态), 卸载时注销。 */
export function useRegisterStepHandle(handle: StepHandle) {
  const ctx = useContext(StepHandleContext)
  useEffect(() => {
    ctx.set(handle)
    return () => ctx.set(null)
  })
}


/** 基线 uid 索引(#224): 行 uid 命中 → 「基线继承」, 未命中 → 「本轮新增」; 无基线返回 null。 */
export function useBaselineUidIndex(
  systemId: number | null | undefined,
): Record<string, string[]> | null {
  const [index, setIndex] = useState<Record<string, string[]> | null>(null)
  useEffect(() => {
    if (!systemId) return
    let alive = true
    api.getSystem(systemId)
      .then((s) => { if (alive) setIndex(s.baseline?.uid_index ?? null) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [systemId])
  return index
}


/** 步骤停留计时(#229): 挂载到保存成功的时长, 供「保存并下一步」上报。 */
export function useStepDwell(): { elapsed: () => number } {
  const mountedAt = useRef(Date.now())
  useEffect(() => { mountedAt.current = Date.now() }, [])
  return { elapsed: () => Math.round((Date.now() - mountedAt.current) / 1000) }
}
