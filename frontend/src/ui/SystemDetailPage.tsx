/* 系统详情: 基本信息(可编辑) + 备案定级事实 + 评估时间线 + 系统清单维护(#194)。
   同一系统多次评估在这里形成时间线; 最新已生成轮次即"当前有效基线"。
   基础设施与组件挂系统维护(#194), 多轮评估共享同一份清单, 不再随轮次复制。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Space, Spin, Tag, Timeline, Typography, message,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import { LevelTag, RoundCell, SystemFormModal } from './SystemsPage'
import { SystemComponentsCard, SystemInfraCard } from './system/SystemInventoryCards'
import type { FilingRow, SystemRow } from '../types'

export default function SystemDetailPage({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const [system, setSystem] = useState<SystemRow | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [filings, setFilings] = useState<FilingRow[]>([])

  const reload = useCallback(() => {
    api.getSystem(systemId)
      .then(setSystem)
      .catch((e: Error) => message.error(e.message))
  }, [systemId])
  useEffect(reload, [reload])
  useEffect(() => { api.listFilings().then(setFilings).catch(() => undefined) }, [])

  if (!system) {
    return <div style={{ padding: 24 }}><Spin /></div>
  }

  const startNewRound = async () => {
    setCreating(true)
    try {
      const rounds = system.rounds ?? []
      const detail = await api.createProject({
        name: `${system.name} 评估`,
        system_id: system.id,
        // 评估继承: 有历史轮次时整卷复制(含定级问卷), 只改变化部分(#151)
        from_project_id: rounds.length ? rounds[0].project_id : undefined,
      })
      message.success(rounds.length
        ? '已按上一轮评估创建新一轮, 请在向导中核对并修改变化部分'
        : '已创建新一轮评估, 请在向导第一步核对信息')
      navigate(`/wizard/${detail.id}`)
    } catch (e) {
      message.error((e as Error).message)
      setCreating(false)
    }
  }

  const rounds = system.rounds ?? []
  const typeLabels = labelMapOf(enums, 'project_types')
  const scaleLabels = labelMapOf(enums, 'user_scales')
  return (
    <div style={{ padding: 24, maxWidth: 1080, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/systems')}>返回台账</Button>
      </Space>
      <Card
        title={system.name}
        extra={(
          <Space>
            <Button onClick={() => setEditing(true)}>编辑信息</Button>
            <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void startNewRound()}>
              发起新一轮评估
            </Button>
          </Space>
        )}
      >
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="系统编号">{system.code || '—'}</Descriptions.Item>
          <Descriptions.Item label="所属备案">
            {system.filing_name
              ? <Space size={6}>{system.filing_name}<LevelTag level={system.filing_level} /></Space>
              : <Typography.Text type="secondary">未挂备案(定级走评估问卷)</Typography.Text>}
          </Descriptions.Item>
          <Descriptions.Item label="负责人">{system.owner_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="用户规模">{scaleLabels[system.user_scale ?? ''] ?? (system.user_scale || '—')}</Descriptions.Item>
          <Descriptions.Item label="业务类型">
            {(system.types ?? []).map((t) => typeLabels[t] ?? t).join('、') || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="公网访问">
            {system.is_public ? <Tag color="orange">涉及公网</Tag> : <Tag>无公网</Tag>}
          </Descriptions.Item>
        </Descriptions>
        {system.filing_level && (
          <Alert
            style={{ marginTop: 4 }}
            type="info"
            showIcon
            message={`定级来源: 备案「${system.filing_name}」(等保${system.filing_level})`}
            description="向导中的定级问卷会预填备案定级; 若评估后人工调整了定级, 结果页会提示与备案不一致。"
          />
        )}
      </Card>

      <Card title="安全基线(D 区)" style={{ marginTop: 16 }} variant="borderless">
        {system.baseline ? (
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="数据资产">{system.baseline.summary?.data_assets ?? 0}</Descriptions.Item>
            <Descriptions.Item label="数据字典表">{system.baseline.summary?.data_tables ?? 0}</Descriptions.Item>
            <Descriptions.Item label="API 清单">{system.baseline.summary?.api_endpoints ?? 0}</Descriptions.Item>
            <Descriptions.Item label="权限矩阵">
              角色 {system.baseline.summary?.roles ?? 0} · 资源 {system.baseline.summary?.resources ?? 0} ·
              授权 {system.baseline.summary?.permission_entries ?? 0}
            </Descriptions.Item>
            <Descriptions.Item label="来源轮次">
              {system.baseline.source_project_id
                ? <Button type="link" size="small" style={{ padding: 0 }}
                    onClick={() => navigate(`/result/${system.baseline!.source_project_id}`)}>
                    第 {system.baseline!.source_project_id} 轮评估
                  </Button>
                : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="写回时间">
              {system.baseline.updated_at?.slice(0, 19).replace('T', ' ') ?? '—'}
              {system.baseline.updated_by ? ` · ${system.baseline.updated_by}` : ''}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">
            暂无安全基线。评估轮次终审通过后, 本轮资产/字典/权限/接口快照将写回为系统基线(v3.0 #225)。
          </Typography.Text>
        )}
        {(system.baseline_histories?.length ?? 0) > 0 && (
          <>
            <Typography.Paragraph strong style={{ margin: '12px 0 4px' }}>基线变更履历</Typography.Paragraph>
            <Timeline
              style={{ marginTop: 8 }}
              items={(system.baseline_histories ?? []).map((h) => ({
                children: (
                  <div>
                    <Typography.Text>{h.summary}</Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                      {h.created_at?.slice(0, 19).replace('T', ' ') ?? ''}
                      {h.operator_name ? ` · ${h.operator_name}` : ''}
                      {h.project_id ? ` · 依据第 ${h.project_id} 轮评审` : ''}
                    </Typography.Text>
                  </div>
                ),
              }))}
            />
          </>
        )}
      </Card>

      <Card title="评估时间线" style={{ marginTop: 16 }} variant="borderless">
        {rounds.length === 0 ? (
          <Typography.Text type="secondary">
            还没有评估记录, 点右上角「发起新一轮评估」开始。
          </Typography.Text>
        ) : (
          <Timeline
            style={{ marginTop: 8 }}
            items={rounds.map((r, idx) => ({
              color: r.status === 'generated' ? 'green' : 'gray',
              children: (
                <div style={{ paddingBottom: idx === rounds.length - 1 ? 0 : 8 }}>
                  <Space size={8} wrap align="center">
                    <Typography.Text strong>{r.project_name}</Typography.Text>
                    {system.current_baseline_project_id === r.project_id && (
                      <Tag color="cyan">当前基线</Tag>
                    )}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {r.created_at?.slice(0, 10) || ''}
                    </Typography.Text>
                  </Space>
                  <div style={{ marginTop: 4 }}><RoundCell round={r} /></div>
                  <Space size={8} style={{ marginTop: 6 }}>
                    <Button size="small" onClick={() => navigate(`/wizard/${r.project_id}`)}>
                      {r.status === 'generated' ? '再编辑' : '继续填写'}
                    </Button>
                    {r.status === 'generated' && (
                      <Button size="small" type="primary" ghost onClick={() => navigate(`/result/${r.project_id}`)}>
                        查看产物
                      </Button>
                    )}
                  </Space>
                </div>
              ),
            }))}
          />
        )}
      </Card>

      <div style={{ marginTop: 16 }}>
        <SystemInfraCard systemId={system.id} />
      </div>
      <div style={{ marginTop: 16 }}>
        <SystemComponentsCard systemId={system.id} />
      </div>

      {editing && (
        <SystemFormModal
          value={system}
          filings={filings}
          enums={enums}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); reload() }}
        />
      )}
    </div>
  )
}
