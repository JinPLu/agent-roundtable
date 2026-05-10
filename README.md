# Agent Roundtable

> 跨厂商盲审的多-agent 协作 substrate：Codex CLI / Claude Code / Cursor subagent 在同一个文件 thread 上接力 plan / execute / review，全程审计落盘。

## 为什么不直接用一家 CLI

同家训练的模型共享盲点。在并行盲审里，85% 的 reviewer 会顺着先到的 verdict 走（modal adoption sycophancy, arXiv:2605.00914）。Roundtable 强制：
- 平行 reviewer 必须不同厂商；
- 必须 `--blind`，脚本自动从 prompt 剥离上一轮 verdict；
- 每次 dispatch 前显示 thread / role / actor / model / 估价，等你点 GO。

## 60 秒跑通

git clone 到 ~/.cursor/skills/agent-roundtable，对 Cursor 说："用 agent-roundtable 初始化"。`roundtable-setup` 会引导你建 models.json、注入 API key、给项目生成 AGENTS.md / CLAUDE.md。

第一个收敛循环：

> 用 roundtable-goal 实现登录功能，预算 3 轮

Cursor 会按 plan → 单 executor 执行 → 跨厂商盲审 → aggregate 循环到 BLOCKER==0。

## 5 个 sub-skill

| Sub-skill | 用途 |
|---|---|
| roundtable-setup   | 初始化 models.json / API key / AGENTS.md |
| roundtable-plan    | Phase A 平行 option matrix；Phase B aggregator 出 PLAN.md |
| roundtable-execute | 单 executor 落地 PLAN.md，强制 scope check |
| roundtable-review  | 跨厂商盲审 + aggregator，只产 verdict |
| roundtable-goal    | plan → execute → review 收敛循环，带 budget / stall / scope 控制 |

## 推荐 5 步工作流

| # | 谁 | 干什么 |
|---|---|---|
| 1 | 多家 planner | 各出 option matrix（roundtable-plan Phase A） |
| 2 | 强 aggregator | 合并成 PLAN.md（roundtable-plan Phase B） |
| 3 | 性价比执行器（如 gpt-5.5）| 实现 PLAN.md（roundtable-execute） |
| 4 | 跨厂商 2+ reviewer + aggregator | 盲审（roundtable-review） |
| 5 | 全自动 | 上述循环到收敛（roundtable-goal） |

## 多厂商在 3 个层面有用

- **质量** — 跨厂商盲审消除单一训练源盲点；N 个独立 reviewer 同意 = self-consistency 信号。
- **成本** — `gpt-5.4-mini` $0.125/1M vs `cursor-claude-4.7-opus` $25/1M（差 200×）。`route.sh` 按角色权重把 compactor / triage 推到便宜模型，aggregator 推到最强。
- **可用性** — `failover_policy`（opt-in）：rate-limit / timeout 自动按 fallback_chain 切。

完整 12 维度论证见 [docs/research/MULTI_VENDOR_VALUE_2026-05-10.md](docs/research/MULTI_VENDOR_VALUE_2026-05-10.md)。

## 设计原则

- **Dispatch confirmation** — 每次 dispatch 前显示 thread / role / actor / model / 估价，等用户确认。
- **完整审计** — 每 turn 的 prompt / stdout / verdict.json 都落到 `.roundtable/threads/<slug>/history/`。
- **满血工具面** — 默认开放 Read/Write/Bash/WebSearch/WebFetch；reviewer + planner 角色 vendor 强制只读；只屏蔽破坏性 git。
- **凭证隔离** — API key 通过 `chmod 600` 本地文件，不进 git / prompt / 对话上下文。
- **上下文卫生** — 发现新规则的 turn 必须先更新 AGENTS.md / .planning/，再 hand-off。

## 进阶

- [docs/MODEL-CAPABILITY-GUIDE.md](docs/MODEL-CAPABILITY-GUIDE.md) — 模型注册表、能力对比、地缘风险分散
- [docs/advanced.md](docs/advanced.md) — N 并行 executor race / 高级 dispatch

## License

[MIT](LICENSE)
