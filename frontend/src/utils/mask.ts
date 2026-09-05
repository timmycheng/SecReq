/**
 * 敏感值掩码工具(#235): 列表页默认「前3后4」, 详情页点击可见。
 * 现系统暂不落真实敏感值, 先落工具备用; 有值展示的功能(如字典示例)接入时直接引用。
 */
export function maskSensitive(value: string | null | undefined): string {
  const text = (value ?? '').trim()
  if (!text) return ''
  if (text.length <= 7) return '*'.repeat(text.length)
  return text.slice(0, 3) + '*'.repeat(Math.max(4, text.length - 7)) + text.slice(-4)
}
