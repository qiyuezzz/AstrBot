import base64
import aiohttp
import json
import random
import asyncio
import astrbot.core.message.components as Comp
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.io import download_image_by_url
from astrbot.core.db import BaseDatabase
from astrbot.api.provider import Provider, Personality
from astrbot import logger
from astrbot.core.provider.func_tool_manager import FuncCall
from typing import List
from ..register import register_provider_adapter
from astrbot.core.provider.entities import LLMResponse


class SimpleGoogleGenAIClient:
    def __init__(self, api_key: str, api_base: str, timeout: int = 120) -> None:
        self.api_key = api_key
        if api_base.endswith("/"):
            self.api_base = api_base[:-1]
        else:
            self.api_base = api_base
        self.client = aiohttp.ClientSession(trust_env=True)
        self.timeout = timeout

    async def models_list(self) -> List[str]:
        request_url = f"{self.api_base}/v1beta/models?key={self.api_key}"
        async with self.client.get(request_url, timeout=self.timeout) as resp:
            response = await resp.json()

            models = []
            for model in response["models"]:
                if "generateContent" in model["supportedGenerationMethods"]:
                    models.append(model["name"].replace("models/", ""))
            return models

    async def generate_content(
        self,
        contents: List[dict],
        model: str = "gemini-1.5-flash",
        system_instruction: str = "",
        tools: dict = None,
        modalities: List[str] = ["Text"],
        safety_settings: List[dict] = [],
    ):
        payload = {}
        if system_instruction:
            payload["system_instruction"] = {"parts": {"text": system_instruction}}
        if tools:
            payload["tools"] = [tools]
        payload["contents"] = contents
        payload["generationConfig"] = {
            "responseModalities": modalities,
        }
        payload["safetySettings"] = [
            {"category": s["category"], "threshold": s["threshold"]}
            for s in safety_settings
        ]
        logger.debug(f"payload: {payload}")
        request_url = (
            f"{self.api_base}/v1beta/models/{model}:generateContent?key={self.api_key}"
        )
        async with self.client.post(
            request_url, json=payload, timeout=self.timeout
        ) as resp:
            if "application/json" in resp.headers.get("Content-Type"):
                try:
                    response = await resp.json()
                except Exception as e:
                    text = await resp.text()
                    logger.error(f"Gemini 返回了非 json 数据: {text}")
                    raise e
                return response
            else:
                text = await resp.text()
                logger.error(f"Gemini 返回了非 json 数据: {text}")
                raise Exception("Gemini 返回了非 json 数据： ")

    async def stream_generate_content(
        self,
        contents: List[dict],
        model: str = "gemini-1.5-flash",
        system_instruction: str = "",
        tools: dict = None,
        modalities: List[str] = ["Text"],
        safety_settings: List[dict] = [],
    ):
        payload = {}
        if system_instruction:
            payload["system_instruction"] = {"parts": {"text": system_instruction}}
        if tools:
            payload["tools"] = [tools]
        payload["contents"] = contents
        payload["generationConfig"] = {
            "responseModalities": modalities,
            "stream": True,
        }
        payload["safetySettings"] = [
            {"category": s["category"], "threshold": s["threshold"]}
            for s in safety_settings
        ]
        logger.debug(f"payload: {payload}")
        request_url = (
            f"{self.api_base}/v1beta/models/{model}:streamGenerateContent?key={self.api_key}"
        )
        async with self.client.post(
            request_url, json=payload, timeout=self.timeout
        ) as resp:
            async for line in resp.content:
                if line:
                    yield line

@register_provider_adapter(
    "googlegenai_chat_completion", "Google Gemini Chat Completion 提供商适配器"
)
class ProviderGoogleGenAI(Provider):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
        db_helper: BaseDatabase,
        persistant_history=True,
        default_persona: Personality = None,
    ) -> None:
        super().__init__(
            provider_config,
            provider_settings,
            persistant_history,
            db_helper,
            default_persona,
        )
        self.chosen_api_key = None
        self.api_keys: List = provider_config.get("key", [])
        self.chosen_api_key = self.api_keys[0] if len(self.api_keys) > 0 else None
        self.timeout = provider_config.get("timeout", 180)
        if isinstance(self.timeout, str):
            self.timeout = int(self.timeout)
        self.client = SimpleGoogleGenAIClient(
            api_key=self.chosen_api_key,
            api_base=provider_config.get("api_base", None),
            timeout=self.timeout,
        )
        self.set_model(provider_config["model_config"]["model"])

        safety_mapping = {
            "harassment": "HARM_CATEGORY_HARASSMENT",
            "hate_speech": "HARM_CATEGORY_HATE_SPEECH",
            "sexually_explicit": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "dangerous_content": "HARM_CATEGORY_DANGEROUS_CONTENT",
        }

        self.safety_settings = []
        user_safety_config = self.provider_config.get("gm_safety_settings", {})
        for config_key, harm_category in safety_mapping.items():
            if threshold := user_safety_config.get(config_key):
                self.safety_settings.append(
                    {"category": harm_category, "threshold": threshold}
                )

    async def get_models(self):
        return await self.client.models_list()

    async def _query(self, payloads: dict, tools: FuncCall) -> LLMResponse:
        tool = None
        if tools:
            tool = tools.get_func_desc_google_genai_style()
            if not tool:
                tool = None

        system_instruction = ""
        for message in payloads["messages"]:
            if message["role"] == "system":
                system_instruction = message["content"]
                break

        google_genai_conversation = []
        for message in payloads["messages"]:
            if message["role"] == "user":
                if isinstance(message["content"], str):
                    if not message["content"]:
                        message["content"] = ""

                    google_genai_conversation.append(
                        {"role": "user", "parts": [{"text": message["content"]}]}
                    )
                elif isinstance(message["content"], list):
                    # images
                    parts = []
                    for part in message["content"]:
                        if part["type"] == "text":
                            if not part["text"]:
                                part["text"] = ""
                            parts.append({"text": part["text"]})
                        elif part["type"] == "image_url":
                            parts.append(
                                {
                                    "inline_data": {
                                        "mime_type": "image/jpeg",
                                        "data": part["image_url"]["url"].replace(
                                            "data:image/jpeg;base64,", ""
                                        ),  # base64
                                    }
                                }
                            )
                    google_genai_conversation.append({"role": "user", "parts": parts})

            elif message["role"] == "assistant":
                if "content" in message:
                    if not message["content"]:
                        message["content"] = ""
                    google_genai_conversation.append(
                        {"role": "model", "parts": [{"text": message["content"]}]}
                    )
                elif "tool_calls" in message:
                    # tool calls in the last turn
                    parts = []
                    for tool_call in message["tool_calls"]:
                        parts.append(
                            {
                                "functionCall": {
                                    "name": tool_call["function"]["name"],
                                    "args": json.loads(
                                        tool_call["function"]["arguments"]
                                    ),
                                }
                            }
                        )
                    google_genai_conversation.append({"role": "model", "parts": parts})
            elif message["role"] == "tool":
                parts = []
                parts.append(
                    {
                        "functionResponse": {
                            "name": message["tool_call_id"],
                            "response": {
                                "name": message["tool_call_id"],
                                "content": message["content"],
                            },
                        }
                    }
                )
                google_genai_conversation.append({"role": "user", "parts": parts})

        logger.debug(f"google_genai_conversation: {google_genai_conversation}")

        modalites = ["Text"]
        if self.provider_config.get("gm_resp_image_modal", False):
            modalites.append("Image")

        loop = True
        while loop:
            loop = False
            result = await self.client.generate_content(
                contents=google_genai_conversation,
                model=self.get_model(),
                system_instruction=system_instruction,
                tools=tool,
                modalities=modalites,
                safety_settings=self.safety_settings,
            )
            logger.debug(f"result: {result}")

            # Developer instruction is not enabled for models/gemini-2.0-flash-exp
            if "Developer instruction is not enabled" in str(result):
                logger.warning(
                    f"{self.get_model()} 不支持 system prompt, 已自动去除, 将会影响人格设置。"
                )
                system_instruction = ""
                loop = True

            elif "Function calling is not enabled" in str(result):
                logger.warning(
                    f"{self.get_model()} 不支持函数调用，已自动去除，不影响使用。"
                )
                tool = None
                loop = True

            elif "Multi-modal output is not supported" in str(result):
                logger.warning(
                    f"{self.get_model()} 不支持多模态输出，降级为文本模态重新请求。"
                )
                modalites = ["Text"]
                loop = True

            elif "candidates" not in result:
                raise Exception("Gemini 返回异常结果: " + str(result))

        candidates = result["candidates"][0]["content"]["parts"]
        llm_response = LLMResponse("assistant")
        chain = []
        for candidate in candidates:
            if "text" in candidate:
                chain.append(Comp.Plain(candidate["text"]))
            elif "functionCall" in candidate:
                llm_response.role = "tool"
                llm_response.tools_call_args.append(candidate["functionCall"]["args"])
                llm_response.tools_call_name.append(candidate["functionCall"]["name"])
                llm_response.tools_call_ids.append(
                    candidate["functionCall"]["name"]
                )  # 没有 tool id
            elif "inlineData" in candidate:
                mime_type: str = candidate["inlineData"]["mimeType"]
                if mime_type.startswith("image/"):
                    chain.append(Comp.Image.fromBase64(candidate["inlineData"]["data"]))

        llm_response.result_chain = MessageChain(chain=chain)
        return llm_response

    async def text_chat(
        self,
        prompt: str,
        session_id: str = None,
        image_urls: List[str] = None,
        func_tool: FuncCall = None,
        contexts=[],
        system_prompt=None,
        tool_calls_result=None,
        **kwargs,
    ) -> LLMResponse:
        new_record = await self.assemble_context(prompt, image_urls)
        context_query = []
        context_query = [*contexts, new_record]
        if system_prompt:
            context_query.insert(0, {"role": "system", "content": system_prompt})

        for part in context_query:
            if "_no_save" in part:
                del part["_no_save"]

        # tool calls result
        if tool_calls_result:
            context_query.extend(tool_calls_result.to_openai_messages())

        model_config = self.provider_config.get("model_config", {})
        model_config["model"] = self.get_model()

        payloads = {"messages": context_query, **model_config}
        llm_response = None

        retry = 10
        keys = self.api_keys.copy()
        chosen_key = random.choice(keys)

        for i in range(retry):
            try:
                self.client.api_key = chosen_key
                llm_response = await self._query(payloads, func_tool)
                break
            except Exception as e:
                if "429" in str(e) or "API key not valid" in str(e):
                    keys.remove(chosen_key)
                    if len(keys) > 0:
                        chosen_key = random.choice(keys)
                        logger.info(
                            f"检测到 Key 异常({str(e)})，正在尝试更换 API Key 重试... 当前 Key: {chosen_key[:12]}..."
                        )
                        await asyncio.sleep(1)
                        continue
                    else:
                        logger.error(
                            f"检测到 Key 异常({str(e)})，且已没有可用的 Key。 当前 Key: {chosen_key[:12]}..."
                        )
                        raise Exception("达到了 Gemini 速率限制, 请稍后再试...")
                else:
                    logger.error(
                        f"发生了错误(gemini_source)。Provider 配置如下: {self.provider_config}"
                    )
                    raise e

        return llm_response

    async def text_chat_stream(
        self,
        prompt,
        session_id=None,
        image_urls=...,
        func_tool=None,
        contexts=...,
        system_prompt=None,
        tool_calls_result=None,
        **kwargs,
    ):
        # raise NotImplementedError("This method is not implemented yet.")
        # 调用 text_chat 模拟流式
        llm_response = await self.text_chat(
            prompt=prompt,
            session_id=session_id,
            image_urls=image_urls,
            func_tool=func_tool,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
        )
        llm_response.is_chunk = True
        yield llm_response
        llm_response.is_chunk = False
        yield llm_response

    def get_current_key(self) -> str:
        return self.client.api_key

    def get_keys(self) -> List[str]:
        return self.api_keys

    def set_key(self, key):
        self.client.api_key = key

    async def assemble_context(self, text: str, image_urls: List[str] = None):
        """
        组装上下文。
        """
        if image_urls:
            user_content = {"role": "user", "content": [{"type": "text", "text": text}]}
            for image_url in image_urls:
                if image_url.startswith("http"):
                    image_path = await download_image_by_url(image_url)
                    image_data = await self.encode_image_bs64(image_path)
                elif image_url.startswith("file:///"):
                    image_path = image_url.replace("file:///", "")
                    image_data = await self.encode_image_bs64(image_path)
                else:
                    image_data = await self.encode_image_bs64(image_url)
                if not image_data:
                    logger.warning(f"图片 {image_url} 得到的结果为空，将忽略。")
                    continue
                user_content["content"].append(
                    {"type": "image_url", "image_url": {"url": image_data}}
                )
            return user_content
        else:
            return {"role": "user", "content": text}

    async def encode_image_bs64(self, image_url: str) -> str:
        """
        将图片转换为 base64
        """
        if image_url.startswith("base64://"):
            return image_url.replace("base64://", "data:image/jpeg;base64,")
        with open(image_url, "rb") as f:
            image_bs64 = base64.b64encode(f.read()).decode("utf-8")
            return "data:image/jpeg;base64," + image_bs64
        return ""

    async def terminate(self):
        await self.client.client.close()
        logger.info("Google GenAI 适配器已终止。")
