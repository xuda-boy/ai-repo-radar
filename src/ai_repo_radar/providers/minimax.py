from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from ai_repo_radar.config import MiniMaxConfig
from ai_repo_radar.models import EnhancementBatch, Recommendation
from ai_repo_radar.pipeline import EnhancementResult


class MiniMaxClient:
    def __init__(
        self,
        api_key: str | None,
        config: MiniMaxConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.config = config
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ai-repo-radar/0.1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.Client(
            timeout=config.timeout_seconds,
            headers=headers,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MiniMaxClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _clean_content(content: str) -> str:
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("MiniMax response does not contain a JSON object")
        return cleaned[start : end + 1]

    @staticmethod
    def _public_payload(
        recommendations: list[Recommendation],
        readmes: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "full_name": item.repository.full_name,
                "description": item.repository.description,
                "language": item.repository.language,
                "topics": item.repository.topics,
                "readme_excerpt": readmes.get(item.repository.full_name, ""),
            }
            for item in recommendations
        ]

    def _payload(
        self,
        recommendations: list[Recommendation],
        readmes: Mapping[str, str],
    ) -> dict[str, Any]:
        public_repositories = self._public_payload(recommendations, readmes)
        instruction = (
            "你是开源项目资料编辑。只根据输入的公开 GitHub 字段和 README 片段输出中文内容。"
            "不得猜测未给出的安装命令，不得评价用户兴趣，也不得改变项目排序。"
            "每条摘要必须说明该仓库独有的用途或能力，禁止多条摘要复用同一结尾或空泛套话；"
            "快速开始也必须针对该仓库，不能统一写成阅读 README。"
            "只返回一个 JSON 对象，结构为 {\"repositories\":[{\"full_name\":字符串,"
            "\"summary_zh\":4到120字中文摘要,\"quick_start\":2到90字快速开始}]}。"
            "仓库必须与输入一一对应，不要 Markdown 代码块，不要额外文字。"
        )
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"repositories": public_repositories},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            "reasoning_split": True,
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.9,
            "max_completion_tokens": self.config.max_completion_tokens,
        }

    @staticmethod
    def _category(response: httpx.Response) -> str:
        if response.status_code in {401, 403}:
            return "authentication"
        if response.status_code == 429:
            return "quota_or_rate_limit"
        if response.status_code >= 500:
            return "provider_unavailable"
        return "api_error"

    def enhance(
        self,
        recommendations: list[Recommendation],
        readmes: Mapping[str, str],
    ) -> EnhancementResult:
        if not self.api_key:
            return EnhancementResult(
                enhancements=[],
                error_category="missing_api_key",
                message="未配置 MiniMax API Key；AI 中文摘要暂不可用。",
            )
        payload = self._payload(recommendations, readmes)
        last_category = "network_error"
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.post(self.config.api_url, json=payload)
            except httpx.TimeoutException:
                last_category = "timeout"
                if attempt < self.config.max_retries:
                    self._sleep(min(8.0, 2.0**attempt))
                    continue
                break
            except httpx.NetworkError:
                last_category = "network_error"
                if attempt < self.config.max_retries:
                    self._sleep(min(8.0, 2.0**attempt))
                    continue
                break

            if response.status_code >= 400:
                last_category = self._category(response)
                if response.status_code >= 500 and attempt < self.config.max_retries:
                    self._sleep(min(8.0, 2.0**attempt))
                    continue
                return EnhancementResult(
                    enhancements=[],
                    error_category=last_category,
                    message="MiniMax 服务暂不可用；AI 中文摘要暂不可用。",
                )
            try:
                raw = response.json()
                if raw.get("input_sensitive") or raw.get("output_sensitive"):
                    return EnhancementResult(
                        enhancements=[],
                        error_category="content_safety",
                        message="MiniMax 内容安全检查未返回摘要；已保留规则结果。",
                    )
                base = raw.get("base_resp") or {}
                if base.get("status_code") not in {None, 0}:
                    return EnhancementResult(
                        enhancements=[],
                        error_category="provider_error",
                        message="MiniMax 返回业务错误；AI 中文摘要暂不可用。",
                    )
                content = raw["choices"][0]["message"]["content"]
                batch = EnhancementBatch.model_validate_json(self._clean_content(content))
                expected = {item.repository.full_name for item in recommendations}
                enhancements = [
                    item for item in batch.repositories if item.full_name in expected
                ]
                return EnhancementResult(enhancements=enhancements)
            except (KeyError, IndexError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                return EnhancementResult(
                    enhancements=[],
                    error_category="invalid_response",
                    message="MiniMax 响应结构无效；AI 中文摘要暂不可用。",
                )

        return EnhancementResult(
            enhancements=[],
            error_category=last_category,
            message="MiniMax 请求超时或网络不可用；AI 中文摘要暂不可用。",
        )
