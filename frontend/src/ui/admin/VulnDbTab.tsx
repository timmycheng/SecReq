/* 离线漏洞库(v2.2.0 内网上线的功能阻塞项): 库版本/生态覆盖/记录数/校验和/数据源状态。

   这一页的三个刻意设计:
   1. **明确交代覆盖缺口**(麒麟、K8s), 不让它以"已覆盖"的面貌出现;
   2. **区分"未导入"与"未纳入覆盖"** —— 前者补数据即可, 后者补再多数据也没用;
   3. 校验和比对走显式触发(大库重算需要几秒), 且留审计。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Space, Spin, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'

import { api } from '../../api'
import type { VulnDbStatus, VulnDbVerifyResult, VulnSourceRow } from '../../types'

const SOURCE_LABELS: Record<string, string> = {
  local: '本地漏洞库', online: 'OSV.dev 在线', sca: '行内 SCA 平台',
}

export default function VulnDbTab() {
  const [status, setStatus] = useState<VulnDbStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [verified, setVerified] = useState<VulnDbVerifyResult | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.getVulnDb()
      .then(setStatus)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  const verify = async () => {
    setVerifying(true)
    try {
      const res = await api.verifyVulnDb()
      setVerified(res)
      if (res.match === true) message.success('校验和一致, 漏洞库文件完整')
      else if (res.match === false) message.warning('校验和不一致, 请确认摆渡过程是否损坏并重新导入')
      else message.info('构建时未记录校验和, 无法核验完整性, 请核对文件来源')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setVerifying(false)
    }
  }

  if (loading && !status) return <Spin style={{ display: 'block', margin: '40px auto' }} />
  if (!status) return <Alert type="error" showIcon message="未能读取漏洞库状态" />

  const missing = status.missing_ecosystems ?? []
  const gaps = status.gaps ?? []

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        平台在内网部署、无互联网出口, 组件漏洞匹配完全依赖本页的<b>本地离线漏洞库</b>。
        库由 <code>scripts/build_vuln_db.py</code> 在联网区构建后摆渡进内网,
        替换挂载的 sqlite 文件即可更新, 无需重建镜像。
      </Typography.Paragraph>

      {!status.available && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 16 }}
          message="本地漏洞库不可用"
          description={
            <span>
              {status.reason}
              <br />
              未导入漏洞库时, 所有组件的漏洞查询都会标注为
              <b>「无法判定」</b>而非「未发现漏洞」—— 不给虚假的安全感。
            </span>
          }
        />
      )}

      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={reload}>刷新</Button>
        <Button
          icon={<SafetyCertificateOutlined />} loading={verifying}
          disabled={!status.available} onClick={() => void verify()}
        >
          校验文件完整性
        </Button>
      </Space>

      {status.available && (
        <Card size="small" title="库概况" style={{ marginBottom: 16 }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="库版本">{status.db_version ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="构建时间">{status.built_at ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="记录数">
              {status.total?.toLocaleString() ?? '—'} 条(按生态/包名展开的坐标行)
            </Descriptions.Item>
            <Descriptions.Item label="体积">
              {status.size_mb != null ? `${status.size_mb} MB` : '—'}
              {status.compressed && <Tag style={{ marginLeft: 8 }}>zlib 压缩</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="文件路径" span={2}>
              <code style={{ fontSize: 12 }}>{status.path}</code>
            </Descriptions.Item>
            <Descriptions.Item label="SHA256" span={2}>
              <code style={{ fontSize: 12 }}>{status.sha256 ?? '构建时未记录'}</code>
            </Descriptions.Item>
            <Descriptions.Item label="CNNVD 映射">
              {status.cnnvd?.available
                ? <Tag color="green">{status.cnnvd.total.toLocaleString()} 条(v{status.cnnvd.db_version})</Tag>
                : <Tag color="orange">未导入(不影响漏洞匹配, 仅少补合规编号)</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="上游数据源">{status.upstream ?? '—'}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {verified && (
        <Alert
          style={{ marginBottom: 16 }}
          type={verified.match === false ? 'error' : verified.match === true ? 'success' : 'info'}
          showIcon
          message={verified.match === true
            ? '校验和一致, 文件完整'
            : verified.match === false
              ? '校验和不一致, 文件可能已损坏'
              : '无校验和可比对(构建时未记录校验和)'}
          description={<code style={{ fontSize: 12 }}>{verified.sha256}</code>}
        />
      )}

      <Card size="small" title="数据源" style={{ marginBottom: 16 }}>
        <Table<VulnSourceRow>
          rowKey="code" dataSource={status.sources ?? []} pagination={false} size="small"
          columns={[
            { title: '数据源', dataIndex: 'code', width: 160,
              render: (v: string) => (
                <Space>
                  {SOURCE_LABELS[v] ?? v}
                  {status.sources?.find((s) => s.code === v)?.active && <Tag color="blue">当前生效</Tag>}
                </Space>
              ) },
            { title: '状态', dataIndex: 'available', width: 100,
              render: (v: boolean) => (v ? <Tag color="green">可用</Tag> : <Tag color="orange">不可用</Tag>) },
            { title: '说明', dataIndex: 'reason', render: (v) => v || '—' },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
          数据源按 <code>SECREQ_VULN_SOURCE</code> 配置链式选取(如 <code>sca,local</code>),
          前一个不可用时自动降级到下一个并记日志, 不静默失败。
        </Typography.Paragraph>
      </Card>

      <Card size="small" title="生态覆盖" style={{ marginBottom: 16 }}>
        <Table
          rowKey="code" pagination={false} size="small"
          dataSource={status.declared_ecosystems ?? []}
          columns={[
            { title: '生态', dataIndex: 'label', width: 220 },
            { title: '记录数', dataIndex: 'records', width: 120,
              render: (v: number | null) => (v == null ? '—' : v.toLocaleString()) },
            { title: '状态', dataIndex: 'code', width: 120,
              render: (code: string) => ((status.covered_ecosystems ?? []).includes(code)
                ? <Tag color="green">覆盖中</Tag> : <Tag color="orange">无数据</Tag>) },
          ]}
        />
        {missing.length > 0 && (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
            未导入: {missing.map((m) => m.label).join('、')}
            (可在联网区重跑构建脚本追加生态后重新摆渡)
          </Typography.Paragraph>
        )}
        {(status.incidental_ecosystems ?? []).length > 0 && (
          <Alert
            style={{ marginTop: 8 }} type="info" showIcon
            message="库内存在非声明生态的记录, 不计入覆盖"
            description={
              <span>
                OSV 的多生态公告会在一个生态的数据包里夹带其他生态的包坐标
                (实测 Maven 数据包带 92 条 npm 记录)。
                {status.incidental_ecosystems?.join('、')} 虽有记录, 但本次构建未声明导入,
                <b>不视为已覆盖</b> —— 否则等于用几十条记录冒充整个生态。
              </span>
            }
          />
        )}
      </Card>

      {gaps.length > 0 && (
        <Card size="small" title="已知覆盖缺口" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {gaps.map((gap) => (
              <Alert
                key={gap.code} type="warning" showIcon
                message={<span><b>{gap.label}</b>: {gap.note}</span>}
                description={gap.detail}
              />
            ))}
          </Space>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
            缺口组件在结果中一律标注为「未纳入本地漏洞库覆盖范围」,
            不会显示成"未发现漏洞"。<Tooltip title="麒麟不在 OSV 的 39 个生态中, openEuler 只能做同源代理匹配">
              <Typography.Link>为什么麒麟无法等价替代?</Typography.Link>
            </Tooltip>
          </Typography.Paragraph>
        </Card>
      )}
    </>
  )
}
