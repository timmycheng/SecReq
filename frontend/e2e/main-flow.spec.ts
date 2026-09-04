import { expect, test } from '@playwright/test'

/* 主链路 E2E(#72): 建系统 → 建项目 → 6 步向导 → 生成 → 批量确认 → 导出。
   覆盖平台最核心用户路径的前端行为(步骤保存/批量确认/导出下载)。 */

test('建系统 → 建项目 → 6步向导 → 生成 → 批量确认 → 导出', async ({ page }) => {
  test.setTimeout(300_000)

  // ── 登录(种子账号, 密码来自 playwright.config webServer env) ──
  await page.goto('/')
  await page.getByPlaceholder('用户名').fill('dev_admin')
  await page.getByPlaceholder('密码').fill('e2e-pass')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.getByRole('button', { name: '发起新评估' }).first())
    .toBeVisible({ timeout: 20_000 })

  // ── 先建系统(#194: 评估挂靠系统, 基本信息/清单都在系统上) ──
  await page.getByText('系统台账', { exact: true }).first().click()
  await page.getByRole('button', { name: '新建系统' }).click()
  const sysModal = page.locator('.ant-modal').filter({ hasText: '系统名称' })
  await sysModal.getByPlaceholder('如: 个人网银系统').fill('E2E 主链路系统')
  await sysModal.locator('.ant-form-item', { hasText: '用户规模' }).locator('.ant-select').click()
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item')
    .first().click()
  await sysModal.getByRole('button', { name: /确\s*定/ }).click()
  // 弹窗关闭 + 台账表格出现该系统行, 才算创建成功
  await expect(sysModal).toBeHidden({ timeout: 20_000 })
  await expect(page.locator('.ant-table').getByText('E2E 主链路系统')).toBeVisible({ timeout: 20_000 })
  await page.getByText('评估管理', { exact: true }).first().click()
  await expect(page.getByRole('button', { name: '发起新评估' }).first())
    .toBeVisible({ timeout: 20_000 })

  // ── 建项目(新建弹窗默认空白新建, #172 → 直通向导第一步) ──
  await page.getByRole('button', { name: '发起新评估' }).first().click()
  await page.getByRole('button', { name: '创建并进向导' }).click()
  await expect(page.getByText('评估编码(自动生成)')).toBeVisible({ timeout: 20_000 })

  // ── 第 1 步: 评估定级(绑定系统 + 合规目标 + 直接指定三级) ──
  await page.getByPlaceholder('如: 个人网银系统').fill('E2E 主链路项目')
  // 选择所属系统(antd Select 虚拟滚动, 键盘导航最稳)
  const sysItem = page.locator('.ant-form-item', { hasText: '所属系统(台账)' }).first()
  await sysItem.locator('.ant-select').first().click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  // 合规目标: 等级保护
  await page.getByText('等级保护', { exact: true }).click()
  // 直接指定等级: 三级(触发政策基线与等保合规规则)
  const levelSelect = page.locator('.ant-select').filter({ hasText: '不走问卷时直接选择' })
  await levelSelect.click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: /保存并下一步/ }).click()

  // ── 第 2 步: 功能清单(录入一条登录功能, 让需求清单有真实来源) ──
  await expect(page.getByRole('button', { name: '新增功能' })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: '新增功能' }).click()
  await page.getByPlaceholder('如: 转账汇款').fill('登录认证')
  // 功能分类必填: 多选下拉用键盘选中首项(antd 两字按钮文案带空格, 匹配用 /确\s*定/)
  const catItem = page.locator('.ant-form-item', { hasText: '功能分类(可多选)' }).first()
  await catItem.locator('.ant-select').click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /确\s*定/ }).click()
  await page.getByRole('button', { name: /保存并下一步/ }).click()

  // ── 第 3~7 步: 依次保存推进(带自愈: 点击后未推进则重试) ──
  const activeStep = page.locator('.ant-steps-item-active')
  const advanceTo = async (next: string) => {
    for (let attempt = 0; attempt < 4; attempt++) {
      await page.getByRole('button', { name: /保存并下一步/ }).click()
      try {
        await expect(activeStep).toContainText(next, { timeout: 12_000 })
        return
      } catch {
        // 步骤未推进(点击落在过渡期): 稍候重试
        await page.waitForTimeout(800)
      }
    }
    throw new Error(`未能推进到步骤: ${next}, 当前: ${await activeStep.textContent()}`)
  }

  // ── 第 3 步: 数据字典(禁止空保存, 录入一条最小资产) ──
  await expect(activeStep).toContainText('数据字典', { timeout: 20_000 })
  await page.getByRole('button', { name: '新增数据资产' }).click()
  await page.getByPlaceholder('如: 银行账户信息').fill('E2E 客户信息')
  const dtypeItem = page.locator('.ant-form-item', { hasText: '数据类别' }).first()
  await dtypeItem.locator('.ant-select').click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  const clsItem = page.locator('.ant-form-item', { hasText: '分级(?)' }).first()
  await clsItem.locator('.ant-select').click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: '新增数据表' }).click()
  await page.getByPlaceholder('物理表名, 如 t_bank_account').fill('t_e2e_customer')
  await page.getByRole('button', { name: /创\s*建/ }).click()
  await page.getByRole('button', { name: '保存资产' }).click()
  await advanceTo('权限矩阵')

  // ── 第 4 步: 权限矩阵(角色已预置; 资源需至少一条, 授权格可留空) ──
  await expect(activeStep).toContainText('权限矩阵', { timeout: 20_000 })
  await page.getByRole('button', { name: '添加' }).nth(1).click()  // 资源编辑器的「添加」
  await page.getByPlaceholder('资源名, 如 交易流水记录').fill('E2E 客户数据')
  // #194: 组件/基础设施已上收系统台账, 向导收敛为 6 步
  await advanceTo('API接口')
  await advanceTo('确认生成')

  // ── 第 8 步: 确认生成(默认本地离线库, 保持用例封闭) ──
  await expect(page.locator('.ant-steps-item-active')).toContainText('确认生成', { timeout: 20_000 })
  await page.getByRole('button', { name: /生成安全基线/ }).click()

  // 生成完成 → 跳转产物页(默认落「执行摘要」页签, #171); 等生成提示后切入需求清单页签
  await expect(page.getByText(/已生成 \d+ 条安全需求/).first())
    .toBeVisible({ timeout: 60_000 })
  await page.getByRole('tab', { name: /安全需求清单/ }).click()
  await expect(page.getByRole('button', { name: /确认全部 \d+ 条待确认需求/ })
    .or(page.getByRole('button', { name: '批量确认' })).first())
    .toBeVisible({ timeout: 30_000 })

  // ── 批量确认(验证确认状态) ──
  const confirmAll = page.getByRole('button', { name: /确认全部 \d+ 条待确认需求/ })
  if (await confirmAll.count()) {
    await confirmAll.first().click()
    await expect(page.getByText(/已确认 \d+ 条/).first()).toBeVisible({ timeout: 30_000 })
  } else {
    await page.getByRole('button', { name: '批量确认' }).first().click()
    await expect(page.getByText(/已确认 \d+ 条/).first()).toBeVisible({ timeout: 30_000 })
  }
  await expect(page.getByText(/已确认/).first()).toBeVisible()

  // ── 导出(下载 docx, 校验文件落盘) ──
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载 Word 文档' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toContain('安全需求说明书')
  const path = await download.path()
  expect(path).toBeTruthy()
})
