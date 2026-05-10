# Agent Roundtable

> 跨厂商盲审的多-agent 协作 substrate：Codex CLI / Claude Code / Cursor subagent 在同一个文件 thread 上接力 plan / execute / review，全程审计落盘。

## 为什么不直接用一家 CLI

同家训练的模型共享盲点。并行盲审里 85% 的 reviewer 顺着先到的 verdict 走（modal adoption sycophancy, arXiv:2605.00914）。Roundtable 强制：

- 并行 reviewer / planner / executor-race **必须不同厂商**；
- reviewer 必须 `--blind`，脚本自动从 prompt 剥离上一轮 verdict；
- 每次 dispatch 前显示 thread / role / actor / model / 估价 + `AskQuestion(GO / 调整 / 取消)`；
- 每 turn 的 prompt / stdout / verdict.json 全落到 `.roundtable/threads/<slug>/history/`。

---

## 一次性 setup

```
git clone … ~/.cursor/skills/agent-roundtable
对 Cursor 说：用 roundtable-setup 初始化
```

按问答走完 5 步：选 `ROUNDTABLE_PROJECT_ROOT` → 填 `models.json` + API key → `backend.sh apply`（含 smoke test）→ 生成 `AGENTS.md` / `CLAUDE.md` → 拷 `.claude/settings.json` 模板（拒绝破坏性 git + secrets 读取）。

---

## 操作指南

> 说明：下文 `/roundtable-X` 是「显式调用 sub-skill X」的简写——在 Cursor 里说「用 roundtable-X」/「跑 roundtable-X」/「/roundtable-X」都等价。skill 全部 `disable-model-invocation: true`，**必须显式点名才会触发**。

### 主流程（推荐）：Cursor plan → 审 → 执行 → 再审

最常用的链路。Cursor 出初稿，roundtable 跨厂商把关，落地后再过一次盲审。

```text
你做     : 在 Cursor Plan 模式写好 ~/.cursor/plans/foo.plan.md

你说     : 起 thread "foo-20260511" 并导入这个 plan
Cursor做 : new_thread.sh foo-20260511 "<one-line>"
           import_plan.sh foo-20260511 ~/.cursor/plans/foo.plan.md
           → artifacts/PLAN.md (含 import 元数据)
           → GOAL.md ## Plan source 段写入源路径 / 时间

你说     : /roundtable-review   # 审 artifacts/PLAN.md
Cursor做 : Dispatch Confirmation → 你点 GO
           跨厂商 2 reviewer (--blind) + aggregator
           → verdict.json (BLOCKER / MAJOR + 异议)

你做     : 在 ~/.cursor/plans/foo.plan.md 里改 plan

你说     : /roundtable-execute   # 落地
Cursor做 : 自动 re-run import_plan.sh (--reviewed yes)
           Dispatch Confirmation → 你点 GO
           executor 强制读 artifacts/PLAN.md 全文，按 plan 步骤实现
           完成后跑 scope_check.py 比 diff vs GOAL.md In-scope
           PASS / VIOLATION → AskQuestion: revert / 接受改 GOAL / re-plan

你说     : /roundtable-review   # 审这次 diff
Cursor做 : 同上 → 给 accept / revise 建议
```

**关键**：每次 Cursor plan 改完，让 Cursor 重新 `import_plan.sh`——executor 才能看到新内容。脚本幂等，重复跑无害。

### 从零开始（没现成 plan）

```text
你说     : /roundtable-plan 帮我看几个方案做 X
Cursor做 : AskQuestion: 只列 options 还是一路到 PLAN.md
           Phase A: N 个 cross-vendor planner 出 plan-*.md → options.md
           (可选) Phase B: aggregator 合成 artifacts/PLAN.md

你说     : /roundtable-execute   # 后续同主流程
```

### 全自动收敛循环

```text
你说     : /roundtable-goal 实现 X，预算 3 轮
Cursor做 : 一次 Dispatch Confirmation 锁定 budget
           plan → execute (含 scope_check) → 跨厂商盲审 → aggregator
           转圈直到 BLOCKER==0 且 converged
           stall / 违规 / budget hit → AskQuestion 让你决定
```

### 纯审计（PR / 已有代码）

```text
你说     : /roundtable-review 审 src/auth/ (或 PR #123)
Cursor做 : 让你确认 acceptance criteria → 写进 GOAL.md
           跨厂商盲审 → aggregator → verdict.json
           不动代码；要修复就接 /roundtable-execute 或 /roundtable-goal
```

---

## 5 个 sub-skill

| Sub-skill | 用途 | 什么时候用 |
|---|---|---|
| `roundtable-setup`   | 初始化 / 重配 API key / 生成 AGENTS.md | 第一次用 / 加新 actor |
| `roundtable-plan`    | N 厂商 planner → options.md / PLAN.md | 没现成 plan，要先看方案 |
| `roundtable-review`  | 跨厂商盲审 + aggregator，**只产 verdict** | 审 plan / 审 diff / PR |
| `roundtable-execute` | 单 executor 落地 PLAN.md + scope check | 已有 PLAN，要写代码 |
| `roundtable-goal`    | plan → execute → review 收敛循环 | 全自动跑到 BLOCKER==0 |

## 6 个用户脚本（其它都是内部实现）

| 脚本 | 用途 |
|---|---|
| `backend.sh` | `init` / `apply` / `show` model registry + API key |
| `new_thread.sh <slug> "<goal>"` | 建 thread 目录 + GOAL.md 模板 |
| `import_plan.sh <slug> <plan-path> [--reviewed yes\|no]` | Cursor plan → `artifacts/PLAN.md` + 同步 `GOAL.md` |
| `codex_turn.sh` / `claude_turn.sh` | 跑一个 turn（agent 调用，不用你自己输） |
| `route.sh --role <r> -m <m> --estimate` | 选 actor / 估价 |

---

## 多厂商在 3 个层面有用

- **质量** — 跨厂商盲审消除单一训练源盲点；N 个独立 reviewer 同意 = self-consistency 信号。
- **成本** — 便宜模型 vs 强模型 ~100× 量级差；`route.sh` 按角色权重把 compactor / triage 推到便宜，aggregator 推到最强。
- **可用性** — opt-in `failover_policy`：rate-limit / timeout 自动按 `fallback_chain` 切下一家。

完整论证：[docs/research/MULTI_VENDOR_VALUE_2026-05-10.md](docs/research/MULTI_VENDOR_VALUE_2026-05-10.md)。

## 设计原则

- **Dispatch Confirmation + AskQuestion** — 每次发车前显式确认，"GO" 才发；调整走自由描述。
- **完整审计** — `.roundtable/threads/<slug>/{THREAD.md, history/, artifacts/, .budget_ledger.jsonl}`。
- **Plan 强约束** — `GOAL.md ## Plan source` + `artifacts/PLAN.md`；executor system prompt 强制按 plan 顺序执行并引用章节。
- **权限分层** — reviewer / planner / discussant 强制只读 (`--permission-mode plan` / `--sandbox read-only`)；executor 走 `.claude/settings.json` 拒绝列表。
- **凭证隔离** — API key 在 `chmod 600` 的本地 env 文件，不进 git / prompt / 对话上下文。
- **上下文卫生** — 发现新规则的 turn 必须先更新 `AGENTS.md` / `.planning/` 再 hand-off。

## 进阶

- [docs/MODEL-CAPABILITY-GUIDE.md](docs/MODEL-CAPABILITY-GUIDE.md) — 模型注册表、能力对比、地缘风险分散
- [docs/advanced.md](docs/advanced.md) — N 并行 executor race / 高级 dispatch
- [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md) — 权限层、估价、recalibration

## License

[MIT](LICENSE)
