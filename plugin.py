import random
import re
from typing import List, Tuple, Type, Optional

from maim_message import Seg
from src.common.logger import get_logger
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    EventType,
    MaiMessages,
    ConfigField
)
from src.plugin_system.base.component_types import ComponentInfo

logger = get_logger("message_filter_plugin")


class MessageFilterEventHandler(BaseEventHandler):
    """消息发送事件处理器 检测并拦截bot发出的消息"""

    event_type = EventType.POST_SEND
    handler_name = "message_intercept_event_handler"
    handler_description = "检测bot要发出的每一条消息，若命中用户设置的规则则进行相应的处理"
    intercept_message = True

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        """执行消息过滤逻辑"""
        rules: Optional[List[dict]] = self.get_config("message_filter_plugin.rules")
        if not rules:
            return True, True, "无规则，跳过执行", None, None

        if not message or not message.plain_text:
            return True, True, "消息内容为空", None, None

        modified = False
        message_segments = message.message_segments
        origin_text = "".join([seg.data for seg in message_segments if seg.type == "text"])
        current_text = origin_text

        for rule in rules:
            pattern = rule.get("pattern")
            action = rule.get("action", "拦截整条消息")
            replacement = rule.get("replacement", "")
            probability = rule.get("probability", 1.0)

            if not pattern:
                continue

            try:
                if re.search(pattern, current_text):
                    # 概率判定
                    if random.random() > probability:
                        logger.debug(
                            f"[{message.stream_id}] 命中了规则 '{pattern}'，但因随机概率({probability})未触发动作。")
                        continue

                    if action == "拦截整条消息":
                        logger.warning(f"[{message.stream_id}] 消息命中了拦截规则 '{pattern}'，已被拦截。")
                        return True, False, f"命中拦截规则: {pattern}", None, None

                    elif action == "替换命中文字":
                        new_text = re.sub(pattern, replacement, current_text)
                        if new_text != current_text:
                            logger.info(
                                f"[{message.stream_id}] 命中了替换规则 '{pattern}'，内容已被替换。新的消息内容为: {new_text}")
                            current_text = new_text
                            modified = True
            except re.error as e:
                logger.error(f"规则 '{pattern}' 正则错误: {e}")
                continue

        if modified:
            segments = message.message_segments
            if len(message.message_segments) > 1:
                # 多段消息时只修改第一段文本，删除其他文本段,保留非文本段
                replaced = False
                for seg in segments:
                    if seg.type != "text":
                        continue
                    if not replaced:
                        seg.data = current_text
                        replaced = True
                        continue
                    segments.remove(seg)
            else:
                segments[0].data = current_text
            message.modify_message_segments(segments)
            logger.debug(f"[{message.stream_id}] 消息内容已更新,原内容: “{origin_text}” 新内容: “{current_text}”")
            return True, True, "已按规则替换部分内容", None, message

        return True, True, "已放行消息", None, None


# ===== 插件注册 =====


@register_plugin
class MessageFilterPlugin(BasePlugin):
    # 插件基本信息
    plugin_name: str = "message_filter_plugin"  # 内部标识符
    enable_plugin: bool = True
    dependencies: List[str] = []  # 插件依赖列表
    python_dependencies: List[str] = []  # Python包依赖列表
    config_file_name: str = "config.toml"  # 配置文件名
    config_section_descriptions = {
        "message_filter_plugin": "消息过滤设置",
    }
    config_schema = {
        "message_filter_plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用消息过滤"),
            "rules": ConfigField(
                type=list,
                item_type="object",
                item_fields={
                    "pattern": {"type": "string", "label": "正则表达式",
                                "placeholder": "要被替换/拦截的内容，支持正则表达式"},
                    "action": {
                        "type": "select",
                        "label": "动作",
                        "choices": ["拦截整条消息", "替换命中文字"],
                        "default": "拦截整条消息"
                    },
                    "replacement": {"type": "string", "label": "替换为", "placeholder": "仅在替换动作时有效"},
                    "probability": {"type": "number", "label": "当规则命中后进行动作的概率(0-1)。设为1代表永远触发",
                                    "default": 1.0}
                },
                default=[
                    {"pattern": "RESOURCE_EXHAUSTED", "action": "拦截整条消息", "replacement": "", "probability": 1.0},
                    {"pattern": "sk_[a-zA-Z0-9]{8}", "action": "替换命中文字", "replacement": "********",
                     "probability": 1.0},
                    {"pattern": "傻逼", "action": "替换命中文字", "replacement": "[filtered]", "probability": 1.0}
                ],
                description="配置过滤规则。拦截整条消息将直接取消发送；替换文字则只会修改命中的部分。当规则命中后会根据概率决定是否执行对应动作。"
            ),
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        components = []
        if self.config.get("message_filter_plugin", {}).get("enable", {}):
            components.append((MessageFilterEventHandler.get_handler_info(), MessageFilterEventHandler))
        return components
