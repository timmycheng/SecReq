/**
 * 品牌主题唯一来源(#268): ConfigProvider 全局 theme 配置与品牌色常量。
 *
 * - 状态语义色(需求状态/分级/门禁/角色标签等)在 ui/tokens.ts, 本文件只管品牌与布局外壳;
 * - style 场景需要品牌色时引 PRIMARY 常量, 不得再写 '#2f5597' 字面量;
 * - ConfigProvider 在 App.tsx 单点挂载, 各页面不得自建 ConfigProvider 覆盖品牌。
 */
import type { ThemeConfig } from 'antd'

/** 品牌主色: 唯一定义处 */
export const PRIMARY = '#2f5597'

/** 登录页品牌渐变背景(主色同 ramp) */
export const BRAND_GRADIENT = `linear-gradient(160deg, #10234a 0%, ${PRIMARY} 60%, #3d6db8 100%)`

/** 全局 antd 主题: 品牌主色 + 圆角 + 布局外壳配色 */
export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: PRIMARY,
    borderRadius: 6,
    // 内容区底色(浅灰蓝): 白色卡片在其上分层
    colorBgLayout: '#f5f6fa',
  },
  components: {
    Layout: { headerBg: '#ffffff' },
  },
}
