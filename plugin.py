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


def _remove_text_segments(segments: List['Seg']) -> List['Seg']:
    """返回一个新列表，删除所有 type == 'text' 的段落"""
    return [s for s in segments if s.type != "text"]


def _replace_first_text_segment(segments: List['Seg'], new_text: str) -> List['Seg']:
    """把第一个 text 段替换为 new_text，删除后续所有 text 段，保留非 text 段顺序不变。"""
    result = []
    replaced = False
    for s in segments:
        if s.type != "text":
            result.append(s)
        else:
            if not replaced:
                s.data = new_text
                result.append(s)
                replaced = True
            # else: 跳过后续的 text 段
    return result


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

        if not modified:
            return True, True, "已放行消息", None, None

        segments: List[Seg] = list(message.message_segments)
        text_stripped = current_text.strip()

        # 若最终文本为空
        if not text_stripped:
            if len(segments) == 1:
                logger.info(f"[{message.stream_id}] 消息内容为空，已取消发送。")
                return True, False, "消息内容为空，已取消发送", None, None

            # 多段消息：删除所有 text 段，保留非文本段
            segments = _remove_text_segments(segments)
            if len(segments) == 0 or all(s.type == "reply" for s in segments):
                logger.info(f"[{message.stream_id}] 消息内容为空，已取消发送。")
                return True, False, "消息内容为空，已取消发送。", None, None

            # 若删除文本段后仍有其他非 reply 的段，则发送该消息
            message.modify_message_segments(segments)
            return True, True, "已按规则替换部分内容", None, message

        # 若最终文本不为空
        if len(segments) == 1:
            # 单段消息直接替换内容
            segments[0].data = current_text
            message.modify_message_segments(segments)
            logger.debug(f"[{message.stream_id}] 消息内容已更新,原内容: “{origin_text}” 新内容: “{current_text}”")
            return True, True, "已按规则替换部分内容", None, message

        # 替换第一个 text 段为 current_text，删除后续 text 段，保留所有非 text 段
        segments = _replace_first_text_segment(segments, current_text)
        message.modify_message_segments(segments)
        logger.debug(f"[{message.stream_id}] 消息内容已更新,原内容: “{origin_text}” 新内容: “{current_text}”")
        return True, True, "已按规则替换部分内容", None, message


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
                                    "default": 1.0},
                    "description": {"type": "string", "label": "规则描述", "placeholder": "可选，对该规则的简短描述，仅便于查看，不会影响功能"},
                },
                default=[
                    {"pattern": "RESOURCE_EXHAUSTED", "action": "拦截整条消息", "replacement": "", "probability": 1.0,
                     "description": "拦截部分API中转站会返回的错误消息"},
                    {"pattern": "傻逼", "action": "替换命中文字", "replacement": "[filtered]", "probability": 1.0,
                     "description": "替换不当用语"},
                    {"pattern": "。$", "action": "替换命中文字", "replacement": "", "probability": 1.0,
                     "description": "删除句末的句号"},
                    {"pattern": "\[回复.+]\s*", "action": "替换命中文字", "replacement": "", "probability": 1.0,
                     "description": "删除笨蛋模型返回的回复引用"}
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
