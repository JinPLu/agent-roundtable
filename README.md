# Agent Roundtable

> 让 Codex CLI、Claude Code 和 Cursor 子 agent 在同一个任务上互相盲审、按协议接力——不是同一家厂商的"多 agent"，而是真正的跨厂商独立审查。

## 它解决什么

- **同厂商多 agent 的伪独立问题**：同一家训练的模型共享盲点；跨厂商并行盲审能消除 85% 的 modal adoption sycophancy（arXiv 2605.00914）。
- **审计可追溯性缺失**：每次 dispatch 的 prompt、输出、verdict.json 全部落盘在 `.roundtable/threads/<slug>/history/`，不依赖对话上下文。
- **调度不透明**：每次 dispatch 前必须给你看确认块（thread / role / actor / model / 估价），你说 GO 才真正发动。

## 多厂家协作的 6 个核心价值

### 质量组

**A — 反 sycophancy（盲审隔离）**  
并行 reviewer 必须来自不同 actor 家族，且必须带 `--blind` flag。脚本在 `build_prompt` 阶段直接抑制上一条 verdict，防止后到的 reviewer 直接跟着第一个的判断走（85.5% 的 modal adoption 发生在 reviewer 能看到先前 verdict 时，`codex_turn.sh:135`）。

**F — Self-consistency 信号**  
N 个独立 reviewer 都接受 = 比单个 reviewer 更强的置信信号；分歧 = 可靠的问题信号。reviewer-aggregator 现在在 JSON 之后的正文里记录 `Consensus: N actors all accepted; self-consistency HIGH.` 或 `Consensus: split — <actor> accepted, <actor> revised.`（见 `roles/reviewer.system.md` 步骤 8）。

### 成本与可用性组

**B — 价格分层**  
`gpt-5.4-mini` 输出 $0.125/1M，`cursor-claude-4.7-opus` 输出 $25/1M，相差 200 倍。`route.sh` 按角色权重把 compactor / triage 推到最便宜的模型，把 reviewer-aggregator 推到最强的模型，dispatch 确认块显示每轮估价。

**D — 故障互备（opt-in）**  
`failover_policy` 已实现，**默认关闭**。开启方式：`models.json` 中 `"enabled": true` + `export ROUNDTABLE_FAILOVER_OPT_IN=1`。开启后在 rate-limit / timeout / convergence-stall 时自动按 `fallback_chain` 换模型，首次 failover 前必须用户确认。跨厂商 failover（如 cialloapi 不可达时 fallback 到 DeepSeek）需手动在 `fallback_chain` 里加对方家族别名。

### 能力与覆盖组

**C — 能力互补**  
OpenAI 系 (`gpt-5.5`)：coding=9, english_io=9；DeepSeek 系 (`claude-opus`)：chinese_io=9，结构化推理强；Gemini 系 (`cursor-gemini-3.1-pro`)：long_context=10（注册表最高分）。`route.sh` 按角色权重自动路由到最合适的家族。

**L — 角色专精**  
`models.json` 里每个角色都有独立的 capability weight profile：`reviewer-aggregator` 看 reasoning(0.5) + long_context(0.3)，`executor` 看 agentic_tools(0.4) + coding(0.3)，`compactor` 看 long_context(0.5) + cost_bonus(0.5)。同一个 thread 里，最便宜的 compactor + 最强的 aggregator 可以同时存在。

> 另有 6 个价值维度在 `docs/research/MULTI_VENDOR_VALUE_2026-05-10.md` 详述：训练数据多样性(G)、知识截止互补(E)、推理路径多样性(I)、工具面异构(J)、合规独立性(H)、地缘风险分散(K)。

## 你的典型 5 步用法

**1. 多家调研 → `roundtable-plan` Phase A**

让多个厂家的 discussant / planner 各自给出候选方案矩阵，不推荐，由你拍板。

```bash
# 对 Cursor 说：
"用 roundtable-plan Phase A，让三家模型各给我一份 Redis vs Postgres 的 option matrix"
```

**2. 跨家审查计划 → `roundtable-plan` Phase B → `roundtable-review`**

Phase A 出来的选项让 aggregator 合并成 `artifacts/PLAN.md`；再让跨厂商 reviewer 审查计划质量，才交给执行。

```bash
# 对 Cursor 说：
"用 roundtable-plan Phase B 把刚才的 options 合并成 PLAN.md，然后用 roundtable-review 跨厂商盲审这个计划"
```

**3. 执行 → `roundtable-execute`**

单个 executor 把 `PLAN.md` / `GOAL.md` 落地。默认单 executor；N 并行 race 是 opt-in 模式，见 `docs/advanced.md`。

```bash
bash scripts/codex_turn.sh <slug> --role executor -m gpt-5.5 --task "implement PLAN.md"
# gpt-5.5 via cialloapi: 输出约 $0.42/1M，适合大多数执行任务
```

**4. 多家盲审 → `roundtable-review`**

并行两个不同家族的 reviewer（带 `--blind`），再跑一个 aggregator 出最终 verdict。

```bash
bash scripts/codex_turn.sh  <slug> --role reviewer -m gpt-5.5   --blind
bash scripts/claude_turn.sh <slug> --role reviewer --model opus  --blind
bash scripts/codex_turn.sh  <slug> --role reviewer-aggregator -m gpt-5.5
```

**5. 完整收敛循环 → `roundtable-goal`**

plan → execute → 平行盲审 → aggregate，按停止条件（BLOCKER==0）循环，带 budget / stall / scope 控制。

```bash
# 对 Cursor 说：
"用 roundtable-goal 的 quality 模式实现登录功能，预算 3 轮"
```

## Sub-skill 一览（5 个）

| Sub-skill | 用途 |
|-----------|------|
| `roundtable-setup` | 初始化 `models.json`，配置 API key，为项目生成 `AGENTS.md` / `CLAUDE.md` |
| `roundtable-plan` | Phase A：多家平行调研，各出 option matrix，不推荐。Phase B：aggregator 合并成可执行 `PLAN.md`。（取代旧版 roundtable-discuss） |
| `roundtable-review` | 跨厂商平行盲审 + aggregator 收尾，只产结构化 verdict，不动代码 |
| `roundtable-execute` | 单 executor 在主 worktree 实现 `PLAN.md` / `GOAL.md`，完成后强制 scope check。N 并行 race 见 `docs/advanced.md` |
| `roundtable-goal` | 单 executor + 平行盲审的收敛回路：plan → execute → review → aggregate，循环到 BLOCKER==0 |

## 安装

```bash
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
```

Cursor 会自动发现 `~/.cursor/skills/` 下的 skill。第一次使用时，对 Cursor 说"用 agent-roundtable 初始化配置"，`roundtable-setup` 会带你建 `models.json`、注入 API key、生成项目级的 `AGENTS.md` / `CLAUDE.md`。

## 设计原则

- **跨厂商盲审** — 平行 reviewer 必须来自不同 actor 家族，必须带 `--blind`。
- **完整审计** — 每次 turn 的 prompt、stdout、stderr、verdict.json 都落到 `.roundtable/threads/<slug>/history/`。
- **满血工具面** — 默认开放 Read / Write / Bash / WebSearch / WebFetch；reviewer 通过 `--permission-mode plan` 锁为只读；只屏蔽破坏性 git 操作。
- **凭证隔离** — API key 通过 `chmod 600` 本地文件传递，不进 git、不进 prompt、不进对话上下文。
- **上下文卫生** — 发现新规则的 turn 必须先更新 `AGENTS.md`（必要时 `CLAUDE.md`）和 `.planning/`，再 hand-off。

## 进一步阅读

- [`docs/research/MULTI_VENDOR_VALUE_2026-05-10.md`](docs/research/MULTI_VENDOR_VALUE_2026-05-10.md) — 12 个跨厂商价值维度的完整研究，含 Gap 分析与 CrewAI / AutoGen / LangGraph 对比
- [`docs/MODEL-CAPABILITY-GUIDE.md`](docs/MODEL-CAPABILITY-GUIDE.md) — 各 actor 能力对比、模型注册表说明、地缘风险分散指南
- [`docs/advanced.md`](docs/advanced.md) — N 并行 executor race、高级 dispatch 模式

## License

[MIT](LICENSE)
