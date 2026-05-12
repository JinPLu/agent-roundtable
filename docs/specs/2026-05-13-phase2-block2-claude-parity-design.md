# Phase 2 块② · Claude CLI 深集成对齐 — 设计 spec

> 日期：2026-05-13
> 状态：design approved（brainstorming → spec），待 writing-plans skill 拆成 PLAN.md → 执行
> 上游：`agent-roundtable_hook_5_件套_ab4e457d.plan.md` §七 (二期预告) → 经 2026-05-12 brainstorming session refine
> 北极星：让三家 CLI（Codex / Claude Code / Cursor 内置 subagent）能互通互审，并把单位 turn 真金白银成本压到最低

---

## 0. 目的与背景

本 spec 只覆盖 Phase 2 **块②**：把 Codex 一期（CX1–CX5）那套机制——session resume / 真实 usage 抓取 / per-role 隔离——平移到 Claude 这一侧，并额外利用 Claude 官方内置的 `Explore` (Haiku) 子代理把"探索税"从主模型转嫁到便宜模型。

其余 9 个 Phase 2 主线（cc-switch 集成、installer、refine、observability、debt、cross-thread memory、epistemic labels、MCP 中台、adaptive routing）不在此 spec 内，由后续 brainstorming session 各自拆 spec。

**为什么先做这块**：在 2026-05-12 brainstorming 中估算，单 Claude executor turn 从 ~$1.27 降到 ~$0.13 量级（~90%），autopilot 15 轮端到端从 ~$19 降到 ~$1.7（~91%）——所有候选块里**单点最大省钱**。

## 1. Scope（明确包含 / 不包含）

### 包含三个子项

| ID | 子项 | 改动定性 |
|----|------|----------|
| a | `extract_claude_usage.py` 修准 | 修正现有行为 |
| b | 显式 `--resume <session_id>` 取代粗粒度 `--continue` | 修正现有行为 |
| e | Haiku `Explore` 接入 reviewer/planner/researcher 类 role | 新增结构性优化 |

### 不包含（推 Phase 3 或更后）

- c · scope_watcher Claude 版（tail stream-json 监 file write）
- d · per-role `.claude/settings.json` 多档接（reviewer / executor 不同 permission set）
- f · `--bare` reviewer 稳态化 + stream-json → json 模式切换条件
- 其他 9 个 Phase 2 主线（不属本块）

### 不动

- 一期 hook 脚本（H1–H5）
- Codex 一侧（`codex_turn.sh` / `extract_codex_usage.py` / scope_watcher.py / codex profile）
- `.roundtable/threads/<slug>/` 数据格式与既有字段
- 用户机器上的 `~/.cursor/hooks.json` / `~/.claude/settings.json` / `~/.codex/config.toml`
- `.budget_ledger.jsonl` schema（仅修复 real_usd 的算法，不动字段名）

## 2. 北极星指标（成功定义）

> **以 proxy 后台的真实出账作为唯一信任源。改代码前后各跑一次同一个固定任务，看账单。**

- **第一次 A/B**（改前 baseline vs 修车 PR (a+b) 之后）：Claude 侧账单**降幅 ≥ 50%** 视为修车成功
- **第二次 A/B**（修车 PR 之后 vs 新装 PR (e) 也合并之后）：Claude 侧账单**再降幅 ≥ 10%**（在已经压低的基数上）视为新装成功
- 任何一次 A/B 不达标 → 当次 PR 单独回滚（参 §6）

不再使用以下作为收尾门槛（一次 brainstorming 中讨论过但被替代）：
- ~~`.budget_ledger.jsonl` real_usd 与 console 偏差 ≤ ±5%~~（已被"账单本身就是事实"取代）
- ~~`cached_input_ratio ≥ 80%`~~（同上）
- ~~autopilot 全程降 ≥ 80%~~（A/B 任务改为单 feature，autopilot 不是 baseline）

## 3. A/B 测试方法

### 3.1 固定测试任务

在 `agent-roundtable` 仓库里给 `scripts/lib/check_budget.py` 加一个新 `--summary` 模式：

> 跑 `python3 scripts/lib/check_budget.py <thread_dir> --summary`，输出过去 10 笔 turn 的总花费、按 role 分组小计、平均 `cached_input_ratio`。

这一道题是**真小 feature**，约 50–80 行 Python 改动 + 1 个测试，executor + reviewer 各跑一次。

### 3.2 阵容固定

- executor actor：**Claude Opus 4.7**（具体 dated slug 由 `models.json` 决定）
- reviewer actor：**Claude Opus 4.7**（同上）
- 不混 Codex / Cursor — 本块只测 Claude 侧账单变化

### 3.3 跑几次

每个比较点跑 **1 次**。门槛拉宽到 ≥ 50%（修车）/ ≥ 10%（新装在修车基础上）以吸收单次随机波动。

A/B 总成本估算：baseline ~$2 + 修车后 ~$0.4 + 新装后 ~$0.2 ≈ **$2.6**。

### 3.4 账单来源

- 用户当前 Claude 侧走 **proxy**（cc-switch-sync 同步过来的 provider，具体 host 由 `~/.codex/auth.json` / `~/.claude/.credentials.json` 决定）
- 实测账单**从 proxy 后台读**（proxy dashboard 一般实时）
- 修车 PR 完工后，本仓库的 `.budget_ledger.jsonl` 中 `real_usd` 也会与账单一致（这本身就是修车 PR 的正确性证据）

## 4. 设计段 1：修车 PR（a + b）

### 4.1 改 `scripts/lib/extract_claude_usage.py`

**当前缺陷**：固定使用 sonnet ballpark 价（input $3 / cache_read $0.30 / output $15），不读 `last.json.model`，不区分 `cache_creation_input_tokens` vs `cache_read_input_tokens`。

**修复目标**：
- 读 `last.json` 中的 `model` 字段（如 `claude-opus-4-7-20251029`）
- 查 `pricing_snapshot.json`（一期已存在）找该 model 的真实 per-1M-token 价
- 四档分别计算 USD：
  - `cache_creation_input_tokens × per_1m_input × 1.25 / 1e6`
  - `cache_read_input_tokens × per_1m_input × 0.10 / 1e6`
  - `(input_tokens - cache_creation - cache_read) × per_1m_input / 1e6`
  - `output_tokens × per_1m_output / 1e6`
- 写入 `usage.json`：`real_usd`、`cached_input_ratio`、`model`、`source: "claude-last-json"`

**stream-json bug 防护**：one-time 验证 `last.json.usage` **是否**受 [anthropics/claude-code#6805](https://github.com/anthropics/claude-code/issues/6805) 影响。如果是，则改从 stream-json 末事件取 `usage`，并打开 `--output-format json` 作为 fallback。

**测试**：`scripts/lib/test_extract_claude_usage.py` 加 6 个 case 覆盖：cache_creation only / cache_read only / mixed / unknown model（pricing snapshot 缺）/ stream-json bug 防护 / usage 缺失。

### 4.2 改 `scripts/claude_turn.sh`

**当前**：通过 `_should_resume` 决定是否在 `_args` 中加 `--continue`。`--continue` 接当前 cwd 下最近 session，**并发不安全**。

**修复目标**：
- 一次正常 turn 结束后，从 stream-json 输出抓 `session_id`（来自最早的 `system.init` 事件的 `session_id` 字段）
- 写 marker：`<thread_dir>/.claude_session.<role>.<model>.json`，含字段：`{session_id, ts, model, git_sha, actor}`（与 Codex marker 同形）
- 下一次同 role + 同 model + 同 thread 的 turn 启动时：
  1. `_should_resume` 走一期既有规则（reviewer / aggregator / devils-advocate / `--blind` 永远 fresh）
  2. marker 有效（24h 内 + `git rev-parse HEAD` 未变 + model 字段一致）→ 用 `claude -p --resume <session_id> ...` + addendum-only delta task
  3. 否则 → fresh，**不再退回 `--continue`**

**autopilot 模式**：H5 续轮场景下 `--force-resume` 跳过 TTL 检查（一期 CX5 已设计），照样生效。

**测试**：`scripts/lib/test_resume_policy.py` 加 4 个 case 覆盖：marker 缺失 / marker 过期 / model 不一致 / git_sha 变。

### 4.3 PR commit message

```
feat(claude): faithful usage accounting + explicit session resume

a. extract_claude_usage.py: model-aware pricing, separate cache_creation /
   cache_read / uncached / output token classes via pricing_snapshot.json.
b. claude_turn.sh: capture session_id from stream-json system.init; resume
   via `--resume <sid>` (parity with Codex CX1) instead of coarse --continue.
```

## 5. 设计段 2：新装 PR（e）

### 5.1 改 4 个 role system prompt

涉及文件：

- `roles/planner.system.md`
- `roles/reviewer.system.md`（兼覆盖 `reviewer-aggregator.system.md`、`devils-advocate.system.md` 的同源段落）
- `roles/researcher.system.md`
- `roles/researcher-deep.system.md`

每个文件中插入一段（实际措辞用 prompt 工艺斟酌）：

> **Before doing any work on this turn, call `Task(subagent_type="Explore", thoroughness="medium", prompt=...)` to identify the files in this repository that are relevant to your task. The Explore subagent runs on Claude Haiku (read-only, fast) and is dramatically cheaper than reading files yourself. Only after Explore returns its summary, read the specific files it flagged — do not pre-emptively read more files than Explore recommended.**

注意：

- **不给 `executor.system.md` / `executor-fast.system.md` 加**——executor 主要在写文件不在读，且 executor 任务往往已经被 PLAN.md 钉死了 path。
- **不给 `discussant.system.md` 加**——讨论性 turn 通常 token 量小，Explore overhead 反而占大头。

### 5.2 thoroughness 选 "medium"

Anthropic 官方 [Explore 三档](https://gist.github.com/johnlindquist/d22c70fd70660b4f6fb4d0b05d0792d2)：

- quick (10–30s)：极简列文件
- **medium (30–60s)**：列文件 + 简要摘要 ✓ 选这档作默认
- very thorough (60–120s)：详细解读

可被 role 自己根据任务难度覆写（在 Explore 调用时显式传 `thoroughness="quick"` 或 `"very thorough"`）。

### 5.3 风险控制

- **风险**：Haiku 看错重点 → Opus 之后又读一遍 → token 算两次 → 反而更贵
- **检测**：A/B 第二次跑完，看账单是否反弹
- **回滚**：单独 revert 这一笔 PR，保留修车 PR
- **不护城河**：新装失败不影响修车 60–80% 那段降幅成绩

### 5.4 PR commit message

```
feat(roles): inject Haiku Explore as repo-context proxy for read-heavy roles

planner / reviewer / reviewer-aggregator / devils-advocate / researcher /
researcher-deep system prompts now require a Task(Explore) call before
the main task, shifting ~30–50% of "exploration tokens" from Opus pricing
to Haiku pricing (~10× cheaper).

Executor and discussant roles unchanged (Explore overhead > savings for
write-heavy / short-turn workloads).
```

## 6. 设计段 3：失败回滚

### 6.1 修车 PR 失败

**症状**：A/B 第一次跑完，Claude 侧账单**降幅 < 50%**。

**排查**（按可能性高到低）：

1. `pricing_snapshot.json` 缺少 Opus 4.7 dated slug 的 entry → `python3 scripts/refresh_pricing_snapshot.py` 重新抓
2. proxy 出账口径与 Anthropic console 不一致 → 改去 console 验
3. baseline 首跑是 cache_creation 价（无热缓存）→ 测前先 warm up 一次再正式测
4. stream-json bug 实际波及 last.json → 切 `--output-format json` 模式

**回滚动作**：`git revert <修车 PR sha>`。`.budget_ledger.jsonl` 老条目无 `real_usd` 字段时仍可用 `est_usd`，向后兼容（一期 CX2 已铺好）。

### 6.2 新装 PR 失败

**症状**：A/B 第二次跑完，相对修车后 baseline，账单**反而上升** 或 **降幅 < 10%**。

**排查**：

1. Haiku 漏看 → 调高 thoroughness 到 "very thorough" 重跑
2. 任务太小（test feature 本身就 < 10 文件） → 换更大测试任务（参 §3.1）
3. Role prompt 写得不够"硬"，模型选择性忽略 → 加更强烈措辞

**回滚动作**：`git revert <新装 PR sha>`。Role prompts 回到修车后状态。

### 6.3 不会失败的承诺

- 不动 hook、不动 Codex 一侧、不动用户机器配置 → 失败不连带其他系统
- 两个 PR 独立 → 任一回滚不影响另一

## 7. Self-review

按 brainstorming skill §"Spec Self-Review" 自检：

| 项 | 结果 |
|----|------|
| 占位符（TBD / TODO / 不完整段）扫描 | ✅ 无 |
| 内部一致性（架构 vs 功能描述匹配） | ✅ §4 / §5 改动列表与 §6 回滚一一对应 |
| Scope 检查（是否仍可一次实现） | ✅ 两个 PR、~4 个文件改动 + 1 个 spec、一次 implementation plan 可承载 |
| 含糊检查（能不能被歧义解读） | ⚠️ §4.1 "stream-json bug 实际是否波及 last.json" 仍是 one-time 验证需要在 implementation 阶段先做；已在 §6.1 排查项 #4 明示 fallback。其他段无歧义 |

## 8. 引用

- 上游 plan：`agent-roundtable_hook_5_件套_ab4e457d.plan.md`
- 一期 CX1 / CX2 资料：`docs/research/AUTOPILOT_RESUME_SYNERGY.md`
- Claude Code 官方 headless 文档：<https://code.claude.com/docs/en/headless>
- Claude Code Task / Explore subagent：<https://gist.github.com/johnlindquist/d22c70fd70660b4f6fb4d0b05d0792d2>
- stream-json usage 重复 bug：<https://github.com/anthropics/claude-code/issues/6805>
- Anthropic 缓存价格规则：1× input 价 = uncached / 1.25× = cache_creation / 0.1× = cache_read

## 9. 下一步

1. 用户 review 本 spec → 提建议 / 通过
2. 通过后调 `writing-plans` skill，由它把本 spec 拆成 PLAN.md（修车 + 新装两阶段，每阶段含执行步骤、验证命令、回滚命令）
3. PLAN.md → `roundtable-execute` 派单 executor 实现 → reviewer 复核 → 跑 A/B → 提交
