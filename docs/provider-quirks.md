# Provider Quirks

> Reference for `roundtable-setup`. When filling `cli_arg` in `models.json`, the choice depends on whether your `endpoint.base_url` is an official vendor or a proxy.

The CLIs (`codex` / `claude`) accept short model aliases — `"opus"`, `"sonnet"`, `"gpt-5"` — and silently resolve them to a current dated slug (e.g. `claude-opus-4-5-20250929`) before sending the API request. **Official vendors** (`api.anthropic.com`, `api.openai.com`) accept those resolved slugs. **Proxies** (`claude-api.org`, `cialloapi.cn`, DeepSeek-shim, OpenRouter, etc.) do **not** do alias resolution — they reject any model id they don't recognise verbatim, returning 502 / 503 with bodies like `"No available accounts"` (per [claude-api.org FAQ §503](https://doc.claude-api.org/faq)).

This produces a setup-time footgun: the user copies an example with `cli_arg: "opus"` and `base_url: "https://api.anthropic.com"`, then later flips `base_url` to a proxy without realising `cli_arg` has to flip too. The `apply` static check now catches the most common combinations of this:

| `base_url` host | Disallowed `cli_arg` (will be rejected) | Use instead |
|---|---|---|
| `claude-api.org` | `opus`, `sonnet`, `haiku` (and any non-dated haiku) | `claude-opus-4-7`, `claude-sonnet-4-6`, **`claude-haiku-4-5-20251001`** (haiku requires the date suffix on this proxy; verify against the [channel doc](https://doc.claude-api.org/channels) before adding new models) |
| `cialloapi.cn` | `gpt-5`, `gpt-4`, `o1`, `o3` (no version suffix) | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, etc. |
| `*.deepseek.com/anthropic` | `opus`, `sonnet`, `haiku` | the upstream id, e.g. `deepseek-v4-pro[1m]` |
| `openrouter.ai/api/v1` | any short alias | the OpenRouter-namespaced id, e.g. `anthropic/claude-opus-4` |

If you're using a proxy not on this list, **always** consult the proxy's accepted-model doc and use the exact id. The smoke test (step 2c above) catches everything else.
