/* 拓扑画布一期(#93): @xyflow/react 实现 区域分组框 + 四类设备节点 + 带说明连线。
   设备/区域/连线状态由父组件持有(与下方清单双向联动); 位置存 layout, 不进规则引擎。 */
import { useCallback, useMemo } from 'react'
import {
  Background, Controls, Handle, Position, ReactFlow,
  applyEdgeChanges, applyNodeChanges,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { CloudServerOutlined, DatabaseOutlined, GlobalOutlined, HddOutlined } from '@ant-design/icons'

export interface TopoZone { uid: string; name: string }
export interface TopoLink { source_uid: string; target_uid: string; label: string | null }
export interface TopoLayout { nodes: Record<string, { x: number; y: number }>; zones: Record<string, { x: number; y: number }> }

export interface TopoAsset {
  uid: string
  asset_type: string
  name: string
  env: string
  zone_uid?: string | null
  ip?: string | null
  holds_sensitive?: boolean
  [key: string]: unknown
}

export const DEVICE_TYPES: { value: string; label: string }[] = [
  { value: 'server', label: '服务器' },
  { value: 'database', label: '数据库' },
  { value: 'middleware', label: '中间件' },
  { value: 'network', label: '网络设备' },
]

const TYPE_ICON: Record<string, React.ReactNode> = {
  server: <CloudServerOutlined />,
  database: <DatabaseOutlined />,
  middleware: <HddOutlined />,
  network: <GlobalOutlined />,
}

/** 设备节点: 图标 + 名称; 上下留连线锚点。 */
function DeviceNode({ data }: { data: { label: string; assetType: string } }) {
  return (
    <div style={{
      width: 130, padding: 8, borderRadius: 8, background: '#fff',
      border: '1px solid #91caff', textAlign: 'center', fontSize: 12,
    }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div style={{ fontSize: 16, color: '#1677ff' }}>{TYPE_ICON[data.assetType] ?? <CloudServerOutlined />}</div>
      <div style={{ marginTop: 2, wordBreak: 'break-all' }}>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

/** 区域节点: 半透明分组框, 双击改名(由父组件处理)。 */
function ZoneNode({ data }: { data: { label: string } }) {
  return (
    <div style={{
      width: 320, height: 200, borderRadius: 10, border: '2px dashed #b7eb8f',
      background: 'rgba(250,255,240,0.6)', padding: 8, fontSize: 13, color: '#389e0d',
    }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <b>▭ {data.label}</b>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { device: DeviceNode, zone: ZoneNode }

export default function InfraTopologyCanvas({ assets, zones, links, positions, onChange }: {
  assets: TopoAsset[]
  zones: TopoZone[]
  links: TopoLink[]
  positions: { nodes: Record<string, { x: number; y: number }>; zones: Record<string, { x: number; y: number }> }
  onChange: (next: { assets?: TopoAsset[]; zones?: TopoZone[]; links?: TopoLink[]; positions?: typeof positions }) => void
}) {
  const nodes = useMemo(() => [
    ...zones.map((z) => ({
      id: z.uid, type: 'zone' as const,
      position: positions.zones[z.uid] ?? { x: 40, y: 40 },
      data: { label: z.name }, zIndex: -1, draggable: true,
    })),
    ...assets.map((a) => ({
      id: a.uid, type: 'device' as const,
      position: positions.nodes[a.uid] ?? { x: 220, y: 60 },
      data: { label: a.name, assetType: a.asset_type },
    })),
  ], [assets, zones, positions])

  const edges = useMemo(() => links.map((l) => ({
    id: `e-${l.source_uid}-${l.target_uid}`,
    source: l.source_uid, target: l.target_uid,
    label: l.label || undefined,
  })), [links])

  const onNodesChange = useCallback((changes: any[]) => {
    // 删除节点 → 同步删除设备/区域与相关连线; 位置拖动 → 写回 positions(#93)
    const removed = changes.filter((c) => c.type === 'remove')
    if (removed.length) {
      const removedIds = removed.map((c) => c.id as string)
      const removedAssets = removedIds.filter((id) => assets.some((a) => a.uid === id))
      const removedZones = removedIds.filter((id) => zones.some((z) => z.uid === id))
      if (removedAssets.length) {
        onChange({ assets: assets.filter((a) => !removedAssets.includes(a.uid)) })
      }
      if (removedZones.length) {
        onChange({ zones: zones.filter((z) => !removedZones.includes(z.uid)) })
      }
    }
    const posChanges = changes.filter((c) => c.type === 'position' && c.position) as { id: string; position: { x: number; y: number } }[]
    if (posChanges.length) {
      const next = { nodes: { ...positions.nodes }, zones: { ...positions.zones } }
      for (const c of posChanges) {
        if (assets.some((a) => a.uid === c.id)) next.nodes[c.id] = c.position
        else if (zones.some((z) => z.uid === c.id)) next.zones[c.id] = c.position
      }
      onChange({ positions: next })
    }
  }, [assets, zones, positions, onChange])

  const onEdgesChange = useCallback((changes: any[]) => {
    const removed = changes.filter((c: { type: string }) => c.type === 'remove')
    if (removed.length) {
      const removedIds = new Set(removed.map((c: { id: string }) => c.id))
      onChange({ links: links.filter((l) => !removedIds.has(`e-${l.source_uid}-${l.target_uid}`)) })
    }
  }, [links, onChange])

  const onConnect = useCallback((params: { source: string; target: string }) => {
    if (params.source === params.target) return
    if (links.some((l) => l.source_uid === params.source && l.target_uid === params.target)) return
    const label = window.prompt('连线说明(如 HTTPS 8443), 可留空') ?? ''
    onChange({ links: [...links, { source_uid: params.source, target_uid: params.target, label }] })
  }, [links, onChange])

  const onEdgeDoubleClick = useCallback((_: unknown, edge: { id: string }) => {
    const link = links.find((l) => `e-${l.source_uid}-${l.target_uid}` === edge.id)
    if (!link) return
    const label = window.prompt('连线说明(如 HTTPS 8443)', link.label ?? '')
    if (label === null) return
    onChange({ links: links.map((l) => (`e-${l.source_uid}-${l.target_uid}` === edge.id ? { ...l, label } : l)) })
  }, [links, onChange])

  const onNodeDoubleClick = useCallback((_: unknown, node: { id: string }) => {
    const zone = zones.find((z) => z.uid === node.id)
    if (!zone) return
    const name = window.prompt('区域名称', zone.name)
    if (name === null || !name.trim()) return
    onChange({ zones: zones.map((z) => (z.uid === zone.uid ? { ...z, name: name.trim() } : z)) })
  }, [zones, onChange])

  return (
    <div style={{ height: 380, border: '1px solid #f0f0f0', borderRadius: 8 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgeDoubleClick={onEdgeDoubleClick}
        onNodeDoubleClick={onNodeDoubleClick}
        fitView
      >
        <Background gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export { applyEdgeChanges, applyNodeChanges }
