/**
 * UI 状态 tokens(#234): 全局唯一色值来源, 各页面只允许从这里取色。
 *
 * - Tag 场景: 直接用 antd 预设色名(本模块导出的映射值);
 * - style={{ color }} 场景: 用下方 HEX(取 antd 预设色值, 集中声明);
 * - 纯排版灰阶(边框/底色)不在此列; CSS 内的状态色用 index.css 顶部 CSS 变量。
 * 语义与文案细则见 docs/frontend-design-spec.md, 本模块与其一一对应。
 */

// ── 需求评审生命周期(#217 状态机): open=灰 / confirmed=蓝 / reviewed=绿 / rectifying=橙
export const REQUIREMENT_STATUS_COLOR: Record<string, string> = {
  open: 'default', confirmed: 'blue', reviewed: 'green', rectifying: 'orange',
}

// ── 评审门禁(ReviewGate 状态 + 提交校验返回态 blocked)
export const GATE_STATUS_COLOR: Record<string, string> = {
  pending: 'default', in_review: 'blue', blocked: 'red',
  passed: 'green', rejected: 'red', rectifying: 'orange',
}

// ── 数据分级 L1-L5: 1级=灰 / 2级=蓝 / 3级=黄 / 4级=火山橙(volcano) / 5级=红
export const DATA_LEVEL_COLOR: Record<string, string> = {
  '1级_公开数据': 'default',
  '2级_C1次要信息': 'blue',
  '3级_C2主要信息': 'gold',
  '4级_C3鉴别信息': 'volcano',
  '5级_重要数据': 'red',
}

// ── 等保定级: 与数据分级同 ramp(#234 定夺, 留痕见规范)——一级=灰 / 二级=蓝 / 三级=黄;
// 等保级别表达合规强度而非风险警示, 不用红色; 四/五级为未来扩档预留。
export const GRADING_LEVEL_COLOR: Record<string, string> = {
  '一级': 'default', '二级': 'blue', '三级': 'gold', '四级': 'volcano', '五级': 'red',
}

// ── 需求优先级与漏洞危害级(同一 ramp, 语义不同故导出两个名字, 只此一份定义)
export const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}
export const SEVERITY_COLOR = PRIORITY_COLOR

// ── 语义 hex(antd 预设色值, 供 style 场景引用)
export const HEX = {
  /** antd red-6: 错误/高危提示文字 */
  danger: '#cf1322',
  /** antd orange-7: 中风险提示文字 */
  warning: '#d46b08',
  /** antd green-6: 低风险/正常提示文字 */
  success: '#52c41a',
} as const

// ── 风险三态文字色(高/中/低, 引用上方语义 hex)
export const RISK_TEXT_COLOR: Record<string, string> = {
  high: HEX.danger, medium: HEX.warning, low: HEX.success,
}
