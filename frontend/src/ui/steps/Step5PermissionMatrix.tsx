/* Step5 用户权限矩阵: 左侧角色行 × 顶部资源列的交叉表格。
   单元格内勾选操作(create/read/...), 高危操作可挂"需审批"标记;
   critical 资源的免审批高危操作、SoD 冲突与 super_admin 特权账号
   由规则引擎自动扫描并生成整改需求。 */
import { useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  Button, Checkbox, Input, InputNumber, Popover, Select, Space,
  Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import type { MatrixEntryIn } from '../../types'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type { RoleRow, ResourceRow } from '../../types'
import type { StepProps } from '../WizardPage'

/** cell[roleIndex][resourceIndex] = { 动作code → 是否需审批 }(键为下标的字符串形态) */
type CellGrants = Record<string, Record<string, Record<string, boolean>>>

const EMPTY_ROLE: RoleRow = { name: '', role_type: 'normal', user_count_estimate: 0 }
const EMPTY_RESOURCE: ResourceRow = { name: '', resource_type: 'data_record', criticality: 'medium' }

export default function Step5PermissionMatrix({ ws, patch, advance }: StepProps) {
  const enums = useEnums()
  const [roles, setRoles] = useState<RoleRow[]>(ws.roles)
  const [resources, setResources] = useState<ResourceRow[]>(ws.resources)
  const [grants, setGrants] = useState<CellGrants>(() => initGrants(ws))
  const [saving, setSaving] = useState(false)

  const actionsMap = labelMapOf(enums, 'permission_actions')
  const highRisk = new Set((enums['high_risk_actions'] as string[]) ?? [])

  const updateGrant = (ri: number, ci: number, action: string, checked: boolean) => {
    setGrants((prev) => {
      const next: CellGrants = { ...prev }
      const row = { ...(next[String(ri)] ?? {}) }
      const cell = { ...(row[String(ci)] ?? {}) }
      if (checked) cell[action] = cell[action] ?? false
      else delete cell[action]
      row[String(ci)] = cell
      next[String(ri)] = row
      return next
    })
  }
  const updateApproval = (ri: number, ci: number, action: string, needs: boolean) => {
    setGrants((prev) => {
      const next: CellGrants = JSON.parse(JSON.stringify(prev))
      next[String(ri)][String(ci)][action] = needs
      return next
    })
  }

  const totalEntries = useMemo(
    () => Object.values(grants).reduce(
      (n, row) => n + Object.values(row).reduce((m, cell) => m + Object.keys(cell).length, 0), 0),
    [grants],
  ) as number

  const warnings = useMemo(() => {
    const list: string[] = []
    for (const r of roles) {
      if (r.role_type === 'super_admin') list.push(`存在超级管理员角色「${r.name}」, 将生成最小权限原则与特权账号审计需求`)
    }
    for (const [riStr, row] of Object.entries(grants)) {
      for (const [ciStr, cell] of Object.entries(row)) {
        const res = resources[Number(ciStr)]
        if (!res || !cell) continue
        const roleName = roles[Number(riStr)]?.name ?? '?'
        const risky = Object.keys(cell).filter((a) => highRisk.has(a) && !cell[a])
        if (res.criticality === 'critical' && risky.length) {
          list.push(`${roleName} 对关键资源「${res.name}」执行 ${risky.map((a) => actionsMap[a]).join('/')} 未挂审批流, 将触发高优先级整改需求`)
        }
        const conflictPairs: [string, string][] = [['create', 'approve'], ['update', 'approve'], ['config_change', 'approve']]
        for (const [a, b] of conflictPairs) {
          if ((['high', 'critical'] as string[]).includes(res.criticality)
              && cell[a] !== undefined && cell[b] !== undefined) {
            list.push(`${roleName} 在「${res.name}」上同时拥有 ${actionsMap[a]} 与 ${actionsMap[b]}, 存在职责分离(SoD)冲突`)
          }
        }
      }
    }
    return [...new Set(list)]
  }, [grants, roles, resources, actionsMap, highRisk])

  const save = async () => {
    if (!roles.length || !resources.length) {
      message.warning('请至少维护一个角色和一个资源')
      return
    }
    const entries: MatrixEntryIn[] = []
    for (const [riStr, row] of Object.entries(grants)) {
      for (const [ciStr, cell] of Object.entries(row)) {
        for (const [action, needsApproval] of Object.entries(cell)) {
          entries.push({ role_index: Number(riStr), resource_index: Number(ciStr), action, requires_approval: !!needsApproval })
        }
      }
    }
    setSaving(true)
    try {
      const saved = await api.saveMatrix(ws.project.id, roles, resources, entries)
      patch({
        roles: saved.roles,
        resources: saved.resources,
        permission_entries: saved.entries as never,
      })
      message.success(`矩阵已保存: ${saved.saved.roles} 角色 × ${saved.saved.resources} 资源, ${saved.saved.entries} 条授权`)
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* ── 角色维护 ── */}
        <div>
          <Typography.Text strong>角色</Typography.Text>
          <RoleResourceEditor<RoleRow>
            rows={roles}
            empty={EMPTY_ROLE}
            onChange={setRoles}
            newRow={() => ({ ...EMPTY_ROLE })}
            columns={(row, setRow, removeBtn) => (
              <>
                <Input size="small" style={{ width: 160 }} value={row.name} placeholder="角色名"
                  onChange={(e) => setRow({ ...row, name: e.target.value })} />
                <Select size="small" style={{ width: 130 }} value={row.role_type}
                  options={optionsOf(enums, 'role_types')}
                  onChange={(v) => setRow({ ...row, role_type: v })} />
                <InputNumber size="small" min={0} value={row.user_count_estimate}
                  onChange={(v) => setRow({ ...row, user_count_estimate: v ?? 0 })} />
                {removeBtn}
              </>
            )}
          />
          {/* ── 资源维护 ── */}
          <Typography.Text strong>资源</Typography.Text>
          <RoleResourceEditor<ResourceRow>
            rows={resources}
            empty={EMPTY_RESOURCE}
            onChange={setResources}
            newRow={() => ({ ...EMPTY_RESOURCE })}
            columns={(row, setRow, removeBtn) => (
              <>
                <Input size="small" style={{ width: 200 }} value={row.name} placeholder="资源名"
                  onChange={(e) => setRow({ ...row, name: e.target.value })} />
                <Select size="small" style={{ width: 140 }} value={row.resource_type}
                  options={optionsOf(enums, 'resource_types')}
                  onChange={(v) => setRow({ ...row, resource_type: v })} />
                <Select size="small" style={{ width: 100 }} value={row.criticality}
                  options={optionsOf(enums, 'criticality_levels')}
                  onChange={(v) => setRow({ ...row, criticality: v })} />
                {removeBtn}
              </>
            )}
          />
        </div>

        {/* ── 交叉表格 ── */}
        <div>
          <Typography.Text strong>权限矩阵(点击单元格勾选操作, * 表示该操作需审批)</Typography.Text>
          <table className="matrix-table" style={{ borderCollapse: 'collapse', marginTop: 8, minWidth: 700 }}>
            <thead>
              <tr>
                <th style={cellStyle('#2f5597', '#fff')}>角色 \ 资源</th>
                {resources.map((r, ci) => (
                  <th key={ci} style={cellStyle('#2f5597', '#fff')}>
                    {r.name}
                    <div>
                      <Tag color={CRITICALITY_COLOR[labelMapOf(enums, 'criticality_levels')[r.criticality]]}>
                        {labelMapOf(enums, 'criticality_levels')[r.criticality] ?? r.criticality}
                      </Tag>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {roles.map((role, ri) => (
                <tr key={ri}>
                  <td style={cellStyle('#fafafa')}>
                    <b>{role.name}</b><br />
                    <Tag color={ROLE_TYPE_COLOR[role.role_type]}>
                      {labelMapOf(enums, 'role_types')[role.role_type] ?? role.role_type}
                    </Tag>
                    <span style={{ color: '#999', fontSize: 12 }}>{role.user_count_estimate} 人</span>
                  </td>
                  {resources.map((_res, ci) => {
                    const cell = grants[String(ri)]?.[String(ci)] ?? {}
                    const granted = Object.keys(cell)
                    return (
                      <td key={ci} style={cellStyle()}>
                        <MatrixCellPopover
                          actionsMap={actionsMap}
                          highRisk={highRisk}
                          granted={cell}
                          onToggleAction={(a, c) => updateGrant(ri, ci, a, c)}
                          onToggleApproval={(a, needs) => updateApproval(ri, ci, a, needs)}
                        >
                          {granted.length === 0
                            ? <span style={{ color: '#bbb' }}>＋ 授权</span>
                            : granted.map((a) => `${actionsMap[a] ?? a}${cell[a] ? '*' : ''}`).join('、')}
                        </MatrixCellPopover>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <Typography.Text type="secondary">
            共 {roles.length} 角色 × {resources.length} 资源 · 已登记授权 {totalEntries} 格次 · 「需审批」以 * 标注
          </Typography.Text>
        </div>

        {warnings.length > 0 && (
          <div style={{ background: '#fff7e6', border: '1px solid #ffd591', borderRadius: 6, padding: '8px 12px' }}>
            <Typography.Text strong type="warning">实时风险提示(规则引擎会据此生成需求):</Typography.Text>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {warnings.map((w, i) => <li key={i}><Typography.Text type="warning">{w}</Typography.Text></li>)}
            </ul>
          </div>
        )}

        <Button type="primary" loading={saving} onClick={save}>保存矩阵并下一步</Button>
      </Space>
    </div>
  )
}

function initGrants(ws: StepProps['ws']): CellGrants {
  const roleIdx = new Map(ws.roles.map((r, i) => [r.id as number, i]))
  const resIdx = new Map(ws.resources.map((r, i) => [r.id as number, i]))
  const cell: CellGrants = {}
  for (const entry of ws.permission_entries) {
    const ri = roleIdx.get(entry.role_id)
    const ci = resIdx.get(entry.resource_id)
    if (ri === undefined || ci === undefined) continue
    ;((cell[ri] ??= {})[ci] ??= {})[entry.action] = !!entry.requires_approval
  }
  return cell
}

function MatrixCellPopover({ children, granted, actionsMap, highRisk, onToggleAction, onToggleApproval }: {
  children: ReactNode
  granted: Record<string, boolean>
  actionsMap: Record<string, string>
  highRisk: Set<string>
  onToggleAction: (action: string, checked: boolean) => void
  onToggleApproval: (action: string, needs: boolean) => void
}) {
  return (
    <Popover
      trigger="click"
      placement="bottom"
      content={
        <div style={{ maxHeight: 300, overflowY: 'auto' }}>
          {Object.entries(actionsMap).map(([action, label]) => (
            <div key={action} style={{ marginBottom: 4 }}>
              <Checkbox
                checked={action in granted}
                onChange={(e) => onToggleAction(action, e.target.checked)}
              >
                {label}
                {highRisk.has(action) && <Tag color="red" style={{ marginLeft: 6 }}>高危</Tag>}
              </Checkbox>
              {' '}
              {action in granted && highRisk.has(action) && (
                <Checkbox
                  style={{ marginLeft: 28 }}
                  checked={!!granted[action]}
                  onChange={(e) => onToggleApproval(action, e.target.checked)}
                >
                  需审批
                </Checkbox>
              )}
            </div>
          ))}
        </div>
      }
    >
      <Button block size="small" style={{ minHeight: 32 }}>{children}</Button>
    </Popover>
  )
}

function RoleResourceEditor<T extends { id?: number }>({ rows, onChange, columns, newRow }: {
  rows: T[]
  empty: T
  newRow: () => T
  onChange: (rows: T[]) => void
  columns: (row: T, setRow: (r: T) => void, removeBtn: ReactNode) => React.ReactNode
}) {
  return (
    <div style={{ margin: '8px 0 12px' }}>
      {rows.map((row, i) => (
        <Space key={i} size={6} style={{ marginBottom: 4 }}>
          {columns(row, (r) => {
            const copy = [...rows]; copy[i] = r; onChange(copy)
          }, (
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => onChange(rows.filter((_, idx) => idx !== i))} />
          ))}
        </Space>
      ))}
      <div>
        <Button size="small" icon={<PlusOutlined />} onClick={() => onChange([...rows, newRow()])}>
          添加
        </Button>
      </div>
    </div>
  )
}


const ROLE_TYPE_COLOR: Record<string, string> = {
  super_admin: 'red', privileged: 'orange', normal: 'blue',
}
const CRITICALITY_COLOR: Record<string, string> = {
  低: 'default', 中: 'gold', 高: 'volcano', 关键: 'red',
}

function cellStyle(bg?: string, color?: string): CSSProperties {
  return {
    border: '1px solid #e8e8e8',
    padding: '8px 10px',
    textAlign: 'center',
    minWidth: 150,
    verticalAlign: 'middle',
    ...(bg ? { background: bg } : {}),
    ...(color ? { color } : {}),
  }
}
