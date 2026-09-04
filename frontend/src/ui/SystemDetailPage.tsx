/* 系统详情: 备案定级事实 + 评估时间线(全部轮次) + 基础设施清单(#177) + 发起新一轮评估。
   同一系统多次评估在这里形成时间线; 最新已生成轮次即"当前有效基线",
   其基础设施清单作为该系统现状的单一事实来源只读展示。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Space, Spin, Table, Tag, Timeline, Typography, message,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'

import { api } from '../api'
import { labelMapOf, useEnums } from '../enums'
import { navigate } from '../router'
import { LevelTag, RoundCell } from './SystemsPage'
import type { InfraAssetRow, SystemRow } from '../types'

const ENV_LABELS: Record<string, string> = { prod: '生产', test: '测试', dev: '开发' }

/** 基础设施清单取自最新一轮评估(优先已生成轮次, #177)。 */
function pickInfraSourceRound(system: SystemRow) {
  const rounds = system.rounds ?? []
  return rounds.find((r) => r.status === 'generated') ?? rounds[0] ?? null
}

export default function SystemDetailPage({ systemId }: { systemId: number }) {
  const enums = useEnums()
  const [system, setSystem] = useState<SystemRow | null>(null)
  const [creating, setCreating] = useState(false)
  /** 基础设施清单缓存: 记录来源轮次 project_id, 防止切换系统时串显旧数据(#177) */
  const [infra, setInfra] = useState<{ roundId: number; rows: InfraAssetRow[] } | null>(null)

  const reload = useCallback(() => {
    api.getSystem(systemId)
      .then(setSystem)
      .catch((e: Error) => message.error(e.message))
  }, [systemId])
  useEffect(reload, [reload])

  useEffect(() => {
    if (!system) return
    const round = pickInfraSourceRound(system)
    if (!round) return
    let cancelled = false
    api.getInfraAssets(round.project_id)
      .then((rows) => { if (!cancelled) setInfra({ roundId: round.project_id, rows }) })
      .catch(() => { if (!cancelled) setInfra({ roundId: round.project_id, rows: [] }) })
    return () => { cancelled = true }
  }, [system])

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
  return (
    <div style={{ padding: 24, maxWidth: 1080, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/systems')}>返回台账</Button>
      </Space>
      <Card
        title={system.name}
        extra={(
          <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void startNewRound()}>
            发起新一轮评估
          </Button>
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
      <InfraOverviewCard
        system={system}
        infra={infra}
        typeLabels={labelMapOf(enums, 'infra_asset_types')}
      />
    </div>
  )
}

/** 基础设施清单(#177): 聚合最新一轮评估(优先已生成)登记的资产, 只读展示系统现状。 */
function InfraOverviewCard({ system, infra, typeLabels }: {
  system: SystemRow
  infra: { roundId: number; rows: InfraAssetRow[] } | null
  typeLabels: Record<string, string>
}) {
  const round = pickInfraSourceRound(system)
  const rows = round && infra?.roundId === round.project_id ? infra.rows : null
  return (
    <Card
      title="基础设施清单"
      style={{ marginTop: 16 }}
      variant="borderless"
      extra={round && rows !== null && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          来自 {round.created_at?.slice(0, 10) || ''} 评估「{round.project_name}」
        </Typography.Text>
      )}
    >
      {!round ? (
        <Typography.Text type="secondary">
          还没有评估轮次, 发起新一轮评估并在「基础设施」步登记清单后, 这里将汇总展示系统现状。
        </Typography.Text>
      ) : rows === null ? (
        <Spin />
      ) : rows.length === 0 ? (
        <Typography.Text type="secondary">
          该轮评估未登记基础设施清单, 可在向导「基础设施」步补填。
        </Typography.Text>
      ) : (
        <Table<InfraAssetRow>
          rowKey={(r) => r.uid ?? String(r.id ?? `${r.name}@${r.env}`)}
          dataSource={rows}
          size="small"
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
          columns={[
            { title: '类型', dataIndex: 'asset_type', width: 110,
              render: (v) => <Tag color={v === 'network' ? 'geekblue' : 'default'}>{typeLabels[v] ?? v}</Tag> },
            { title: '名称', dataIndex: 'name' },
            { title: '环境', dataIndex: 'env', width: 80,
              render: (v) => ENV_LABELS[v] ?? v },
            { title: 'IP/地址', dataIndex: 'ip', width: 130, render: (v) => v || '—' },
            { title: '规格', render: (_v, r) => r.asset_type === 'server'
              ? [r.cpu_cores && `${r.cpu_cores}核`, r.memory_gb && `${r.memory_gb}G内存`, r.disk_gb && `${r.disk_gb}G盘`, r.os]
                .filter(Boolean).join(' / ') || '—'
              : (r.purpose || '—') },
            { title: '数量', dataIndex: 'quantity', width: 70, render: (v) => v ?? '—' },
            { title: '承载敏感数据', dataIndex: 'holds_sensitive', width: 110,
              render: (v: boolean) => (v ? <Tag color="red">是</Tag> : '否') },
          ]}
        />
      )}
    </Card>
  )
}
