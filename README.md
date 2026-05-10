# Agent Roundtable

> 跨厂商盲审的多-agent 协作 substrate：Codex / Claude / Cursor subagent 在一个 thread 上接力 plan / execute / review，全程审计落盘。

## 你想… → 输入

> `/roundtable-X` ≡「用 roundtable-X」——显式点名 skill（都 `disable-model-invocation`）。

| 场景 | 输入 | 链路 |
|---|---|---|
| **首次用 / 加 actor** | `/roundtable-setup` | 问答走完 models.json + API key + AGENTS.md |
| **调研，看几个方案** | `/roundtable-plan 看几个方案做 X` | N 家 cross-vendor planner → `options.md`（可继续 → `PLAN.md`）|
| **执行 Cursor plan**（主流程）| `导入这个 plan: <路径>` → `/roundtable-review` → 改 plan → `/roundtable-execute` → `/roundtable-review` | 详见下 |
| **已有 PLAN.md 直接干** | `/roundtable-execute` | 单 executor + `scope_check.py` 自动比 GOAL.md In-scope |
| **审已有代码 / PR** | `/roundtable-review 审 src/auth/`（或 `审 PR #123`）| 跨厂商盲审 → `verdict.json`；不动代码 |
| **全自动跑到 BLOCKER==0** | `/roundtable-goal 实现 X，预算 3 轮` | plan → exec → review 循环；stall / 违规 / budget hit → AskQuestion |

发车前都会 paste **Dispatch Confirmation**（thread / role / actor / 估价）+ `AskQuestion(GO / 调整 / 取消)`，你点一下就跑。

## 主流程展开

```text
你做      Cursor Plan 模式写 ~/.cursor/plans/foo.plan.md
你输      "导入这个 plan: ~/.cursor/plans/foo.plan.md"
Cursor做  import_plan.sh foo.plan.md
          → slug=foo-20260511 (auto), thread 不存在自动建
          → artifacts/PLAN.md + GOAL.md ## Plan source

你输      /roundtable-review     # 审 plan
          → 跨厂商 2 reviewer (--blind) + aggregator → verdict.json

你做      根据 verdict 改 ~/.cursor/plans/foo.plan.md
你输      /roundtable-execute
          → 自动 re-import (--reviewed yes) 同步最新 plan
          → executor 强制读 PLAN.md 全文，按 plan 顺序实现，引用章节
          → scope_check.py: PASS / VIOLATION → AskQuestion(revert / 改 GOAL / re-plan)

你输      /roundtable-review     # 审 diff → accept / revise
```

plan 改完直接 `/roundtable-execute` 即可，无需手动 re-import。

## 一次性 setup

```bash
git clone … ~/.cursor/skills/agent-roundtable
```
对 Cursor 说 `/roundtable-setup` → 问答走完：选项目根 → 填 `models.json` + API key → `backend.sh apply` **逐家测速**（1-token ping + 延迟汇总，`≥2000ms` 标 `SLOW`，`≥5000ms` 标 `VERY SLOW`，失败立刻 fail-fast）→ 生成 `AGENTS.md` / `CLAUDE.md` → 拷 `.claude/settings.json` 拒绝列表。日常想随时复测：`backend.sh validate`。

## 为什么跨厂商 + 落盘

- **质量** — 并行盲审里 85% reviewer 顺先到的 verdict 走（modal adoption sycophancy, arXiv:2605.00914）；跨厂商 + `--blind` + aggregator 保留 dissent 是唯一可靠破解。
- **成本** — 便宜 vs 强模型 ~100× 量级差；`route.sh` 按角色把 triage / compactor 推到便宜，aggregator 推到最强。
- **可审计** — 每 turn 的 prompt / stdout / `verdict.json` / `.budget_ledger.jsonl` 全落 `.roundtable/threads/<slug>/history/`。
- **可执行** — `GOAL.md ## Plan source` + `artifacts/PLAN.md` 强绑定；executor system prompt 强制按 plan 顺序读 + 引用章节号。
- **可控** — reviewer / planner / discussant vendor 强制只读 (`--permission-mode plan` / `--sandbox read-only`)；executor 走 `.claude/settings.json` 拒绝破坏性 git + secrets。
- **凭证隔离** — API key 在 `chmod 600` 本地 env 文件，不进 git / prompt / 对话上下文。

完整论证：[docs/research/MULTI_VENDOR_VALUE_2026-05-10.md](docs/research/MULTI_VENDOR_VALUE_2026-05-10.md)。

## 用户脚本（其余皆内部实现）

| 脚本 | 用途 |
|---|---|
| `backend.sh init/apply/show` | model registry + API key |
| `import_plan.sh <plan> [--slug X] [--reviewed yes\|no]` | plan → `artifacts/PLAN.md` + 同步 GOAL；thread 不存在自动建 |
| `new_thread.sh <slug> "<goal>"` | 单独建 thread（不必常用，`import_plan.sh` 代劳）|
| `route.sh --role <r> -m <m> --estimate` | 选 actor / 估价 |
| `codex_turn.sh` / `claude_turn.sh` | agent 自动调，不用手输 |

## 进阶

- [docs/MODEL-CAPABILITY-GUIDE.md](docs/MODEL-CAPABILITY-GUIDE.md) — 模型注册表、能力对比、地缘风险分散
- [docs/advanced.md](docs/advanced.md) — N 并行 executor race / 高级 dispatch
- [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md) — 权限层、估价、recalibration

## License

[MIT](LICENSE)
