/* 离开拦截注册表: 向导等有未保存状态的页面挂载时注册询问器,
   顶部 logo 等全局导航入口在跳转前调用 requestLeave 询问。 */

export type LeaveAsker = () => Promise<boolean>

let asker: LeaveAsker | null = null

/** 页面挂载时注册, 卸载时传 null 注销。 */
export function setLeaveAsker(fn: LeaveAsker | null) {
  asker = fn
}

/** 询问是否允许离开当前页面。resolve(true)=允许, resolve(false)=留在本页。 */
export function requestLeave(): Promise<boolean> {
  return asker ? asker() : Promise.resolve(true)
}
