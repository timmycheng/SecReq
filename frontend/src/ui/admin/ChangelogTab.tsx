/* 更新日志(#55): 后端解析 CHANGELOG.md 为结构化版本块, 本组件零依赖渲染
   (行内 **加粗** 与 `代码`), 版本折叠展示, 新版本在前。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Collapse, Spin, Tag, Typography, message } from 'antd'

import { api } from '../../api'

interface ChangelogBlock {
  kind: 'h3' | 'para' | 'list_item' | 'quote' | 'table_row'
  text?: string
  cells?: string[]
}

interface ChangelogVersion {
  version: string
  date: string
  blocks: ChangelogBlock[]
}

/** 行内渲染: **加粗** 与 `代码`, 其余原样。受控格式, 不引入 markdown 库。 */
function InlineText({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean), [text])
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <b key={i}>{part.slice(2, -2)}</b>
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return <code key={i} style={{ fontSize: 12 }}>{part.slice(1, -1)}</code>
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

function Blocks({ blocks }: { blocks: ChangelogBlock[] }) {
  const listItems = (items: ChangelogBlock[], start: number) => (
    <ul key={`ul-${start}`} style={{ margin: '4px 0', paddingLeft: 20 }}>
      {items.map((b, i) => (
        <li key={start + i} style={{ margin: '4px 0' }}><InlineText text={b.text ?? ''} /></li>
      ))}
    </ul>
  )
  const nodes: React.ReactNode[] = []
  let run: ChangelogBlock[] = []
  let runStart = 0
  blocks.forEach((b, i) => {
    if (b.kind === 'list_item') {
      if (!run.length) runStart = i
      run.push(b)
      return
    }
    if (run.length) { nodes.push(listItems(run, runStart)); run = [] }
    if (b.kind === 'h3') {
      nodes.push(<Typography.Title key={i} level={5} style={{ marginTop: 12 }}><InlineText text={b.text ?? ''} /></Typography.Title>)
    } else if (b.kind === 'quote') {
      nodes.push(
        <blockquote key={i} style={{ borderLeft: '3px solid #d9d9d9', margin: '8px 0', padding: '2px 10px', color: '#666' }}>
          <InlineText text={b.text ?? ''} />
        </blockquote>,
      )
    } else if (b.kind === 'table_row') {
      nodes.push(
        <div key={i} style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap' }}>
          {(b.cells ?? []).join(' | ')}
        </div>,
      )
    } else {
      nodes.push(<Typography.Paragraph key={i} style={{ marginBottom: 8 }}><InlineText text={b.text ?? ''} /></Typography.Paragraph>)
    }
  })
  if (run.length) nodes.push(listItems(run, runStart))
  return <>{nodes}</>
}

export default function ChangelogTab() {
  const [versions, setVersions] = useState<ChangelogVersion[] | null>(null)

  const reload = useCallback(() => {
    api.getChangelog()
      .then(setVersions)
      .catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  if (versions === null) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!versions.length) {
    return <Alert type="warning" showIcon message="未找到更新日志(CHANGELOG.md 缺失), 请核对部署包完整性" />
  }
  const latest = versions[0]
  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        平台各版本变更记录(与仓库 CHANGELOG 同源), 当前展示 {versions.length} 个版本。
      </Typography.Paragraph>
      <Collapse
        defaultActiveKey={[latest.version]}
        items={versions.map((v) => ({
          key: v.version,
          label: (
            <span>
              <Tag color="blue">v{v.version}</Tag>
              <span style={{ marginRight: 8 }}>{v.date}</span>
              {v.version === latest.version && <Tag color="green">当前</Tag>}
            </span>
          ),
          children: <Blocks blocks={v.blocks} />,
        }))}
      />
    </>
  )
}
