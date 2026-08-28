/* 术语速查提示: 内联文字后跟 "?" 图标, 悬浮展示术语卡。
   解释性文案在前端维护(非业务枚举, 不违反 /api/meta/constants 唯一来源约束)。 */
import type { ReactNode } from 'react'
import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export const GLOSSARY: Record<string, { title: string; text: string }> = {
  sbom: {
    title: 'SBOM(软件物料清单)',
    text: '记录系统使用了哪些第三方组件及其版本的清单, 类似食品配料表。生成时按组件版本自动比对已知漏洞。',
  },
  cyclonedx: {
    title: 'CycloneDX / SPDX',
    text: '两种通用的 SBOM 文件格式, 可由 Maven/npm 等构建工具或安全工具导出。在第 7 步上传即可批量导入组件, 无需手工逐条录入。',
  },
  osv: {
    title: 'OSV.dev',
    text: 'Google 维护的公开漏洞数据库, 按「组件名 + 版本」查询已知漏洞(CVE)。查询失败时自动降级, 不阻塞生成流程。',
  },
  purl: {
    title: 'purl(包统一资源名)',
    text: '组件的标准坐标, 如 pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1。系统按 purl 精确匹配漏洞数据, 手工录入的组件会自动补齐。',
  },
  sod: {
    title: '职责分离(SoD)',
    text: '同一角色不应同时持有互斥权限(如既可创建单据又可审批单据), 否则存在「既当运动员又当裁判员」的舞弊风险。',
  },
  approval: {
    title: '免审批(高危操作无审批)',
    text: '删除/导出/审批/配置变更属于高危操作。关键资源上这些操作若未勾选「需审批」, 单人操作即可生效, 规则引擎会生成高优先级整改需求。',
  },
  asvs: {
    title: 'ASVS 4.0.3',
    text: 'OWASP 应用安全验证标准。本工具的安全需求编号按其章节分组(如 V12 对应文件上传), 便于对照国际基线自查。',
  },
  cve_cvss: {
    title: 'CVE / CVSS',
    text: 'CVE 是漏洞的唯一编号(如 CVE-2021-44228); CVSS 是漏洞严重程度评分(0~10 分, ≥9 为「严重」)。',
  },
  pii: {
    title: '敏感个人信息(PII)',
    text: '一旦泄露或被滥用容易导致人格尊严受损或人身财产安全受到危害的个人信息(金融账户、身份证、生物识别等), 合规要求比一般个人信息更严格。',
  },
  dryrun: {
    title: '试算预览(干跑)',
    text: '按当前已保存的输入完整跑一遍规则引擎, 预览将触发多少条安全需求, 不写入数据库、不生成文档。',
  },
  qps: {
    title: 'QPS',
    text: '每秒请求数, 限流配置的常用单位。「100 QPS/IP」表示单个 IP 每秒最多发起 100 次请求。',
  },
  grading: {
    title: '等保定级',
    text: '「网络安全等级保护」制度中的系统定级(一级/二级/三级), 级别越高安全要求越严。定级结果决定密码策略、加密策略的默认基线。',
  },
  anonymous_api: {
    title: '匿名接口',
    text: '无需登录即可调用的接口, 攻击面最大。规则引擎会为每个匿名接口生成专项安全评估需求。',
  },
}

export type GlossaryTerm = keyof typeof GLOSSARY

export default function GlossaryTip({ term, children }: { term: GlossaryTerm; children?: ReactNode }) {
  const g = GLOSSARY[term]
  if (!g) return <>{children}</>
  return (
    <span style={{ whiteSpace: 'normal' }}>
      {children}
      <Tooltip
        title={(
          <div>
            <b>{g.title}</b>
            <div style={{ marginTop: 4, fontWeight: 400 }}>{g.text}</div>
          </div>
        )}
      >
        <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999', cursor: 'help' }} />
      </Tooltip>
    </span>
  )
}
