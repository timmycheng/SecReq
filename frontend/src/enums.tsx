/* 枚举常量上下文: 全部选项与中文标签由后端 /api/meta/constants 统一供给,
   前端不硬编码任何业务枚举(DESIGN.md 约束第七节)。 */
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Spin } from 'antd'

import { api, type Constants } from './api'
import type { LabelMap } from './types'

const EnumsContext = createContext<Constants | null>(null)

export function EnumsProvider({ children }: { children: ReactNode }) {
  const [constants, setConstants] = useState<Constants | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.constants().then(setConstants).catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <Spin tip={`常量加载失败: ${error}`}><div style={{ height: 200 }} /></Spin>
  if (!constants) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="正在加载枚举常量…" />
      </div>
    )
  }
  return <EnumsContext.Provider value={constants}>{children}</EnumsContext.Provider>
}

export function useEnums(): Constants {
  const ctx = useContext(EnumsContext)
  if (!ctx) throw new Error('useEnums 必须在 <EnumsProvider> 内使用')
  return ctx
}

/** code→label 映射常量取值(不存在时回退空表)。 */
export function labelMapOf(constants: Constants, key: string): LabelMap {
  const raw = constants[key]
  return (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as LabelMap : {}
}

/** Select/Cascader 通用 options。 */
export function optionsOf(constants: Constants, key: string): { value: string; label: string }[] {
  return Object.entries(labelMapOf(constants, key)).map(([value, label]) => ({ value, label }))
}

/** 按 code 取中文标签, 未注册的 code 原样返回(与 shared/constants.py 的 label 行为一致)。 */
export function labelOf(constants: Constants, key: string, code?: string | null): string {
  if (!code) return ''
  return labelMapOf(constants, key)[code] ?? code
}
