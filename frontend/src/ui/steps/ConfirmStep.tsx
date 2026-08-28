/* 确认页: 汇总全部输入(附各步「去修改」链接) → 完整性检查 →
   规则引擎试算预览触发规模 → 生成安全基线。生成读取的是各步"已保存"的数据。 */
import { useState } from 'react'
import {
  Alert, App, Button, Card, Descriptions, Space, Spin, Switch, Tag, Typography,
} from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { labelMapOf, useEnums } from '../../enums'
import { navigate } from '../../router'
import type { PreviewResult } from '../../types'
import GlossaryTip from '../GlossaryTip'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'gold', low: 'default',
}

export default function ConfirmStep({ ws, goto }: StepProps) {
  const { message } = App.useApp()
  const enums = useEnums()
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [osvOnline, setOsvOnline] = useState(true)

  const priorityLabels = labelMapOf(enums, 'priority_labels')

  // 确认页自身无输入, 永远视为"已保存"
  useRegisterStepHandle({ save: async () => true, isDirty: () => false })

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
      const summary = await api.generate(ws.project.id, !osvOnline)
      message.success(
        `已生成 ${summary.requirements_total} 条安全需求${summary.vulnerabilities_total
          ? `, 命中 ${summary.vulnerabilities_total} 条漏洞(其中严重 ${summary.critical_vulnerabilities} 条)`
          : ''}`,
        5,
      )
      navigate(`/result/${ws.project.id}`)
    } catch (e) {
      message.error((e as Error).message)
      setGenerating(false)
    }
  }

  /** 每个汇总项: 内容 + (为空时的)提醒与跳转链接。 */
  const withFix = (step: number, text: string, empty: boolean) => (
    <Space size={8} wrap>
      <span style={{ color: empty ? '#cf1322' : undefined }}>{text}</span>
      {empty
        ? <a onClick={() => goto(step)} style={{ color: '#cf1322' }}>去补录</a>
        : <a onClick={() => goto(step)}>去修改</a>}
    </Space>
  )

  const gaps: string[] = []
  if (!ws.survey?.effective_level) gaps.push('等保定级问卷未完成')
  if (!ws.features.length) gaps.push('功能清单为空')
  if (!ws.data_assets.length) gaps.push('数据字典为空')
  if (!ws.roles.length || !ws.resources.length) gaps.push('权限矩阵未维护')
  if (!ws.components.length) gaps.push('软件/框架清单为空(将跳过漏洞扫描)')

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <Typography.Title level={4}>确认输入</Typography.Title>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        以下汇总的是<b>各步骤已保存</b>的数据; 生成前可从任意一行「去修改」跳回对应步骤。
      </Typography.Text>

      {gaps.length > 0 && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          message={`以下内容尚未完成(不影响生成, 但对应维度的需求会缺失): ${gaps.join('; ')}`}
        />
      )}

      <Descriptions
        bordered
        size="small"
        column={2}
        items={[
          { key: 'name', label: '项目', children: `${ws.project.name}(${ws.project.code})` },
          {
            key: 'grading',
            label: <GlossaryTip term="grading">定级结论</GlossaryTip>,
            children: ws.survey?.effective_level
              ? <Tag color="blue">等保{ws.survey.effective_level}{ws.survey.final_level ? '(人工修正)' : '(系统建议)'}</Tag>
              : withFix(1, '未完成问卷', true),
          },
          { key: 'features', label: '功能清单', children: withFix(2, `${ws.features.length} 个功能`, !ws.features.length) },
          {
            key: 'assets',
            label: '数据字典',
            children: withFix(3, `${ws.data_assets.length} 个资产 / ${ws.data_assets.reduce((n, a) => n + a.tables.length, 0)} 张表`, !ws.data_assets.length),
          },
          {
            key: 'matrix',
            label: <GlossaryTip term="sod">权限矩阵</GlossaryTip>,
            children: withFix(4, `${ws.roles.length} 角色 × ${ws.resources.length} 资源, ${ws.permission_entries.length} 条授权`, !ws.roles.length || !ws.resources.length),
          },
          {
            key: 'auth',
            label: '认证方式',
            children: withFix(5, ws.auth_config?.auth_methods.map((m) => labelMapOf(enums, 'auth_methods')[m] ?? m).join('、') || '未设置', !ws.auth_config),
          },
          { key: 'sbom', label: <GlossaryTip term="sbom">软件/框架清单</GlossaryTip>, children: withFix(6, `${ws.components.length} 个组件`, !ws.components.length) },
          { key: 'apis', label: '接口/资产清单', children: withFix(7, `${ws.api_endpoints.length} 接口 · ${ws.infra_assets.length} 基础设施资产`, false) },
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

      <Card size="small" style={{ marginTop: 16 }} title={<GlossaryTip term="dryrun">需求触发试算预览(不写入数据库)</GlossaryTip>}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button icon={<PlayCircleOutlined />} loading={previewing} onClick={doPreview}>
            按当前数据试算
          </Button>
          {preview && (
            <>
              <Alert
                type={preview.total > 0 ? 'success' : 'warning'}
                message={`将触发 ${preview.total} 条安全需求`}
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
        <Switch checked={osvOnline} onChange={setOsvOnline} />
        <span><GlossaryTip term="osv">在线查询 OSV.dev 漏洞库</GlossaryTip></span>
        <Typography.Text type="secondary">(关闭则跳过联网查询, 使用库内已有漏洞数据; 查询失败会自动降级, 不阻塞生成)</Typography.Text>
      </Space>

      <div style={{ marginTop: 16 }}>
        {generating
          ? <Spin tip="正在执行规则引擎与文档生成…"><div style={{ height: 60 }} /></Spin>
          : (
            <Button type="primary" size="large" onClick={doGenerate}>
              生成安全基线(需求 + SBOM + 4 份 Word 文档)
            </Button>
          )}
      </div>
    </div>
  )
}
