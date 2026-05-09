# Agent Roundtable

让 **Codex CLI**、**Claude Code CLI**、**Cursor 子 agent** 三种 LLM 围着一份共享文档轮流发言、互相 review，给你一份完整可审计的多智能体协作日志。

> 一个模型容易有盲点（同厂商训练偏置、特定任务薄弱、漏验证）。多个**不同厂商**的 agent 接力 + 互查，能显著降低幻觉、catch 单模型漏掉的方法学问题。研究表明跨厂商盲审能避免 85% 的同源附和率（arXiv 2605.00914）。

```
   ┌─────────┐    ┌─────────┐    ┌──────────┐
   │  Codex  │    │ Claude  │    │  Cursor  │
   │   CLI   │    │   CLI   │    │ Subagent │
   └────┬────┘    └────┬────┘    └────┬─────┘
        │              │              │
        └──────────────┼──────────────┘
                       ▼
              ┌─────────────────┐
              │   THREAD.md     │  ← 唯一真值，append-only
              │  (5-part body)  │
              └─────────────────┘
```

---

## 这个 skill 解决什么问题

| 痛点 | 单 agent | Agent Roundtable |
|------|---------|------------------|
| 模型盲点 | 同厂商相同盲点 | 跨厂商互补 |
| 没有审计日志 | 散落聊天里 | 全部进 `THREAD.md` |
| 验证不严 | 容易"看起来对" | reviewer 必须出结构化 JSON 判决 |
| review 互相附和 | 同模型互验=回音壁 | `--blind` 模式独立判决 |
| 改了源码不知道哪个 agent 改的 | — | 每轮 `history/<actor>/<ts>/` 完整保留 |

适合场景：代码 review、复杂功能开发、研究/论文事实核查、协议合规审计。

---

## 安装与配置（10 分钟）

### 第 1 步：克隆

```bash
git clone https://github.com/JinPLu/agent-roundtable.git ~/.cursor/skills/agent-roundtable
```

Cursor 会自动发现 `~/.cursor/skills/` 下的 skill。

### 第 2 步：准备 API key

至少需要一个 LLM 的 API key。支持两类：

- **OpenAI 兼容**（OpenAI 官方 / Azure / 国内代理 / 本地 vLLM 等）→ 给 codex CLI 用
- **Anthropic 兼容**（Anthropic 官方 / DeepSeek anthropic-compat / Bedrock 等）→ 给 claude CLI 用

如果你用的是 **Cursor 子 agent**（在 Cursor IDE 里 Pro/Pro+/Ultra 订阅自带的模型），不需要 API key。

### 第 3 步：让 skill 给你建配置文件

在 Cursor 里告诉 agent：

> **「跑 agent-roundtable 的初始化」** 或 **「用 /agent-roundtable 配置一下」**

Cursor agent 会执行 `backend.sh init`，给你建一份 `models.json`（chmod 600，gitignored，永不入 git）。

### 第 4 步：填 4 个字段

打开 `~/.cursor/skills/agent-roundtable/models.json`，找你要用的模型，填这 4 个字段：

```json
"my-model-name": {
  "actor":   "codex",                                      // codex 或 claude
  "cli_arg": "gpt-5",                                      // CLI 调用时的模型名
  "endpoint": {
    "base_url": "https://api.openai.com/v1",               // 你的 API endpoint
    "api_key":  "sk-..."                                   // 你的 key
  }
}
```

然后把 `active.codex` 或 `active.claude` 设到这个模型 id 上。

### 第 5 步：让 skill 应用配置

回 Cursor 告诉 agent：「**done**」（或者「应用配置」）。

Cursor agent 会执行 `backend.sh apply`：把 endpoint 写进本地 `.codex_env.local` / `.claude_env.local`（chmod 600），并跑一个 1 行的健康检查 turn 验证 endpoint 通畅。

完成后跑 `backend.sh show` 应该看到 `✅ IMPORTED`。

> **API key 永远不会进聊天记录、不会上 GitHub**。skill 通过文件传 key，agent 只读 endpoint URL 和模型名做调度，从不读 key 本身。

### 第 6 步：为项目造 agent 上下文（每个项目做一次）

Agent CLI 启动时会自动加载项目根的上下文文件——没这些文件，agent 每轮要重新探索"项目是什么、源码在哪、规范是什么"，浪费 token + 容易瞎猜。**有了它们，agent 一上来就是满血状态。**

**两个文件名，不同工具读不同的**（这是关键，**不能只造一个**）：

| 文件 | 谁原生读取 |
|------|-----------|
| `AGENTS.md` | Codex CLI、Cursor、GitHub Copilot、Gemini CLI、25+ 其他 agent 工具（Linux Foundation 标准） |
| `CLAUDE.md` | Claude Code CLI（**不会**直接读 bare `AGENTS.md`） |

**Anthropic 官方推荐模式（二者非纯重复）：**

- **`AGENTS.md`** = 跨平台真值，写**所有 agent 都需要的**项目信息：build/test 命令、目录结构、规范、PR 规则、通用约束、常见陷阱。
- **`CLAUDE.md`** = 薄覆盖层（约 20–50 行），第一行 `@AGENTS.md` 导入跨平台内容，下方写 **Claude Code 专属**规则（plan 模式偏好、sub-agent 委派习惯、slash command 行为、anything that names a Claude Code feature）。

```markdown
# CLAUDE.md（薄覆盖层示例）
@AGENTS.md

## Claude Code 专属
- 默认用 plan 模式做 review-style 任务
- 写完文件后自动跑 pytest 验证
- 不要主动建 sub-agent；roundtable 协议外不要 dispatch 其他 agent
```

**怎么生成**：在 Cursor 里告诉 agent：

> **「用 agent-roundtable，dispatch 一个 cursor-claude-4.7-opus subagent 给我项目造 AGENTS.md，描述项目结构、关键文件、规范、常见陷阱。然后造一份薄 CLAUDE.md 用 `@AGENTS.md` 导入。」**

Cursor agent 会扫项目目录、读 `.planning/` / `README` / 关键源码后产出一份 ~120-200 行的 `AGENTS.md` + 一份 ~20-50 行的 `CLAUDE.md`。

**简化方案（项目无 Claude 专属规则时）**：用 symlink，单一真值：

```bash
cd /your/project
ln -s AGENTS.md CLAUDE.md       # AGENTS.md 是源，CLAUDE.md 跟随
```

> 缺点：失去添加 Claude 专属覆盖的能力。仅适用于跨平台规则就够用的简单项目。

> 项目重构/加新模块后，重新 dispatch 一次刷新 AGENTS.md。CLAUDE.md（如果是覆盖层）通常不用动。

---

## 怎么用

你不需要直接调脚本。在 Cursor 里直接对 agent 说话：

### 示例 1：让两个不同厂商的 agent 互相 review 一段代码

> 「用 agent-roundtable 跑跨厂商 review，让 codex 和 claude 各自审一遍 `auth/login.py` 的安全性」

Cursor agent 会：
1. 创建一个 thread（叫 `auth-login-review-XXX`）
2. 给你看一个 dispatch confirmation 框：模型选谁、用哪个 effort、估计花多少钱
3. 等你说 **「GO」** 或者你自己选别的模型
4. 跑 codex + claude 两个 reviewer 平行（各自 `--blind`）
5. 把两份 JSON verdict 给你

### 示例 2：让 agent 帮你做完整功能开发

> 「用 agent-roundtable 的 quality 模式，让 planner 先做方案，executor 实现，3 个 reviewer 平行审，最后 aggregator 收尾」

Cursor agent 会按 4 阶段流程跑（见下方 Mode 4），每阶段都会先问你确认。

### 示例 3：单轮快速 review

> 「让 codex 用 gpt-5.5 跑一个 reviewer 检查我刚提交的 commit」

最便宜最快，一个 agent 一轮搞定。

---

## 6 种角色

每个角色对应 `roles/<role>.system.md` 一份系统提示词。Cursor agent 会根据你的任务自动选角色，也可以你指定。

| 角色 | 干什么 | 写权限 | 适合 |
|------|--------|--------|------|
| **planner** | 拆任务、出实现方案 | 仅 thread 内 | 复杂任务前先出方案 |
| **executor** | 改源码、跑测试、提交 | 项目全部（沙箱内） | 实现已确定的方案 |
| **reviewer** | 投结构化 JSON 判决 | 只读 | 验证实现/方案是否达成 GOAL |
| **devils-advocate** | 逆向 reviewer，专挑漏洞 | 只读 | 高风险决策前的对抗审 |
| **reviewer-aggregator** | 看完所有 reviewer 后**选**最有理的判决（不是平均） | 只读 | 多 reviewer 收尾 |
| **discussant** | 列选项、提问，不下结论 | thread 内 | 设计阶段的开放讨论 |

> **共享规则**（`roles/_independence_rule.md`）：每个 agent 必须**独立读源文件**、跑命令验证。`THREAD.md` 是日志不是证据，**绝不能**只信前面 agent 的总结。

---

## 4 种协作模式

### Mode 1 — 单轮（最便宜）

```
GOAL ──▶ [agent] ──▶ THREAD.md
```

一个 agent 一轮干完。**适合**：快速 review、一次性问答、简单生成。

### Mode 2 — 串行链

```
GOAL ──▶ planner ──▶ executor ──▶ reviewer
            ↓           ↓           ↓
            └──────── THREAD.md ────┘
```

每轮读上一轮的输出做下一步。**适合**：明确的"先方案、后实现、再审计"开发流。

### Mode 3 — 平行 reviewer（跨厂商，反附和）

```
              ┌──▶ codex/reviewer (--blind)
              │
   executor ──┼──▶ claude/devils-advocate (--blind)
              │
              └──▶ aggregator ──▶ 选最有理的 verdict
```

2–3 个不同厂商 reviewer 同时跑，每个都 `--blind`（看不到其他人）。aggregator **选**而非综合，避免"和稀泥"。**适合**：高风险决策、关键 review。

### Mode 4 — 全质量回路（最贵但最稳）

```
Plan ──▶ Execute ──▶ Reviewer × N (含 1 个 devils-advocate, 全 blind)
                            │
                            ▼
                        Aggregate
                            │
   停止条件：≥1 通过 + 0 BLOCKER + ≤1 异议
```

4 阶段闭环。**适合**：关键功能、合规/安全决策、论文事实核查。

---

## 重要保证

- ✅ **API key 永不入聊天/git**：通过 `chmod 600` 文件传递，agent 只看 endpoint URL
- ✅ **完整审计**：每轮的 prompt、输出、stderr、verdict.json 全保存到 `history/<actor>/<ts>/`
- ✅ **可重放**：thread 在你项目内（`<project>/.roundtable/`），跟代码一起 commit/分享
- ✅ **agent 满血探索**：默认全工具开放（WebSearch、WebFetch、Bash、Read、Write），只屏蔽真正破坏性的 git 操作
- ✅ **每次 dispatch 你都有否决权**：Cursor agent 不会偷偷跑 turn，每次都会先问你确认
- ✅ **上下文卫生 (Context Hygiene)**：强制要求 agent 及时将新发现的架构规则或项目事实更新到 `AGENTS.md` / `CLAUDE.md` 和 `.planning/` 中，防止后续计划跑偏

---

## 文件结构

| 路径 | 是什么 |
|------|--------|
| `SKILL.md` | 完整协议——Cursor agent 读这个文件 |
| `models.example.json` | 模型目录模板（已含 benchmark 分数和 cursor 内置模型） |
| `models.json` | 你的工作副本（gitignored、chmod 600） |
| `scripts/` | 调度、路由、线程操作（agent 调用，你不需要直接跑） |
| `roles/*.system.md` | 6 个角色的系统提示词 |
| `roles/reviewer.schema.json` | reviewer JSON verdict 严格 schema |
| `docs/` | 进阶文档（脚本细节、模型能力指南、审计快照） |

## 进阶

完整协议、模型选择原则、dispatch 确认协议、quality mode 停止条件等见 [SKILL.md](SKILL.md)。

## License

[MIT](LICENSE)
