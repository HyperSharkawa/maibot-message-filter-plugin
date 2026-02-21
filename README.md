# maibot-message-filter-plugin

MaiBot 的消息过滤插件，阻止或替换任何不想让 Bot 说出口的文字。支持使用正则表达式自定义过滤规则，对匹配命中的消息可选择拦截/替换/LLM判定是否要发送三种处理方式。

## 功能概览

- **阶段过滤**：按处理时机拆分为两个规则列表：
  - `after_llm_rules`：在模型返回完整响应后处理
  - `pre_send_rules`：在消息即将发送前处理
- **三种动作**：
  - `拦截整条消息`
  - `替换命中文字`
  - `使用LLM判断是否拦截`
- **正则规则**：`pattern` 支持 Python 正则表达式。
- **概率触发**：`probability` 为 `0~1`，命中规则后按概率执行动作。
- **可开关规则**：每条规则可通过 `enabled` 单独启用/禁用。

## 安装

1. 将仓库克隆到 MaiBot 的 `plugins` 目录：

   ```powershell
   cd <maibot根目录>\plugins
   git clone https://github.com/HyperSharkawa/maibot-message-filter-plugin
   ```
2. 重启 MaiBot，确认启动日志中出现插件名 `message_filter_plugin`。

## 配置

- `message_filter_plugin`：基础过滤规则
- `llm_check`：LLM 判断参数（供 `使用LLM判断是否拦截` 动作使用）

### `message_filter_plugin` 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enable` | `bool` | 是否启用插件，默认 `true` |
| `pre_send_rules` | `array<object>` | 发送前处理规则列表，按顺序执行 |
| `after_llm_rules` | `array<object>` | LLM响应后处理规则列表，按顺序执行 |

### 规则字段（`pre_send_rules[]` / `after_llm_rules[]`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enabled` | `string` | `启用` / `不启用`，用于控制该条规则是否生效 |
| `pattern` | `string` | 正则表达式（必填），用于匹配消息内容的正则表达式 |
| `action` | `string` | `拦截整条消息` / `替换命中文字` / `使用LLM判断是否拦截`（仅 `after_llm_rules` 可用） |
| `replacement` | `string` | 替换文本（仅替换动作时使用） |
| `probability` | `number` | 命中后执行动作的概率（`0~1`），`1` 代表必定执行，`0.5` 代表 50% 概率 |
| `description` | `string` | 规则描述（仅用于备注） |

### `llm_check` 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `model` | `string` | 用于判断的 LLM 模型分组，默认 `utils` |
| `context_count` | `int` | 提供给判断模型的最近消息条数，默认 `10` |
| `prompt` | `string` | 判断提示词模板，支持 `{messages}` 与 `{reply_text}` 占位符 |

> ⚙️ 修改配置后需重启生效。插件自带了一些示例规则，可根据需要修改或新增规则。

## 执行过程

- 规则按配置顺序执行。
- 命中规则后先做概率判定；未通过概率则跳过该次触发。
- 执行相应动作：替换 / 拦截 /在命中 LLM 动作时调用一次 LLM 判断。
- 任一规则触发 `拦截整条消息` 、 替换后文本消息为空或LLM判断为不发送，则取消发送。

### LLM 判断动作说明

- 仅当命中 `使用LLM判断是否拦截` 的规则时触发。
- 一个消息可命中多条 LLM 规则，但只会进行一次 LLM 调用。
- 若 LLM 返回不是精确的 `发送` 两个字，则视为不发送并拦截。请注意写合适的提示词。
- 请注意 Token 消耗！

## 故障排查

- 规则不生效：
  - 检查 `enable = true`
  - 检查 `pre_send_rules` / `after_llm_rules` 是否为空
  - 检查规则 `enabled` 是否为 `启用`
  - 检查规则是否放在正确的列表中
  - 检查正则是否正确匹配目标文本，可以让AI帮你写正确的正则表达式
- 日志出现 `正则错误`：说明 `pattern` 写的不对，请修复后重启
- LLM 判断未触发：
  - 查看日志报错获取更多信息