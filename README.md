# Agent Roundtable

Agent Roundtable 是一套面向 Cursor 的多智能体协作 skill，让 **Codex CLI**、**Claude Code** 和 **Cursor 子 agent** 围着一份共享的 on-disk 线程轮流接力，给你一份完整可审计的跨厂商协作日志。

## 它怎么工作

任何对编码 agent 有点经验的人都知道：单模型容易踩盲点——同一厂商训练的模型，往往在同一类问题上沉默。Agent Roundtable 解决这一点的方式是把 turn 落在 `THREAD.md` 里、把判决落在结构化 JSON 里，然后强制让不同厂商的 agent **盲审**对方的工作。

实证研究在 18 个跨六大家族的 LLM 上度量了"行为纠缠"（DW-BEI / CIG），发现纠缠程度与裁判精度退化之间的相关性 ρ ≈ 0.64–0.71；据此做去纠缠重加权的跨厂商裁判组合，比同厂商多数投票多带 +4.5% 准确率（arXiv 2604.07650）。把这件事做对，需要的不是更聪明的 prompt，而是更严的协议。

skill 启动时不会直接写代码。它先识别你的意图，路由到合适的子 skill：你要 review、要开发、还是先做配置；然后按子 skill 的协议，dispatch 一组合适厂商和角色的 turn，每一轮都先给你 dispatch 确认块、跑完后把审计落盘。

## 安装

```bash
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
```

Cursor 会自动发现 `~/.cursor/skills/` 下的 skill。第一次使用时，对 Cursor 说"用 agent-roundtable 初始化配置"，`roundtable-setup` 会带你建 `models.json`、注入 API key、生成项目级的 `AGENTS.md` / `CLAUDE.md`。

## 怎么用

直接用自然语言告诉 Cursor 你的意图，agent 会自动路由到对应子 skill：

- "用 agent-roundtable 初始化配置" → `roundtable-setup`
- "用 agent-roundtable 让多模型平铺设计选项，比如 Redis vs Postgres" → `roundtable-discuss`
- "用 agent-roundtable 跑跨厂商 review，让 codex 和 claude 各审一遍 `auth/login.py`" → `roundtable-review`
- "用 agent-roundtable 让多模型给我提候选实现，再挑最好的" → `roundtable-execute`
- "用 agent-roundtable 的 quality 模式实现登录功能" → `roundtable-goal`

每一次 dispatch agent 都会先给你看确认块（thread / role / actor / model / 估价），等你说 GO 才真正发动。你随时可以否决或换模型。

## skill 库

按从轻到重的承诺度排列：

- **agent-roundtable** — 路由器与全局硬规则（dispatch 确认、上下文卫生、独立验证、跨厂商盲审、最小工具禁用）。
- **roundtable-setup** — 初始化 `models.json`、配置 API key、为项目生成 `AGENTS.md` / `CLAUDE.md`。
- **roundtable-discuss** — 跨厂商平行讨论：N 个不同家族的 discussant 各出一份 option matrix，再单 actor 合并成 `artifacts/options.md`，**不**给推荐，由你拍板。
- **roundtable-review** — 跨厂商平行盲审 + aggregator 收尾，只产判决，不动代码。
- **roundtable-execute** — N 个不同厂商的 executor 在隔离 worktree 上各做同一个任务，aggregator 选出最佳单一候选分支，败者保留作 forensic。
- **roundtable-goal** — 单 executor + 平行盲审的收敛回路：plan → execute → 平行盲审 → aggregate，按停止条件循环到 BLOCKER==0。

## 设计原则

- **跨厂商盲审** — 平行 reviewer 必须来自不同 actor 家族，必须带 `--blind`。
- **完整审计** — 每次 turn 的 prompt、stdout、stderr、verdict.json 都落到 `.roundtable/threads/<slug>/history/`。
- **满血工具面** — 默认开放 Read / Write / Bash / WebSearch / WebFetch；reviewer 通过 `--permission-mode plan` 锁为只读；只屏蔽破坏性 git 操作。
- **凭证隔离** — API key 通过 `chmod 600` 本地文件传递，不进 git、不进 prompt、不进对话上下文。
- **上下文卫生** — 发现新规则的 turn 必须先更新 `AGENTS.md`（必要时 `CLAUDE.md`）和 `.planning/`，再 hand-off。

## 文件结构

- `SKILL.md` — 路由与全局硬规则
- `skills/` — 子 skill
- `roles/` — 各角色 system prompt 与 `reviewer.schema.json`
- `scripts/` — 调度脚本（`codex_turn.sh`、`claude_turn.sh`、`backend.sh` 等）
- `models.example.json` — 模型注册表模板
- `models.json` — 你的本地配置（gitignored，chmod 600）
- `docs/` — 进阶用法、模型能力指南、审计快照

## License

[MIT](LICENSE)
