import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class AIClient:
    """OpenAI 协议兼容的 AI 客户端"""

    def __init__(self, base_url: str, api_key: str, model: str, proxy: str = "", extra_params: dict | None = None):
        kwargs = {
            "base_url": base_url,
            "api_key": api_key,
        }
        if proxy:
            kwargs["http_client"] = None  # TODO: 如需代理，用 httpx 配置
        self.client = AsyncOpenAI(**kwargs)
        self.model = model
        self.total_tokens_used = 0
        self.extra_params = extra_params or {}

    async def chat(
        self,
        system_prompt: str,
        user_content: str,
        images: list[str] | None = None,
        temperature: float = 0.4,
    ) -> str:
        """
        调用 LLM 获取文本回复。

        Args:
            system_prompt: 系统提示词
            user_content: 用户输入内容
            images: 图片路径列表（用于多模态，可选）
            temperature: 生成温度
        """
        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # 构建 user message
        if images:
            content_parts = [{"type": "text", "text": user_content}]
            for img_path in images:
                img_data = self._encode_image(img_path)
                if img_data:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_data}"}
                    })
            messages.append({"role": "user", "content": content_parts})
        else:
            messages.append({"role": "user", "content": user_content})

        try:
            # 构建请求参数
            request_params = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }

            # 处理额外参数
            if self.extra_params:
                # OpenAI 标准参数列表
                standard_params = {"temperature", "max_tokens", "top_p", "frequency_penalty",
                                   "presence_penalty", "stop", "stream", "user"}
                extra_body = {}
                for key, value in self.extra_params.items():
                    if key in standard_params:
                        request_params[key] = value
                    else:
                        # 非标准参数（如 enable_thinking）放入 extra_body
                        extra_body[key] = value
                if extra_body:
                    request_params["extra_body"] = extra_body

            response = await self.client.chat.completions.create(**request_params)
            # 记录 token 用量
            if response.usage:
                self.total_tokens_used += response.usage.total_tokens
                logger.debug(
                    f"Token usage: {response.usage.prompt_tokens} + "
                    f"{response.usage.completion_tokens} = {response.usage.total_tokens}"
                )

            message = response.choices[0].message
            content = message.content or ""

            # 打印思维链（CoT 模型如 DeepSeek-R1、Kimi-K2.5 等）
            reasoning_content = getattr(message, "reasoning_content", None)
            if reasoning_content:
                logger.info(f"[AI 思维链]\n{reasoning_content}\n[/AI 思维链]")

            return content

        except Exception as e:
            logger.error(f"AI 调用失败: {e}")
            raise

    def _encode_image(self, image_path: str) -> str | None:
        """将图片文件编码为 base64"""
        path = Path(image_path)
        if not path.exists():
            logger.warning(f"图片不存在: {image_path}")
            return None
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
