/* 复制到 Word: 前端把产物渲染为带内联样式的 HTML 写入剪贴板,
   粘贴到 Word/WPS 即保留标题层级、表格与标红等格式(走查整改: 不再生成 .docx 文件)。 */

export function escapeHtml(text: string | null | undefined): string {
  return String(text ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

/** 写入剪贴板 text/html(+text/plain 兜底); 需在用户点击回调内调用。 */
export async function copyRichHtml(html: string, plainText: string): Promise<void> {
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
    await navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([plainText], { type: 'text/plain' }),
    })])
    return
  }
  // 兜底: 隐藏选区 + execCommand
  const div = document.createElement('div')
  div.innerHTML = html
  div.style.position = 'fixed'
  div.style.left = '-9999px'
  document.body.appendChild(div)
  const range = document.createRange()
  range.selectNodeContents(div)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
  document.execCommand('copy')
  selection?.removeAllRanges()
  div.remove()
}

const H1 = 'style="font-size:20pt;font-weight:bold;font-family:\'黑体\',SimHei;text-align:center;margin:0 0 6pt"'
const H2 = 'style="font-size:14pt;font-weight:bold;font-family:\'黑体\',SimHei;margin:18pt 0 8pt;border-bottom:1px solid #999"'
const META_TABLE = 'style="border-collapse:collapse;width:100%;font-family:\'宋体\',SimSun;font-size:11pt"'
const TD = 'style="border:1px solid #666;padding:4pt 6pt;vertical-align:top"'
const TD_HEAD = 'style="border:1px solid #666;padding:4pt 6pt;background:#eee;font-weight:bold;width:18%"'
const REQ_TABLE = 'style="border-collapse:collapse;width:100%;font-family:\'宋体\',SimSun;font-size:10.5pt"'
/** td 属性: 在基础单元格样式上追加内联样式。 */
function td(extraStyle = ''): string {
  return `style="border:1px solid #666;padding:4pt 6pt;vertical-align:top;${extraStyle}"`
}

export interface RequirementLike {
  req_id: string
  title: string
  description: string
  category: string
  priority: string
  acceptance_criteria: string
  trigger_reason: string
  source_label?: string | null
  reg_confirmed?: boolean
  regulatory_ref?: { file: string; clause?: string }[] | null
}

export interface VulnLike {
  cve_id: string
  severity: string
  component_name: string
  component_version: string
  affected_range: string | null
  fix_version: string | null
  summary: string | null
}

const SEVERITY_TEXT: Record<string, string> = {
  critical: '严重', high: '高危', medium: '中危', low: '低危',
}

/** 文档外壳: 标题 + 概况表 + 章节。 */
export function docShell(title: string, metaRows: [string, string][], sections: string): string {
  const meta = metaRows.length
    ? `<table ${META_TABLE}>${metaRows.map(([k, v]) => `<tr><td ${TD_HEAD}>${escapeHtml(k)}</td><td ${TD}>${v}</td></tr>`).join('')}</table><br/>`
    : ''
  return `<html><head><meta charset="utf-8"></head><body style="font-family:'宋体',SimSun"><h1 ${H1}>${escapeHtml(title)}</h1>${meta}${sections}</body></html>`
}

export function sectionHeading(text: string): string {
  return `<h2 ${H2}>${escapeHtml(text)}</h2>`
}

export function para(text: string): string {
  return `<p style="margin:4pt 0;font-size:11pt">${text}</p>`
}

/** 安全需求清单章节: 平铺全文(描述不截断), 分组置顶监管报送。 */
export function requirementsSection(reqs: RequirementLike[], priorityLabels: Record<string, string>): string {
  const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
  const sorted = [...reqs].sort((a, b) =>
    (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9) || a.req_id.localeCompare(b.req_id))
  const rows = sorted.map((r, i) => {
    const refs = (r.regulatory_ref ?? []).map((ref) => `《${escapeHtml(ref.file)}》${escapeHtml(ref.clause ?? '')}`)
      .filter(Boolean).join('<br/>') || '—'
    const confirmed = r.reg_confirmed ? '✓ 已确认' : '□ 未确认'
    const priorityStyle = r.priority === 'critical' ? 'color:#c00000;font-weight:bold' : ''
    return `<tr>
      <td ${td('text-align:center')}>${i + 1}</td>
      <td ${td()}><b>[${escapeHtml(r.req_id)}]</b> ${escapeHtml(r.title)}<br/>
        <span style="color:#333">${escapeHtml(r.description)}</span></td>
      <td ${td(priorityStyle)}>${escapeHtml(priorityLabels[r.priority] ?? r.priority)}</td>
      <td ${td('font-size:9.5pt')}>${escapeHtml(r.category)}<br/><span style="color:#666;font-size:9pt">${escapeHtml(r.source_label ?? '')}</span></td>
      <td ${td('font-size:9.5pt')}>${escapeHtml(r.acceptance_criteria)}</td>
      <td ${td('font-size:9.5pt')}>${refs}<br/><span style="color:#666;font-size:9pt">${confirmed}</span></td>
    </tr>`
  })
  return `<table ${REQ_TABLE}>
    <tr>
      <th ${td('background:#eee;font-weight:bold;text-align:center;width:5%')}>序号</th>
      <th ${td('background:#eee;font-weight:bold;width:38%')}>需求内容</th>
      <th ${td('background:#eee;font-weight:bold;width:7%')}>优先级</th>
      <th ${td('background:#eee;font-weight:bold;width:13%')}>类目/来源</th>
      <th ${td('background:#eee;font-weight:bold;width:20%')}>验收标准</th>
      <th ${td('background:#eee;font-weight:bold;width:17%')}>合规依据/确认</th>
    </tr>
    ${rows.join('')}
  </table>`
}

/** 漏洞清单章节(高危标红)。 */
export function vulnsSection(vulns: VulnLike[]): string {
  if (!vulns.length) return para('未发现漏洞记录。')
  const rows = vulns.map((v) => {
    const sev = SEVERITY_TEXT[v.severity] ?? v.severity
    const sevStyle = v.severity === 'critical' || v.severity === 'high'
      ? 'color:#c00000;font-weight:bold' : ''
    return `<tr><td ${td(sevStyle)}>${escapeHtml(sev)}</td>
      <td ${td(sevStyle)}>${escapeHtml(v.cve_id)}</td>
      <td ${td()}>${escapeHtml(v.component_name)}@${escapeHtml(v.component_version)}</td>
      <td ${td()}>${escapeHtml(v.affected_range ?? '—')}</td>
      <td ${td()}>${escapeHtml(v.fix_version ?? '官方暂未发布修复版')}</td>
      <td ${td()}>${escapeHtml(v.summary ?? '')}</td></tr>`
  })
  return `<table ${REQ_TABLE}>
    <tr>
      <th ${td('background:#eee;font-weight:bold;width:8%')}>等级</th>
      <th ${td('background:#eee;font-weight:bold;width:16%')}>CVE</th>
      <th ${td('background:#eee;font-weight:bold;width:22%')}>组件</th>
      <th ${td('background:#eee;font-weight:bold;width:18%')}>受影响范围</th>
      <th ${td('background:#eee;font-weight:bold;width:14%')}>修复版本</th>
      <th ${td('background:#eee;font-weight:bold')}>简述</th>
    </tr>
    ${rows.join('')}
  </table>`
}

/** 概况信息(定级/策略/合规)章节。 */
export function infoSection(rows: [string, string][]): string {
  return `<table ${META_TABLE}>${rows.map(([k, v]) =>
    `<tr><td ${TD_HEAD}>${escapeHtml(k)}</td><td ${TD}>${v}</td></tr>`).join('')}</table>`
}

/** 合规目标 → 需求监管出处文件名关键词(与 shared/constants.py 的口径一致)。 */
const COMPLIANCE_KEYWORDS: Record<string, string> = {
  djcp_l3: '等级保护', pipl: '个人信息', pci_dss: 'PCI',
}

export interface SummaryInput {
  projectName: string
  requirements: RequirementLike[]
  vulns: VulnLike[]
  complianceTargets: string[]
  complianceLabels: Record<string, string>
}

/** 执行摘要章节(#162): 结论 + 关键数字 + Top 风险 + 合规覆盖, 与结果页/Word 导出同口径。 */
export function executiveSummarySection(input: SummaryInput): string {
  const { projectName, requirements, vulns } = input
  const crit = requirements.filter((r) => r.priority === 'critical').length
  const high = requirements.filter((r) => r.priority === 'high').length
  const critV = vulns.filter((v) => v.severity === 'critical').length
  const highV = vulns.filter((v) => v.severity === 'high').length
  const confirmed = requirements.filter((r) => r.reg_confirmed).length

  let text: string; let detail: string; let color: string
  if (crit || critV) {
    text = `不建议直接通过: 存在 ${crit} 条关键需求与 ${critV} 个严重漏洞`
    detail = '关键项为硬性安全要求, 建议整改闭环后复评; 优先处理下表 Top 风险。'
    color = '#c00000'
  } else if (high || highV) {
    text = `有条件通过: 无关键(critical)项, 有 ${high} 条高优先级需求与 ${highV} 个高危漏洞`
    detail = '建议按 Top 风险排期整改, 其余需求按建议阶段落实。'
    color = '#d46900'
  } else {
    text = `基线整体可控: 共 ${requirements.length} 条需求, 均非 critical/high`
    detail = '按建议阶段落实即可, 无需额外整改决策。'
    color = '#1e7d32'
  }

  const top = requirements
    .filter((r) => r.priority === 'critical' || r.priority === 'high')
    .sort((a, b) => (a.priority === 'critical' ? -1 : 1) - (b.priority === 'critical' ? -1 : 1))
    .slice(0, 5)
  const topRows = top.map((r) => `<tr>
      <td ${td(r.priority === 'critical' ? 'color:#c00000;font-weight:bold' : '')}>${escapeHtml(r.req_id)}</td>
      <td ${td()}>${escapeHtml(r.title)}</td>
      <td ${td(r.priority === 'critical' ? 'color:#c00000' : '')}>${escapeHtml(r.priority === 'critical' ? '紧急' : '高')}</td>
      <td ${td('font-size:9.5pt')}>${escapeHtml(r.source_label ?? '—')}</td>
    </tr>`).join('')

  const coverage = input.complianceTargets.map((code) => {
    const keyword = COMPLIANCE_KEYWORDS[code]
    const label = input.complianceLabels[code] ?? code
    const count = keyword
      ? requirements.filter((r) => (r.regulatory_ref ?? []).some((f) => (f.file ?? '').includes(keyword))).length
      : 0
    return `${escapeHtml(label)}: ${count || '未直接命中'}`
  }).join(';')

  return `${sectionHeading(`${projectName} 执行摘要`)}
  <p style="margin:6pt 0;font-size:12pt;font-weight:bold;color:${color}">${escapeHtml(text)}</p>
  ${para(escapeHtml(detail))}
  <table ${REQ_TABLE}>
    <tr>
      <th ${td('background:#eee;font-weight:bold')}>安全需求</th>
      <th ${td('background:#eee;font-weight:bold')}>紧急(critical)</th>
      <th ${td('background:#eee;font-weight:bold')}>高(high)</th>
      <th ${td('background:#eee;font-weight:bold')}>已确认</th>
      <th ${td('background:#eee;font-weight:bold')}>严重漏洞</th>
      <th ${td('background:#eee;font-weight:bold')}>高危漏洞</th>
    </tr>
    <tr><td ${td()}><b>${requirements.length}</b></td><td ${td('color:#c00000')}>${crit}</td>
      <td ${td()}>${high}</td><td ${td()}>${confirmed}</td>
      <td ${td('color:#c00000')}>${critV}</td><td ${td()}>${highV}</td></tr>
  </table><br/>
  ${top.length ? `<p style="margin:6pt 0;font-weight:bold;font-size:11pt">Top 风险</p>
  <table ${REQ_TABLE}>
    <tr><th ${td('background:#eee;font-weight:bold;width:16%')}>编号</th>
      <th ${td('background:#eee;font-weight:bold')}>需求标题</th>
      <th ${td('background:#eee;font-weight:bold;width:10%')}>优先级</th>
      <th ${td('background:#eee;font-weight:bold;width:20%')}>来源</th></tr>
    ${topRows}
  </table><br/>` : ''}
  <p style="margin:4pt 0;font-size:10.5pt;color:#666">合规目标覆盖: ${coverage}(按需求监管出处统计)。</p>`
}
