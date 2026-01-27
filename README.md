# maibot-message-filter-plugin
MaiBot 的消息过滤插件，基于内置插件系统在消息发送阶段对内容做最后一次审查，阻止或替换任何不想让 Bot 说出口的文字。

## 功能
- 拦截 / 替换：在消息真正被发送前直接取消整条消息，或仅替换命中的片段。
- 正则规则：每条规则使用正则表达式匹配文本，可对不同场景编写精准策略。
- 概率控制：命中后可按 `0-1` 的概率决定是否执行动作。

## 安装
1. 将仓库克隆到麦麦的 `plugins` 目录：
   ```powershell
   cd <maibot 根目录>\plugins
   git clone https://github.com/HyperSharkawa/maibot-message-filter-plugin
   ```
2. 确认 `maibot-message-filter-plugin` 文件夹下存在 `plugin.py`、`config.toml`（启动后自动生成）等文件。
3. 重启麦麦，插件会在启动日志中以 `message_filter_plugin` 名称出现。

## 配置
插件配置位于 `plugins/maibot-message-filter-plugin/config.toml`，对应配置段为 `message_filter_plugin`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enable` | `bool` | 是否启用消息过滤，默认为 `true`。
| `rules` | `array` | 过滤规则列表，每条规则均为对象。空列表时不会执行任何过滤。
| `rules[].pattern` | `string` | **必填。** 用于匹配消息内容的正则表达式。
| `rules[].action` | `"拦截整条消息" \| "替换命中文字"` | 命中后的动作，默认拦截整条消息。
| `rules[].replacement` | `string` | 仅当动作为替换时有效，表示替换成的文本。
| `rules[].probability` | `float` | 触发动作的概率（0-1）。`1` 代表必定执行，`0.5` 代表 50% 概率。

> ⚙️ 修改配置后需重启生效。插件自带了一些示例规则，可根据需要修改或新增规则。

## 使用说明
- 插件在对每条即将发送的消息进行正则匹配。
- 若规则命中且通过概率判定：
  - 选择拦截时，消息不会发送，日志中可看到 `消息命中了拦截规则` 的告警。
  - 选择替换时，仅替换文本片段，其余消息段（如图片、表情）会被保留。
- 多条规则会按配置顺序依次匹配，可结合“拦截 + 替换”构建多层策略。

## 故障排查
- **规则未生效**：确认 `enable = true` 且 `rules` 非空，同时确保正则可匹配目标消息。
- **正则报错**：插件会在日志中以 `规则 '<pattern>' 正则错误` 进行提示，请修正表达式后重启。

