# maibot-message-filter-plugin

MaiBot 的消息过滤插件，阻止或替换任何不想让 Bot 说出口的文字。

## 功能概览

- **阶段过滤**：每条规则可指定生效阶段。支持**两个处理阶段**的规则过滤：
  - 在模型返回完整响应后处理
  - 在消息即将发送前处理
- **两种动作**：
  - `拦截整条消息`
  - `替换命中文字`
- **正则规则**：`pattern` 支持 Python 正则表达式。
- **概率触发**：`probability` 为 `0~1`，命中规则后按概率执行动作。

## 安装

1. 将仓库克隆到 MaiBot 的 `plugins` 目录：

   ```powershell
   cd <maibot根目录>\plugins
   git clone https://github.com/HyperSharkawa/maibot-message-filter-plugin
   ```
2. 重启 MaiBot，确认启动日志中出现插件名 `message_filter_plugin`。

## 配置

### 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enable` | `bool` | 是否启用插件，默认 `true` |
| `rules` | `array<object>` | 规则列表，按顺序执行 |

### 规则字段（`rules[]`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pattern` | `string` | 正则表达式（必填），用于匹配消息内容的正则表达式 |
| `action` | `string` | `拦截整条消息` / `替换命中文字` |
| `stage` | `string` | `发送前处理` / `LLM响应后处理` |
| `replacement` | `string` | 替换文本（仅替换动作时使用） |
| `probability` | `number` | 命中后执行动作的概率（`0~1`），`1` 代表必定执行，`0.5` 代表 50% 概率 |
| `description` | `string` | 规则描述（仅用于备注） |

> ⚙️ 修改配置后需重启生效。插件自带了一些示例规则，可根据需要修改或新增规则。

## 执行过程

- 规则按配置顺序执行。
- 命中规则后先做概率判定；未通过概率则跳过该次触发。
- 执行相应的动作，进行文本替换/拦截。
- 任一规则触发 `拦截整条消息` 或替换后文本消息为空，则取消发送。


## 故障排查

- 规则不生效：
  - 检查 `enable = true`
  - 检查 `rules` 非空
  - 检查 `stage` 是否选对
  - 检查正则是否正确匹配目标文本，可以让AI帮你写正确的正则表达式。
- 日志出现 `正则错误`：说明 `pattern` 写的不对，请修复后重启。

