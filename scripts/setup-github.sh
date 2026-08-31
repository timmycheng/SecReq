#!/usr/bin/env bash
# 一次性初始化 GitHub 仓库流程基建: type/priority 标签集 + main 分支保护。
# 前置: 安装 gh CLI 并 gh auth login, token 需仓库 admin 权限。
# 幂等: 重复执行只更新同名标签与保护规则。
set -euo pipefail

REPO="${GH_REPO:-timmycheng/SecReq}"

echo "── 创建标签集 ──"
while IFS='|' read -r name color desc; do
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
done <<'LABELS'
type: bug|d73a4a|缺陷修复
type: feature|1d76db|新功能
type: docs|0075ca|文档
type: chore|bfdadc|工程杂项
type: ci|0e8a16|CI/流水线
priority: P0|b60205|阻塞项: 先修
priority: P1|d93f0b|重要: 尽快修
priority: P2|fbca04|一般: 排期修
dependencies|0366d6|依赖更新(Dependabot)
LABELS

echo "── 配置 main 分支保护 ──"
# 规则: 必须走 PR(0 个必需批准, 单人可自审自合) + 三项 CI 状态检查必过
#       + 线性历史 + 仅允许 squash 合并, 对管理员同样生效。
# 注意: contexts 中的检查名必须与 ci.yml 各 job 的 name 字段逐字一致。
if gh api -X PUT "repos/${REPO}/branches/main/protection" --input - <<'JSON'; then
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["后端测试", "后端 Lint", "前端检查"]
  },
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "enforce_admins": true,
  "restrictions": null,
  "required_linear_history": true,
  "allow_squash_merge": true,
  "allow_merge_commit": false,
  "allow_rebase_merge": false,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
  echo "分支保护已配置"
else
  cat <<'MANUAL'
gh 配置失败(token 权限不足或 API 变更)。请手动设置:
  仓库页 → Settings → Branches → Add branch protection rule:
  - Branch name pattern: main
  - Require a pull request before merging(Required approvals 填 0)
  - Require status checks to pass: 勾选 后端测试 / 后端 Lint / 前端检查
  - Require linear history
  - 仅勾选 Allow squash merging
  - 勾选 Include administrators
MANUAL
fi

echo "── 完成 ──"
