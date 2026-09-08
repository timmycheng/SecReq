/* 系统清单维护卡共用件(#289 自 SystemInventoryCards 拆分时沉淀)。 */

/** 向导步骤句柄(#259): 与 steps/stepContext 的 StepHandle 同构。 */
export interface InventoryCardHandle {
  /** 保存清单; 未修改时短路返回 true, 校验/请求失败返回 false(提示由卡片内部负责)。 */
  save: (silent?: boolean) => Promise<boolean>
  isDirty: () => boolean
}
