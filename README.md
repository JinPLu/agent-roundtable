# Agent Roundtable

> 让 Codex CLI、Claude Code、Cursor 子 Agent 围坐同一张桌子，在共享的 on-disk 线程上轮流接力，提供可审计的跨厂商多智能体协作。

单模型容易有盲点。跨厂商盲审能显著降低幻觉与单模型的方法学漏洞——研究显示跨厂商独立分配可获得 ~99% 的有效分歧率，远高于"请你批判性思考"提示的 ~48% 基线（arXiv 2405.09935）。

## 设计原则

- **跨厂商盲审**：平行 reviewer 必须来自不同 actor 家族（OpenAI-compat vs Anthropic-compat），且必须带 `--blind`。
- **完整审计日志**：每次调用的 prompt、输出、`verdict.json` 都落盘到 `.roundtable/threads/<slug>/history/`。
- **满血工具面**：默认开放 Read / Write / Bash / WebSearch / WebFetch；reviewer 角色通过 `--permission-mode plan` 锁为只读；只屏蔽破坏性 git 操作。
- **凭证不入聊天**：API Key 通过本地 `chmod 600` 文件传递，不进 git、不进 prompt、不进对话上下文。
- **上下文卫生**：发现新规则的 turn 必须先更新 `AGENTS.md`（必要时 `CLAUDE.md`）和 `.planning/`，再 hand-off。

## 快速开始

### 1. 安装

```bash
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
```

Cursor 会自动发现 `~/.cursor/skills/` 下的 skill。

### 2. 初始化

在 Cursor 对话中说：

> 用 agent-roundtable 初始化配置

Agent 会跑 `roundtable-init` 子 skill，创建 `models.json`。打开该文件，为你要用的模型填入 `actor` / `cli_arg` / `endpoint.base_url` / `endpoint.api_key` 四个字段，然后回复"应用配置"。

### 3. 注入项目上下文

如果你的项目根目录还没有 `AGENTS.md` / `CLAUDE.md`，让 init 子 skill 帮你生成。这是"满血启动"的关键——agent CLI 启动时会自动加载这两个文件，省掉重复探索代码库的开销。

## 怎么用

直接用自然语言下达指令，Cursor Agent 会路由到对应的子 skill：

- **跨厂商 Review**：「用 agent-roundtable 跑跨厂商 review，让 codex 和 claude 各审一遍 `auth/login.py`」 → `roundtable-review`
- **完整功能开发**：「用 agent-roundtable 的 quality 模式实现 X 功能」 → `roundtable-develop`
- **单轮快速检查**：直接调用 `scripts/codex_turn.sh <slug> --role reviewer`

## 角色

| 角色 | 职责 | 权限 |
|------|------|------|
| `planner` | 拆解任务，输出 `artifacts/plan.md` | 写 thread |
| `executor` | 实现方案、跑测试、commit | 读写项目（屏蔽破坏性 git） |
| `reviewer` | 输出结构化 JSON 判决 | 只读 |
| `devils-advocate` | 对抗式 review，专挑漏洞 | 只读 |
| `reviewer-aggregator` | 多 reviewer 收尾，输出合并判决 | 只读 |
| `discussant` | 列选项与权衡，不下结论 | 写 thread |

## 文件结构

- `SKILL.md`：路由与全局硬规则。
- `skills/`：子 skill（`roundtable-init`、`roundtable-review`、`roundtable-develop`），按用户意图自动加载。
- `roles/`：各角色的 system prompt 与 `reviewer.schema.json`。
- `scripts/`：调度脚本（`codex_turn.sh`、`claude_turn.sh`、`backend.sh` 等）。
- `models.example.json`：模型注册表模板（含 benchmark 与示例条目）。
- `models.json`：你的本地模型与 API 配置（gitignored，chmod 600）。
- `docs/`：进阶用法、模型能力指南、历史审计快照。

## 进阶

- 模式与路由：`docs/advanced.md`
- 模型选型：`docs/MODEL-CAPABILITY-GUIDE.md`

## License

[MIT](LICENSE)
