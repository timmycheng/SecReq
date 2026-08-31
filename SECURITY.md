# 安全策略(Security Policy)

## 支持的版本

仅最新 Release 版本获得安全修复, 更新方式见 [README](README.md) 与 [CHANGELOG](CHANGELOG.md)。

## 报告漏洞

请**不要**通过公开 issue 报告安全漏洞, 使用 GitHub 的私密漏洞报告通道: 仓库页 Security → Advisories → Report a vulnerability, 或私信仓库维护者。

报告请尽量包含: 影响版本、复现步骤或 PoC、影响评估(机密性/完整性/可用性)、修复建议(如有)。演示数据与测试代码中刻意保留的旧组件、弱口令样例不属于漏洞。

## 响应预期

- 确认收到: 3 个工作日内。
- 评估与修复: 高危项按 `priority: P0` 处理, 发布 patch 版本并致谢报告者(除非要求匿名)。

## 部署方自查提示

平台初始种子账号口令由 `SECREQ_SEED_PASSWORD` 注入, 未设置时每次启动随机生成; 生产部署必须显式设置并在首登后修改, 详见 `.env.example`。
