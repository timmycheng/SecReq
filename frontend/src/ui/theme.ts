/**
 * 品牌主题唯一来源(#268): ConfigProvider 全局 theme 配置与品牌色常量。
 *
 * - 状态语义色(需求状态/分级/门禁/角色标签等)在 ui/tokens.ts, 本文件只管品牌与布局外壳;
 * - style 场景需要品牌色时引 PRIMARY 常量, 不得再写色值字面量;
 * - ConfigProvider 在 App.tsx 单点挂载, 各页面不得自建 ConfigProvider 覆盖品牌。
 * - #280 改版: 品牌色与侧边栏深海军蓝分组菜单对齐新原型。
 */
import { theme as antdTheme } from 'antd'
import type { ThemeConfig } from 'antd'

/** 品牌主色: 唯一定义处 */
export const PRIMARY = '#2f54eb'

/** 品牌渐变: 用于登录页背景与顶部品牌区 */
export const BRAND_GRADIENT = 'linear-gradient(135deg, #2f54eb 0%, #722ed1 100%)'

/** 侧边栏深海军蓝配色: 与菜单选中态/分组标题保持一致 */
export const SIDER_BG = '#0e1c33'
export const SIDER_TRIGGER_BG = '#16263f'
export const SIDER_ITEM_COLOR = '#a6b5cd'
export const SIDER_GROUP_COLOR = 'rgba(166, 181, 205, 0.55)'
export const SIDER_SELECTED_BG = '#1e3257'

/** 全局 antd 主题: 品牌主色 + 圆角 + 分组侧边菜单配色 */
export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: PRIMARY,
    borderRadius: 6,
    // 内容区底色(浅灰蓝): 白色卡片在其上分层
    colorBgLayout: '#f5f6fa',
    fontSize: 14,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      siderBg: SIDER_BG,
      triggerBg: SIDER_TRIGGER_BG,
    },
    Menu: {
      darkItemBg: 'transparent',
      darkPopupBg: SIDER_SELECTED_BG,
      darkItemColor: SIDER_ITEM_COLOR,
      darkItemHoverColor: '#ffffff',
      darkItemHoverBg: 'rgba(255, 255, 255, 0.06)',
      darkItemSelectedBg: SIDER_SELECTED_BG,
      darkItemSelectedColor: '#ffffff',
      darkGroupTitleColor: SIDER_GROUP_COLOR,
      itemBorderRadius: 8,
      itemMarginInline: 12,
      itemHeight: 40,
      activeBarBorderWidth: 0,
    },
  },
  algorithm: antdTheme.defaultAlgorithm,
}
