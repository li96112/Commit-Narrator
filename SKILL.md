---
name: commit-narrator
description: Analyze git history and generate a project narrative — eras, milestones, hotspot files, contributor profiles, velocity trends, and a new engineer reading guide. Zero dependencies, works on any git repo.
metadata: {"openclaw":{"emoji":"📖","requires":{"bins":["python3","git"]},"homepage":"https://github.com/li96112/Commit-Narrator"}}
---

# Commit-Narrator — 项目故事书

> 读 Git 历史，讲项目故事

分析任意 Git 仓库的提交历史，自动识别项目阶段、里程碑、高风险文件、贡献者画像、开发节奏，生成一份"新人入职第一天就能读懂"的项目叙事。

## Agent 调用方式

当用户提到"分析 git 历史"、"项目故事"、"Commit-Narrator"、"新人文档"时：

### 分析当前仓库

```bash
python3 {baseDir}/scripts/narrator.py --output /tmp/narrator_story.md
# 读取 /tmp/narrator_story.md 展示给用户
```

### 带过滤条件分析

```bash
# 分析指定目录的仓库
python3 {baseDir}/scripts/narrator.py --repo /path/to/project --output /tmp/narrator_story.md

# 只看某个时间段
python3 {baseDir}/scripts/narrator.py --since 2026-01-01 --until 2026-04-01 --output /tmp/story.md

# 只看某个作者的贡献
python3 {baseDir}/scripts/narrator.py --author "Zhang" --output /tmp/story.md

# 只看某个目录的历史
python3 {baseDir}/scripts/narrator.py --path src/components --output /tmp/story.md

# 同时导出 JSON 数据
python3 {baseDir}/scripts/narrator.py --json /tmp/analysis.json --output /tmp/story.md
```

### 触发关键词
- "分析这个项目的 git 历史" / "项目故事" / "commit 分析"
- "Commit-Narrator" / "narrator"
- "给新人写个项目介绍" / "新人入职文档"
- "谁贡献最多" / "哪些文件改动最频繁"
- "项目发展阶段" / "里程碑" / "hotspot"

## 分析维度

| 维度 | 内容 |
|------|------|
| **Project Summary** | 总 commit 数、贡献者数、时间跨度、代码行数净增 |
| **Commit Breakdown** | 按类型分类：feat/fix/refactor/docs/chore/init/release（含可视化柱形图） |
| **Project Eras** | 自动检测项目阶段（Bootstrap → Feature Build → Stabilization → Maintenance） |
| **Milestones** | 重大节点：初始化、大规模重构、版本发布、架构变更 |
| **Hotspot Files** | 最频繁变更的文件（高变更 = 高风险），含 churn 量和风险等级 |
| **Contributors** | 每人的提交数、代码量、活跃天数、专注领域、主要贡献类型 |
| **Activity Patterns** | 每周/每天活跃度热力图、高峰编码时段 |
| **Velocity Trend** | 开发速度趋势：加速 / 减速 / 稳定 |
| **Reading Guide** | 新人入职阅读路线：从哪个 commit 开始读、看什么文件、跟谁的代码 |

## Commit 分类规则

支持 Conventional Commits + 中文 commit message：

| 类型 | 匹配模式 | 示例 |
|------|----------|------|
| Feature | `feat(...)`, `add:`, `新增`, `implement` | feat(auth): add OAuth2 login |
| Bug Fix | `fix(...)`, `修复`, `hotfix`, `patch` | fix: 修复登录页空指针 |
| Refactor | `refactor(...)`, `重构`, `restructure` | refactor: extract auth module |
| Documentation | `docs:`, `文档`, `readme` | docs: update API reference |
| Test | `test:`, `测试`, `spec` | test: add unit tests for parser |
| Performance | `perf:`, `优化`, `optimize` | perf: reduce bundle size by 40% |
| Chore | `chore:`, `build:`, `ci:`, `deps`, `配置` | chore: upgrade webpack to v5 |
| Init | `init`, `initial commit`, `初始` | Initial commit |
| Release | `release`, `v1.0`, `版本` | release: v2.0.0 |

## 零依赖

纯 Python 标准库 + git CLI，不需要安装任何额外包。

## 文件说明

| 文件 | 作用 |
|------|------|
| `scripts/narrator.py` | 核心引擎：Git 数据提取 + 分类 + 多维度分析 + 叙事生成 |
