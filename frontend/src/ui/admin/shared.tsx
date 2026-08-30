/* 系统管理页各 Tab 共用的小部件与常量。 */
import { InputNumber, Space, Typography } from 'antd'

export const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}

export function NumField({ label, value, onChange }: {
  label: string
  value: number
  onChange: (v: number | null) => void
}) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <InputNumber style={{ width: 140 }} value={value} min={1} onChange={(v) => onChange(v ?? null)} />
    </Space>
  )
}
