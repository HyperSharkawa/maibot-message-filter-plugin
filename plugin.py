import random
import re
from typing import List, Tuple, Type, Optional, Dict

from maim_message import Seg

from src.common.logger import get_logger
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    EventType,
    MaiMessages,
    ConfigField,
    message_api,
    llm_api
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


async def _apply_filter_rules_to_text(
        rules: List[dict],
        text: str,
        chat_id: str,
        llm_check_settings: Optional[Dict[str, str | int]] = None
) -> Tuple[bool, bool, str, Optional[str]]:
    """
    对文本应用规则列表
    :param rules: 规则列表
    :param text: 待处理的文本
    :param chat_id: 消息流ID，仅用于日志记录，帮助定位是哪条消息触发了规则
    :param llm_check_settings: LLM判断设置，仅在规则中有使用LLM判断的规则时需要提供
    :return: (blocked, modified, final_text, hit_pattern) 是否被拦截、是否被修改、最终文本内容、命中的规则pattern（如果有）
    """
    current_text = text
    modified = False
    llm_check_needed = False
    hit_pattern: Optional[str] = None
    
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
                if probability < 1.0 and random.random() > probability:
                    logger.debug(f"[{chat_id}] 命中了规则 '{pattern}'，但因随机概率({probability})未触发动作。")
                    continue

                if action == "拦截整条消息":
                    logger.warning(f"[{chat_id}] 消息命中了拦截规则 '{pattern}'，已被拦截。")
                    return True, modified, current_text, pattern
                elif action == "替换命中文字":
                    new_text = re.sub(pattern, replacement, current_text)
                    if new_text != current_text:
                        logger.info(f"[{chat_id}] 命中了替换规则 '{pattern}'，内容已被替换。新的消息内容为: {new_text}")
                        current_text = new_text
                        modified = True
                elif action == "使用LLM判断是否拦截":
                    llm_check_needed = True
                    if hit_pattern is None:
                        hit_pattern = pattern
        except re.error as e:
            logger.error(f"规则 '{pattern}' 正则错误: {e}")
            continue
        except Exception as e:
            logger.error(f"规则 '{pattern}' 处理时发生错误: {e}")
            continue

    if llm_check_needed:
        if not llm_check_settings:
            logger.warning(f"[{chat_id}] 命中了LLM判断规则 '{hit_pattern}'，但LLM设置未配置，跳过LLM判断。")
            return False, modified, current_text, hit_pattern
        
        if not current_text.strip():
            if modified:
                logger.info(f"[{chat_id}] 消息命中了LLM判断规则 '{hit_pattern}'，但经过替换后的消息内容为空，跳过LLM判断。")
                return False, modified, current_text, hit_pattern
            else:
                logger.info(f"[{chat_id}] 消息命中了LLM判断规则 '{hit_pattern}'，但消息内容为空，跳过LLM判断。")
                return False, modified, current_text, hit_pattern

        should_send, reason = await _check_reply_with_llm(
            chat_id=chat_id,
            reply_text=current_text,
            prompt=llm_check_settings.get("prompt", ""),
            model_name=llm_check_settings.get("model", "utils"),
            context_count=llm_check_settings.get("context_count", 10),
        )
        if not should_send:
            logger.warning(f"[{chat_id}] 消息命中了LLM判断规则 '{hit_pattern}'，LLM判断结果为不发送，已被拦截。LLM判断原因: {reason}")
            return True, modified, current_text, hit_pattern
        logger.debug(f"[{chat_id}] 消息命中了LLM判断规则 '{hit_pattern}'，LLM判断结果为发送，已放行。")

    return False, modified, current_text, hit_pattern


async def _check_reply_with_llm(chat_id: str, reply_text: str, prompt: str, model_name: str, context_count: int) -> Tuple[bool, str]:
    """
    使用LLM判断是否应该发送这条回复

    Returns:
        Tuple[bool, str]: (是否应该发送, 原因)
    """

    if not chat_id:
        logger.warning("无法获取chat_id，跳过LLM判断")
        return True, "无法获取上下文"
    if not prompt:
        logger.warning("LLM判断提示词模板为空，跳过LLM判断")
        return True, "LLM判断提示词模板为空"
    available_models = llm_api.get_available_models()
    model_config = available_models.get(model_name)
    if not model_config:
        logger.warning(f"指定的LLM模型 '{model_name}' 不存在，跳过LLM判断")
        return True, f"指定的LLM模型 '{model_name}' 不存在"

    recent_messages = message_api.get_recent_messages(chat_id=chat_id, hours=1.0, limit=context_count)
    messages_text = message_api.build_readable_messages_to_str(recent_messages, replace_bot_name=True, timestamp_mode="relative")

    final_prompt = prompt.format(messages=messages_text, reply_text=reply_text)
    logger.debug(f"LLM判断提示词: {final_prompt}")

    success, response, _, _ = await llm_api.generate_with_model(prompt=final_prompt, model_config=model_config, request_type="plugin.llm_check")
    logger.debug(f"LLM调用结果: success={success}, response={response}")

    if not success:
        logger.warning(f"LLM判断调用失败: {response}")
        return True, f"LLM调用失败: {response}"

    response = response.strip()
    if response != "发送":
        reasoning = f"LLM判断结果: '{response}'，已拦截消息。"
        logger.info(reasoning)
        return False, response

    return True, response


class LLMResponseFilterEventHandler(BaseEventHandler):
    """LLM请求完成事件处理器 检测并拦截或替换LLM的响应内容消息"""
    event_type = EventType.AFTER_LLM
    handler_name = "llm_response_filter_event_handler"
    handler_description = "检测LLM响应，若命中用户设置的规则则进行相应的处理"
    intercept_message = True
    rules: Optional[List[dict]] = []
    llm_check_settings: Optional[Dict[str, str | int]] = {
        "model": "utils",
        "context_count": 10,
        "prompt": "",
    }

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, Optional[str], None, Optional[MaiMessages]]:
        """执行消息过滤逻辑"""

        rules: Optional[List[dict]] = LLMResponseFilterEventHandler.rules
        if not rules:
            return True, True, "无规则，跳过执行", None, message

        if not message or not message.llm_response_content:
            return True, True, "消息内容为空", None, message

        origin_text = message.llm_response_content
        current_text = origin_text

        blocked, modified, current_text, hit_pattern = await _apply_filter_rules_to_text(
            rules=rules,
            text=current_text,
            chat_id=message.stream_id,
            llm_check_settings=LLMResponseFilterEventHandler.llm_check_settings
        )
        if blocked:
            return True, False, f"命中拦截规则: {hit_pattern} 中止后续流程", None, None

        if not modified:
            return True, True, "LLM响应已放行", None, message
        current_text = current_text.strip()
        if not current_text:
            logger.info(f"[{message.stream_id}] 经过替换后的LLM响应内容为空，中止后续流程")
            return True, False, "经过替换后的LLM响应内容为空，中止后续流程", None, None
        message.modify_llm_response_content(current_text)
        logger.debug(f"[{message.stream_id}] LLM响应内容已更新,原内容: “{origin_text}” 新内容: “{current_text}”")

        return True, True, "已按规则替换部分LLM响应内容", None, message


class PreSendMessageFilterEventHandler(BaseEventHandler):
    """消息发送事件处理器 检测并拦截或替换bot发出的消息"""

    event_type = EventType.POST_SEND
    handler_name = "pre_send_message_filter_event_handler"
    handler_description = "检测bot要发出的每一条消息，若命中用户设置的规则则进行相应的处理"
    intercept_message = True
    rules: Optional[List[dict]] = []

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        """执行消息过滤逻辑"""
        rules: Optional[List[dict]] = PreSendMessageFilterEventHandler.rules
        if not rules:
            return True, True, "无规则，跳过执行", None, None

        if not message or not message.plain_text:
            return True, True, "消息内容为空", None, None

        message_segments = message.message_segments
        origin_text = "".join([seg.data for seg in message_segments if seg.type == "text"])
        current_text = origin_text

        blocked, modified, current_text, hit_pattern = await _apply_filter_rules_to_text(
            rules=rules,
            text=current_text,
            chat_id=message.stream_id
        )
        if blocked:
            return True, False, f"命中拦截规则: {hit_pattern} 中止后续流程", None, None

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
            return True, True, "已按规则替换部分消息内容", None, message

        # 若最终文本不为空
        if len(segments) == 1:
            # 单段消息直接替换内容
            segments[0].data = current_text
            message.modify_message_segments(segments)
            logger.debug(f"[{message.stream_id}] 消息内容已更新,原内容: “{origin_text}” 新内容: “{current_text}”")
            return True, True, "已按规则替换部分消息内容", None, message

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
        "message_filter_plugin": "基础设置",
        "llm_check": "LLM判断设置",
    }
    config_schema = {
        "message_filter_plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用消息过滤"),
            "pre_send_rules": ConfigField(
                type=list,
                item_type="object",
                item_fields={
                    "enabled": {
                        "type": "select",
                        "label": "是否启用该规则",
                        "choices": ["启用", "不启用"],
                        "default": "启用"
                    },
                    "pattern": {
                        "type": "string",
                        "label": "正则表达式",
                        "placeholder": "要被替换/拦截的内容，支持正则表达式"
                    },
                    "action": {
                        "type": "select",
                        "label": "动作",
                        "choices": ["拦截整条消息", "替换命中文字"],
                        "default": "拦截整条消息"
                    },
                    "replacement": {"type": "string", "label": "替换为", "placeholder": "仅在替换动作时有效"},
                    "probability": {
                        "type": "number",
                        "label": "当规则命中后进行动作的概率(0-1)。设为1代表永远触发",
                        "default": 1.0
                    },
                    "description": {
                        "type": "string",
                        "label": "规则描述",
                        "placeholder": "可选，对该规则的简短描述，仅便于查看，不会影响功能"
                    },
                },
                default=[
                    {
                        "enabled": "启用",
                        "pattern": "。$",
                        "action": "替换命中文字",
                        "replacement": "",
                        "probability": 1.0,
                        "description": "删除句末的句号"},
                ],
                description="发送前处理规则：会在一条消息被发送前处理(如果启用了回复分割，这里处理的是单独的一句句话)。拦截整条消息将直接取消发送；替换文字则只会修改命中的部分。当规则命中后会根据概率决定是否执行对应动作。"
            ),
            "after_llm_rules": ConfigField(
                type=list,
                item_type="object",
                item_fields={
                    "enabled": {
                        "type": "select",
                        "label": "是否启用该规则",
                        "choices": ["启用", "不启用"],
                        "default": "启用"
                    },
                    "pattern": {
                        "type": "string",
                        "label": "正则表达式",
                        "placeholder": "要被替换/拦截的内容，支持正则表达式"
                    },
                    "action": {
                        "type": "select",
                        "label": "动作",
                        "choices": ["拦截整条消息", "替换命中文字", "使用LLM判断是否拦截"],
                        "default": "拦截整条消息"
                    },
                    "replacement": {"type": "string", "label": "替换为",
                                    "placeholder": "仅在替换动作时有效。可以为空，留空相当于删掉命中部分的文字"},
                    "probability": {
                        "type": "number",
                        "label": "当规则命中后进行动作的概率(0-1)。设为1代表永远触发",
                        "default": 1.0
                    },
                    "description": {
                        "type": "string",
                        "label": "规则描述",
                        "placeholder": "可选，对该规则的简短描述，仅便于查看，不会影响功能"
                    },
                },
                default=[
                    {"enabled": "启用", "pattern": r"RESOURCE_EXHAUSTED", "action": "拦截整条消息",
                     "replacement": "", "probability": 1.0,
                     "description": "拦截部分API中转站会返回的错误消息"},
                    {"enabled": "启用", "pattern": "傻逼", "action": "替换命中文字", "replacement": "[filtered]",
                     "probability": 1.0,
                     "description": "替换不当用语"},
                    {"enabled": "启用", "pattern": r"\s*\[.+]\s*", "action": "替换命中文字", "replacement": "",
                     "probability": 1.0,
                     "description": "删除笨蛋回复模型自己伪造的[]括起来的动作，比如[回复xx的消息]、[戳一戳消息]、[贴表情消息]等"},
                    {"enabled": "启用", "pattern": r"<\|begin_of_box\|>", "action": "替换命中文字",
                     "replacement": "",
                     "probability": 1.0,
                     "description": "删除硅基流动的GLM-4.6V返回的标签"},
                    {"enabled": "启用", "pattern": r"<\|end_of_box\|>", "action": "替换命中文字",
                     "replacement": "",
                     "probability": 1.0,
                     "description": "删除硅基流动的GLM-4.6V返回的标签"},
                    {"enabled": "不启用",
                     "pattern": ".?",
                     "action": "使用LLM判断是否拦截",
                     "replacement": "",
                     "probability": 1.0,
                     "description": "“.?”将会匹配所有消息。如果你希望每一条消息都使用LLM判断是否发送，请启用。"}
                ],
                description="LLM响应后处理规则：会在LLM响应成功后处理回复模型返回的整段内容。拦截整条消息将直接取消发送；替换文字则只会修改命中的部分。当规则命中后会根据概率决定是否执行对应动作。"
            ),

        },
        "llm_check": {
            "model": ConfigField(
                type=str,
                choices=['lpmm_entity_extract', 'lpmm_rdf_build', 'planner', 'replyer', 'tool_use', 'utils', 'vlm'],
                default="utils",
                description="用于判断的LLM模型分组"
            ),
            "context_count": ConfigField(
                type=int,
                default=10,
                description="获取多少条最近的消息作为上下文供判断模型参考"
            ),
            "prompt": ConfigField(
                type=str,
                input_type="textarea",
                default="""你是一个消息发送判断助手。你的任务是判断一条回复是否应该发送。\n以下是最近的对话上下文：\n{messages}\n\n回复模型生成的回复：\n{reply_text}\n\n请判断这条回复是否应该发送。\n\n【必须拦截的情况】\n用户最后一条消息是新的话题或问题，但回复完全没有涉及这个新话题，而是完全无关的内容。\n例如：用户最后一条消息是"今天吃什么"，但回复是"在呢"（完全没回答吃什么的问题，只是回应了更早的"在吗"）\n\n【必须发送的情况】\n1.回复与用户最后一条消息的话题相关\n2.除非完全不相关，否则都发送\n3.无法确定时，默认发送\n\n如果应该发送，请回复"发送"两字，不要进行任何解释或添加其他多余的文字。\n如果应该拦截，请回复"不发送"并简短说明原因。""",
                description="LLM判断的提示词模板。使用{messages}表示上下文，{reply_text}表示回复内容"
            ),
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        components = []
        pre_send_rules: List[dict] = self.config.get("message_filter_plugin", {}).get("pre_send_rules", [])
        after_llm_rules: List[dict] = self.config.get("message_filter_plugin", {}).get("after_llm_rules", [])
        pre_send_rules = [r for r in pre_send_rules if r.get("enabled") == "启用"]
        after_llm_rules = [r for r in after_llm_rules if r.get("enabled") == "启用"]
        PreSendMessageFilterEventHandler.rules = pre_send_rules
        LLMResponseFilterEventHandler.rules = after_llm_rules

        llm_check_prompt = self.config.get("llm_check", {}).get("prompt", "")
        llm_check_model_name = self.config.get("llm_check", {}).get("model", "utils")
        llm_check_context_count = self.config.get("llm_check", {}).get("context_count", 10)
        LLMResponseFilterEventHandler.llm_check_settings["prompt"] = llm_check_prompt
        LLMResponseFilterEventHandler.llm_check_settings["model"] = llm_check_model_name
        LLMResponseFilterEventHandler.llm_check_settings["context_count"] = llm_check_context_count

        if self.config.get("message_filter_plugin", {}).get("enable", False):
            if pre_send_rules:
                components.append((PreSendMessageFilterEventHandler.get_handler_info(), PreSendMessageFilterEventHandler))
            if after_llm_rules:
                components.append((LLMResponseFilterEventHandler.get_handler_info(), LLMResponseFilterEventHandler))
        return components
