/* 步骤句柄上下文: 各步骤把 save/isDirty 注册给向导容器,
   容器的吸底导航与离开拦截通过句柄调用, 步骤自身不再渲染保存按钮。 */
import { createContext, useContext, useEffect } from 'react'

export interface StepHandle {
  /** 保存本步; 校验失败或请求出错时返回 false(错误提示由步骤内部负责)。 */
  save: () => Promise<boolean>
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
