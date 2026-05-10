# Agent Roundtable

> 跨厂商盲审的多-agent 协作 substrate：Codex CLI / Claude Code / Cursor subagent 在同一个文件 thread 上接力 plan / execute / review，全程审计落盘。

## 你想… → 输入这个

> 5 个 sub-skill 都 `disable-model-invocation: true`，必须**显式点名**。`/roundtable-X` 和「用 roundtable-X」都能触发；用哪种顺手。

| 你的场景 | 输入 | 链路一句话 |
|---|---|---|
| **第一次用 / 加 actor** | `/roundtable-setup` | 引导填 models.json + API key + AGENTS.md |
| **调研：想看几个方案** | `/roundtable-plan 看几个方案做 X` | 多家 planner 并行 → `options.md` |
| **执行 Cursor plan**（最常用） | `导入这个 plan: <路径>` → `/roundtable-review` → （改 plan）→ `/roundtable-execute` → `/roundtable-review` | cursor-plan → 审 → 改 → 落地 → 再审 |
| **已有 PLAN.md，直接干** | `/roundtable-execute` | 单 executor + scope check |
| **审已有代码 / PR** | `/roundtable-review 审 src/auth/` 或 `审 PR #123` | 跨厂商盲审 → verdict（不动代码）|
| **全自动跑到 BLOCKER==0** | `/roundtable-goal 实现 X，预算 3 轮` | plan → execute → review 收敛循环 |

每次发车前 Cursor 都会 paste **Dispatch Confirmation**（thread / role / actor / 估价）+ AskQuestion(**GO / 调整 / 取消**)，你点一下就跑。

---

## 主流程详解：Cursor plan → 审 → 改 → 落地 → 再审

最高频的链路。Cursor Plan 模式出初稿，roundtable 跨厂商把关 + 落地。

```text
你做      在 Cursor Plan 模式写好 ~/.cursor/plans/foo.plan.md

你输      "导入这个 plan: ~/.cursor/plans/foo.plan.md"
Cursor做  import_plan.sh ~/.cursor/plans/foo.plan.md
          • slug 派生 (foo-20260511)，thread 不存在自动建
          • 写 artifacts/PLAN.md  +  GOAL.md ## Plan source
          → 报告 slug 给你

你输      /roundtable-review
Cursor做  Dispatch Confirmation → 你 GO
          → 跨厂商 2 reviewer (--blind) + aggregator
          → verdict.json (BLOCKER / MAJOR + 异议)

你做      根据 verdict 在 ~/.cursor/plans/foo.plan.md 里改

你输      /roundtable-execute
Cursor做  自动重跑 import_plan.sh --reviewed yes（同步最新 plan）
          → Dispatch Confirmation → 你 GO
          → executor 强制读 artifacts/PLAN.md 全文，按 plan 顺序实现
          → scope_check.py 比 diff vs GOAL.md In-scope
          → PASS / VIOLATION→AskQuestion(revert / 接受改 GOAL / re-plan)

你输      /roundtable-review
Cursor做  审这次 diff → accept / revise 建议
```

**关键**：每次 Cursor plan 改完，回 Cursor 说"重新导入" / 直接走 `/roundtable-execute`（会自动同步）——executor 看到的才是新内容。

## 其它场景

### 调研：拿不准方向 → `/roundtable-plan`

```text
你输      /roundtable-plan 看几个方案做 X
Cursor做  AskQuestion: 只列 options / 一路到 PLAN.md
          Phase A: N 家 cross-vendor planner → 各自 plan-*.md → 合成 options.md
          (可选) Phase B: aggregator → artifacts/PLAN.md
你做      看 options.md 决定路径 → 接 /roundtable-execute 或 /roundtable-goal
```

### 纯审计：审代码或 PR → `/roundtable-review`

```text
你输      /roundtable-review 审 src/auth/   （或 "审 PR #123"）
Cursor做  让你确认 acceptance criteria → 写进 GOAL.md
          → 跨厂商 2 reviewer (--blind) + aggregator → verdict.json
          不动代码；要修复就接 /roundtable-execute 或 /roundtable-goal
```

### 全自动循环：放手不管 → `/roundtable-goal`

```text
你输      /roundtable-goal 实现 X，预算 3 轮
Cursor做  一次 Dispatch Confirmation 锁定 budget
          plan → execute (scope_check) → 跨厂商盲审 → aggregator
          转圈直到 BLOCKER==0 且 converged
          stall / 违规 / budget hit → AskQuestion 让你决定
```

---

## 为什么不直接用一家 CLI

同家训练的模型共享盲点。并行盲审里 85% 的 reviewer 顺着先到的 verdict 走（modal adoption sycophancy, arXiv:2605.00914）。Roundtable 强制：

- 并行 reviewer / planner / executor-race **必须不同厂商**；
- reviewer 必须 `--blind`，脚本自动剥离上一轮 verdict；
- 每次 dispatch 前显示参数 + AskQuestion(GO / 调整 / 取消)；
- 每 turn 的 prompt / stdout / verdict.json 全落到 `.roundtable/threads/<slug>/history/`。

完整论证：[docs/research/MULTI_VENDOR_VALUE_2026-05-10.md](docs/research/MULTI_VENDOR_VALUE_2026-05-10.md)。

## 一次性 setup

```
git clone … ~/.cursor/skills/agent-roundtable
对 Cursor 说：/roundtable-setup
```

按问答 5 步：选 `ROUNDTABLE_PROJECT_ROOT` → 填 `models.json` + API key → `backend.sh apply`（含 smoke test）→ 生成 `AGENTS.md` / `CLAUDE.md` → 拷 `.claude/settings.json` 模板（拒绝破坏性 git + secrets 读取）。

---

## 5 个 sub-skill

| Sub-skill | 用途 | 什么时候用 |
|---|---|---|
| `roundtable-setup`   | 初始化 / 重配 API key / 生成 AGENTS.md | 第一次 / 加新 actor |
| `roundtable-plan`    | N 厂商 planner → options.md / PLAN.md | 没现成 plan，先看方案 |
| `roundtable-review`  | 跨厂商盲审 + aggregator，**只产 verdict** | 审 plan / 审 diff / PR |
| `roundtable-execute` | 单 executor 落地 PLAN.md + scope check | 已有 PLAN，要写代码 |
| `roundtable-goal`    | plan → execute → review 收敛循环 | 全自动跑到 BLOCKER==0 |

## 6 个用户脚本（其它都是内部实现）

| 脚本 | 用途 |
|---|---|
| `backend.sh` | `init` / `apply` / `show` model registry + API key |
| `new_thread.sh <slug> "<goal>"` | 建 thread（多数时候不用手跑，`import_plan.sh` 会代劳）|
| `import_plan.sh <plan-path> [--slug X] [--reviewed yes\|no]` | Cursor plan → `artifacts/PLAN.md` + 同步 GOAL.md；thread 不存在自动建 |
| `codex_turn.sh` / `claude_turn.sh` | 跑一个 turn（agent 调用，不用你自己输）|
| `route.sh --role <r> -m <m> --estimate` | 选 actor / 估价 |

---

## 多厂商在 3 个层面有用

- **质量** — 跨厂商盲审消除单一训练源盲点；N 个独立 reviewer 同意 = self-consistency 信号。
- **成本** — 便宜模型 vs 强模型 ~100× 量级差；`route.sh` 按角色权重把 compactor / triage 推到便宜，aggregator 推到最强。
- **可用性** — opt-in `failover_policy`：rate-limit / timeout 自动按 `fallback_chain` 切下一家。

## 设计原则

- **Dispatch Confirmation + AskQuestion** — 每次发车前显式确认；"GO" 才发，调整走自由描述。
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
