# Agent Roundtable

让 **Codex CLI**、**Claude Code CLI**、**Cursor 子 agent** 三类 actor 围绕一份共享的 `THREAD.md` 轮流发言，产生可审计、可回放的协作日志。

```
   ┌─────────┐    ┌─────────┐    ┌──────────┐
   │  Codex  │    │ Claude  │    │  Cursor  │
   │   CLI   │    │   CLI   │    │ Subagent │
   └────┬────┘    └────┬────┘    └────┬─────┘
        │              │              │
        └──────────────┼──────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   THREAD.md     │  ← 唯一真值，append-only
              │  (5-part body)  │
              └─────────────────┘
```

每轮（turn）按固定 5 段格式追加：**Read** / **Did** / **Verification** / **Open questions** / **Hand-off**。

---

## 角色（roles/）

每个 role 对应 `roles/<role>.system.md` 一份系统提示词，决定 agent 的工作目标、写权限、产物形式。

| 角色 | 干什么 | 写权限 | 必须产出 |
|------|--------|--------|---------|
| **planner** | 拆任务、出方案 → `artifacts/plan.md` | 仅 thread 内 | 计划文件 |
| **executor** | 实现计划、改源码、跑测试 | 项目全部（受沙箱保护） | 改动 + 验证 |
| **reviewer** | 对实现/方案投结构化判决 | 只读（`plan` 模式） | JSON verdict（内联在 **Verification** 里） |
| **devils-advocate** | 逆向 reviewer，专挑漏洞，必须 `--blind` | 只读 | 同上，立场对抗 |
| **reviewer-aggregator** | 看完所有 reviewer 后**选**一个最有理的 verdict（不是综合） | 只读 | 选定的 verdict + 异议记录 |
| **discussant** | 讨论选项、提疑问、不下结论 | thread 内 | 进入 `OPEN_QUESTIONS.md` |

> **共享规则**（`roles/_independence_rule.md`）：每个 agent 必须独立读源文件、跑命令验证。`THREAD.md` 是日志不是证据，**不能**只信前面的 agent。

---

## 四种协作模式

### Mode 1 — 单轮（最便宜）

```
GOAL.md ──▶ [agent] ──▶ THREAD.md
```

一次对话，一个 agent 干完。适合：快速 review、一次性生成、简单讨论。

```bash
codex_turn.sh my-thread --role discussant -m gpt-5.5 --task "..."
```

### Mode 2 — 串行链（planner → executor → reviewer）

```
GOAL.md ──▶ planner ──▶ executor ──▶ reviewer
                ↓           ↓           ↓
              THREAD.md  ←───────────────┘
```

每一轮读上一轮的输出做下一步。适合：明确的"先方案后实现"功能开发。

### Mode 3 — 平行 reviewer（跨厂商，反 sycophancy）

```
              ┌──▶ codex/reviewer (--blind)
              │
executor ─────┼──▶ claude/devils-advocate (--blind)
              │
              └──▶ aggregator ──▶ 选最有理的 verdict
```

2–3 个不同厂商的 reviewer 同时跑，每个都 `--blind`（看不到其他人的 verdict）。研究表明同厂商 reviewer 互看会有 85% 盲从率（arXiv 2605.00914），跨厂商 + 盲审能避免。

### Mode 4 — 全质量回路（4 阶段，最贵）

```
Plan ──▶ Execute ──▶ [Reviewer × N (blind)] ──▶ Aggregate
                                  ↓
                       devils-advocate 必含其中
                                  ↓
              停止条件：≥1 通过且 0 BLOCKER, ≤1 异议
```

适合关键决策。详见 `SKILL.md § Quality mode`。

---

## 快速开始

```bash
# 安装
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
SKILL=~/.cursor/skills/agent-roundtable

# 一次性配置：填模型 endpoint
$SKILL/scripts/backend.sh init                    # 拷模板
# 编辑 $SKILL/models.json，每个模型填 actor / cli_arg / base_url / api_key
$SKILL/scripts/backend.sh apply                   # 写 .env.local（chmod 600）

# 进项目根目录
cd /path/to/your/project

# 创线程（自动落在 ./.roundtable/threads/<slug>/）
$SKILL/scripts/new_thread.sh my-review "审计 auth 模块"
# 编辑 .roundtable/threads/my-review/GOAL.md

# 调起一轮
$SKILL/scripts/codex_turn.sh my-review --role planner -m gpt-5.5 --task "..."
```

`ROUNDTABLE_PROJECT_ROOT` 自动取 caller 的 `git rev-parse --show-toplevel`。线程就在你项目里。

---

## 接口（5 个 flag 封顶）

```
codex_turn.sh / claude_turn.sh <slug> --role ROLE [-m MODEL] [--effort LEVEL] [--task TEXT|--task-file FILE] [--blind]
```

- `--role`: 上面六个之一
- `-m`: `models.json` 里的别名
- `--effort`: `low | medium | high`
- `--task` 或 `--task-file`: 本轮指令
- `--blind`: 平行 reviewer 必带

其他（sandbox、permission-mode、timeout 等）按 role 自动选最优默认。

---

## 文件结构

| 路径 | 作用 |
|------|------|
| `SKILL.md` | 完整协议（Cursor 加载这个） |
| `models.example.json` | 模型目录模板（含 benchmark、价格） |
| `models.json` | 用户工作副本（gitignored，chmod 600） |
| `scripts/` | 调度、路由、线程操作 |
| `roles/*.system.md` | 每个角色的系统提示词 |
| `roles/reviewer.schema.json` | reviewer JSON verdict 严格 schema |
| `docs/` | 进阶文档（脚本分析、模型能力指南） |

## 协议细节

完整规则、模型选择原则、dispatch 确认协议见 [SKILL.md](SKILL.md)。

## License

[MIT](LICENSE)
