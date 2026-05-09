# 🤝 Agent Roundtable

<p align="center">
  <em>让 Codex CLI、Claude Code CLI 和 Cursor 子 Agent 围坐一桌，为你提供可审计的、跨厂商的多智能体协作。</em>
</p>

> 一个模型容易有盲点。多个**不同厂商**的 agent 接力 + 互查，能显著降低幻觉、catch 单模型漏掉的方法学问题。研究表明跨厂商盲审能避免 85% 的同源附和率。

---

## ✨ 核心特性 (Features)

- 🛡️ **打破模型盲点**：支持跨厂商（OpenAI vs Anthropic）平行盲审，避免单一模型的“回音壁”效应。
- 📝 **完整审计日志**：所有交互记录在 `THREAD.md` 中，每次调用的 prompt、输出和判决结果（JSON）均在本地持久化。
- 🔓 **满血 Agent 探索**：默认开放全工具面（WebSearch、Bash、文件读写），仅拦截破坏性 Git 操作。
- 🔒 **极致安全**：API Key 永远不入 Git 或聊天记录（通过 `chmod 600` 本地文件传递），每次高危 Dispatch 强制用户确认。
- 🧹 **上下文卫生**：强制 Agent 及时将新发现的架构规则沉淀到 `AGENTS.md`，防止长线任务跑偏。

---

## 🚀 快速开始 (Quick Start)

### 1. 安装
```bash
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
```
*(Cursor 会自动发现 `~/.cursor/skills/` 下的 skill)*

### 2. 初始化配置
在 Cursor 对话框中输入：
> 「用 /agent-roundtable 初始化配置」

Agent 会自动帮你生成 `models.json`。填入你的 API Key 后，回复「**应用配置**」。

### 3. 注入项目上下文（推荐）
为了让 Agent 满血启动，在你的项目根目录对 Cursor 说：
> 「用 agent-roundtable，dispatch 一个 subagent 给我项目造一份 AGENTS.md 和 CLAUDE.md」

---

## 💡 怎么用 (Usage)

你不需要手动执行任何脚本，直接用自然语言向 Cursor Agent 下达指令即可：

**场景 1：跨厂商平行 Review（防附和）**
> 「用 agent-roundtable 跑跨厂商 review，让 codex 和 claude 各自审一遍 `auth/login.py` 的安全性」

**场景 2：完整功能开发（全质量回路）**
> 「用 agent-roundtable 的 quality 模式，让 planner 先做方案，executor 实现，3 个 reviewer 平行审，最后 aggregator 收尾」

**场景 3：单轮快速检查**
> 「让 codex 跑一个 reviewer 检查我刚提交的 commit」

---

## 🎭 角色与协作模式 (Architecture)

### 6 种预设角色
| 角色 | 职责 | 权限 | 适用场景 |
|------|------|------|----------|
| **planner** | 拆解任务、输出方案 | 仅写 Thread | 复杂任务的先期规划 |
| **executor** | 修改源码、运行测试 | 读写项目 | 落实已确定的方案 |
| **reviewer** | 输出结构化 JSON 判决 | 只读 | 验证实现是否达成目标 |
| **devils-advocate** | 逆向 Review，专挑漏洞 | 只读 | 高风险决策前的对抗性审查 |
| **reviewer-aggregator**| 综合所有 Review，做出最终判决 | 只读 | 多 Reviewer 场景收尾 |
| **discussant** | 列出选项与权衡，不下结论 | 仅写 Thread | 架构设计阶段的开放讨论 |

### 协作模式 (Modes)
- **单轮 (Single)**：快速问答或单次 Review。
- **串行 (Sequential)**：`Planner → Executor → Reviewer` 经典流水线。
- **平行盲审 (Parallel Blind)**：多个 Reviewer 同时独立审查，互相不可见，最后由 Aggregator 裁决。
- **全质量回路 (Quality Loop)**：包含计划、执行、平行盲审、汇总的完整闭环，直至达成停止条件（0 Blocker，≤1 异议）。

---

## 📁 文件结构

- `SKILL.md`: Agent 读取的完整协议与规则。
- `models.example.json`: 模型目录模板（含 Benchmark 和内置模型）。
- `models.json`: 你的本地模型与 API 配置（Git 忽略）。
- `scripts/`: 调度与路由脚本（由 Agent 自动调用）。
- `roles/`: 各角色的 System Prompt 及 JSON Schema。
- `docs/`: 进阶指南与审计快照。

## 📄 License
[MIT](LICENSE)