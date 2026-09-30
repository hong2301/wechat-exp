# 仓库管理方案：fork 还是独立仓库？

## 结论：推荐「独立仓库 + upstream 关联」方式

```
你的仓库 (github.com/你/wechat-exp)
   └─ 完整项目（上游代码 + my_tools/ 自定义功能）
   └─ git remote add upstream = 原项目（同步用）
```

## 为什么不用 fork

| 对比维度 | fork | 独立仓库 ✅ |
|---|------|---------|
| 上游更新同步 | 页面点 Sync fork | `git fetch upstream && git merge`（一样简单） |
| 原仓库被删/被 DMCA | **fork 可能一起消失**（本领域微信官方 2025 年已下架 3 个大项目） | 完全不受影响 🔒 |
| 代码回馈上游 | 可发 PR | 可发 PR，效果一样 |
| 完全自主管理 | 受 fork 关系影响 | 无约束 |

关键点：本领域（微信数据解密）项目随时可能被官方投诉下架，**独立仓库不受牵连**，
而 git 同步能力两者完全等价。

## 操作步骤（本仓库已就绪）

```bash
# 1. 在 GitHub 新建空仓库 wechat-exp（不要勾选 README）
# 2. 本地关联你的仓库 + 保留上游
git remote add origin  https://github.com/你的用户名/wechat-exp.git
git remote add upstream https://github.com/sunhanaix/pc_wechat_exp.git
git add -A && git commit -m "feat: 新增 my_tools 两个核心功能（提取/查询）"
git push -u origin main

# 3. 以后上游每有更新
git fetch upstream
git merge upstream/main      # my_tools/ 独立，几乎零冲突

# 4. 有其他电脑/环境要同步上游时，同样执行上面的 fetch+merge
```

## 目录约定（保证零冲突）

```
wechat-exp/
├── my_tools/        ← 你的两个核心功能（独立文件夹，不碰上游文件）
├── my_output/       ← 运行产物（gitignore，不提交）
├── src/ ...         ← 上游代码（从不直接修改，只随 upstream 更新）
└── .gitignore
```

> 提示：`.wechat_exp_config.json`（数据库密钥）已在 .gitignore，绝不提交。