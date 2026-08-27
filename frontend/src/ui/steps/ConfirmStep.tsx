/* 确认页: 汇总全部输入 → 规则引擎干跑预览触发规模 → 生成安全基线。 */
import { useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Space, Spin, Switch, Tag, Typography, message,
} from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, useEnums } from '../../enums'
import { navigate } from '../../router'
import type { PreviewResult } from '../../types'
import type { StepProps } from '../WizardPage'

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}

export default function ConfirmStep({ ws }: StepProps) {
  const enums = useEnums()
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [skipOsv, setSkipOsv] = useState(false)

  const priorityLabels = labelMapOf(enums, 'priority_labels')

  const doPreview = async () => {
    setPreviewing(true)
    try {
      setPreview(await api.previewRequirements(ws.project.id))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setPreviewing(false)
    }
  }

  const doGenerate = async () => {
    setGenerating(true)
    try {
      const summary = await api.generate(ws.project.id, skipOsv)
      message.success(
        `已生成 ${summary.requirements_total} 条安全需求${summary.vulnerabilities_total
          ? `, 命中 ${summary.vulnerabilities_total} 条漏洞(其中严重 ${summary.critical_vulnerabilities} 条)`
          : ''}`,
        5,
      )
      navigate(`/result/${ws.project.id}`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div style={{ maxWidth: 900 }}>
      <Typography.Title level={4}>确认输入</Typography.Title>
      <Descriptions
        bordered
        size="small"
        column={2}
        items={[
          { key: 'name', label: '项目', children: `${ws.project.name}(${ws.project.code})` },
          {
            key: 'grading',
            label: '定级结论',
            children: ws.survey?.effective_level
              ? <Tag color="blue">等保{ws.survey.effective_level}{ws.survey.final_level ? '(人工修正)' : '(系统建议)'}</Tag>
              : <Tag>未完成问卷</Tag>,
          },
          { key: 'features', label: '功能清单', children: `${ws.features.length} 个功能` },
          {
            key: 'assets',
            label: '数据字典',
            children: `${ws.data_assets.length} 个资产 / ${ws.data_assets.reduce((n, a) => n + a.tables.length, 0)} 张表`,
          },
          {
            key: 'matrix',
            label: '权限矩阵',
            children: `${ws.roles.length} 角色 × ${ws.resources.length} 资源, ${ws.permission_entries.length} 条授权`,
          },
          {
            key: 'auth',
            label: '认证方式',
            children: ws.auth_config?.auth_methods.map((m) => labelMapOf(enums, 'auth_methods')[m] ?? m).join('、') || '—',
          },
          { key: 'sbom', label: '软件/框架清单', children: `${ws.components.length} 个组件` },
          { key: 'apis', label: '接口/资产清单', children: `${ws.api_endpoints.length} 接口 · ${ws.infra_assets.length} 基础设施资产` },
          {
            key: 'deploy',
            label: '部署环境',
            children: (ws.project.deploy_env ?? []).map((d) => labelMapOf(enums, 'deploy_envs')[d] ?? d).join('、') || '—',
          },
          {
            key: 'compliance',
            label: '合规目标',
            children: (ws.project.compliance_targets ?? []).map((c) => labelMapOf(enums, 'compliance_targets')[c] ?? c).join('、') || '—',
          },
        ]}
      />

      <Card size="small" style={{ marginTop: 16 }} title="需求触发预览(干跑, 不写入数据库)">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button icon={<PlayCircleOutlined />} loading={previewing} onClick={doPreview}>
            预览触发的安全需求
          </Button>
          {preview && (
            <>
              <Alert
                type={preview.total > 0 ? 'success' : 'warning'}
                message={`已触发 ${preview.total} 条安全需求`}
                description={(
                  <Space size={[6, 6]} wrap style={{ marginTop: 4 }}>
                    {preview.by_category.map((c) => (
                      <Tag key={c.code} color="blue">{c.label} × {c.count}</Tag>
                    ))}
                    <span>| </span>
                    {Object.entries(preview.by_priority).map(([p, n]) => n > 0 && (
                      <Tag key={p} color={PRIORITY_COLOR[p]}>{priorityLabels[p] ?? p} × {n}</Tag>
                    ))}
                  </Space>
                )}
              />
              {preview.top_items.length > 0 && (
                <div style={{ padding: '8px 12px', background: '#fafafa', borderRadius: 6 }}>
                  <Typography.Text type="secondary">高优先级摘要:</Typography.Text>
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                    {preview.top_items.slice(0, 5).map((t) => <li key={t}><Typography.Text>{t}</Typography.Text></li>)}
                  </ul>
                </div>
              )}
            </>
          )}
        </Space>
      </Card>

      <Space align="center" style={{ marginTop: 20 }}>
        <Switch checked={!skipOsv} onChange={(v) => setSkipOsv(!v)} />
        <span>在线查询 OSV.dev 漏洞库</span>
        <Typography.Text type="secondary">(关闭则跳过网络查询, 使用库内缓存; 失败自动降级不阻塞流程)</Typography.Text>
      </Space>

      <div style={{ marginTop: 16 }}>
        {generating
          ? <Spin tip="正在执行规则引擎与文档生成…"><div style={{ height: 60 }} /></Spin>
          : (
            <Button type="primary" size="large" onClick={doGenerate}>
              ⚡ 生成安全基线(需求 + SBOM + 4 份 Word 文档)
            </Button>
          )}
      </div>
    </div>
  )
}
