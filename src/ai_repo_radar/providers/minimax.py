from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from ai_repo_radar.config import MiniMaxConfig
from ai_repo_radar.models import Recommendation, RepositoryEnhancement
from ai_repo_radar.pipeline import EnhancementResult

logger = logging.getLogger(__name__)
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


@dataclass(frozen=True)
class _ParsedEnhancements:
    enhancements: list[RepositoryEnhancement]
    missing_names: list[str]
    issue: str | None
    finish_reason: str | None
    request_id: str | None


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
            "User-Agent": "ai-repo-radar/0.2.3",
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
        return cleaned.strip()

    @classmethod
    def _json_payload(cls, content: str) -> dict[str, Any]:
        cleaned = cls._clean_content(content)
        decoder = json.JSONDecoder()
        list_fallback: list[Any] | None = None
        for index, character in enumerate(cleaned):
            if character not in "[{":
                continue
            try:
                candidate, _end = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and isinstance(candidate.get("repositories"), list):
                return candidate
            if isinstance(candidate, list) and list_fallback is None:
                list_fallback = candidate
        if list_fallback is not None:
            return {"repositories": list_fallback}
        raise ValueError("json_payload_missing")

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") not in {
                    None,
                    "text",
                    "output_text",
                }:
                    continue
                value = part.get("text", part.get("content"))
                if isinstance(value, str):
                    parts.append(value)
            if parts:
                return "".join(parts)
        raise ValueError("content_missing")

    @classmethod
    def _parse_response(
        cls,
        raw: Any,
        expected_names: list[str],
    ) -> _ParsedEnhancements:
        if not isinstance(raw, dict):
            return _ParsedEnhancements([], expected_names, "response_envelope", None, None)
        request_id = raw.get("id") if isinstance(raw.get("id"), str) else None
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return _ParsedEnhancements(
                [], expected_names, "choices_missing", None, request_id
            )
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            finish_reason = None
        message = choice.get("message")
        if not isinstance(message, dict):
            return _ParsedEnhancements(
                [], expected_names, "message_missing", finish_reason, request_id
            )
        try:
            content = cls._content_text(message.get("content"))
            payload = cls._json_payload(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            issue = (
                "output_truncated"
                if finish_reason in {"length", "max_tokens"}
                else "json_payload"
            )
            return _ParsedEnhancements([], expected_names, issue, finish_reason, request_id)

        accepted: dict[str, RepositoryEnhancement] = {}
        invalid_items = 0
        expected = set(expected_names)
        for item_raw in payload["repositories"]:
            try:
                item = RepositoryEnhancement.model_validate(item_raw)
            except (TypeError, ValueError, ValidationError):
                invalid_items += 1
                continue
            if item.full_name not in expected or item.full_name in accepted:
                continue
            summary = item.summary_zh.strip()
            quick_start = item.quick_start.strip()
            if not _CJK_PATTERN.search(summary) or not _CJK_PATTERN.search(quick_start):
                invalid_items += 1
                continue
            accepted[item.full_name] = item.model_copy(
                update={"summary_zh": summary, "quick_start": quick_start}
            )

        missing_names = [name for name in expected_names if name not in accepted]
        issue = None
        if missing_names:
            if finish_reason in {"length", "max_tokens"}:
                issue = "output_truncated"
            elif invalid_items:
                issue = "invalid_items"
            else:
                issue = "repositories_missing"
        return _ParsedEnhancements(
            [accepted[name] for name in expected_names if name in accepted],
            missing_names,
            issue,
            finish_reason,
            request_id,
        )

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
        *,
        retry: bool = False,
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
        if retry:
            instruction += (
                "这是格式校验后的自动重试：必须补齐全部输入仓库，字段名和层级必须完全一致，"
                "summary_zh 与 quick_start 都必须包含中文。"
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
            "temperature": 0.1 if retry else 0.2,
            "top_p": 0.8 if retry else 0.9,
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

    @staticmethod
    def _ordered_enhancements(
        recommendations: list[Recommendation],
        completed: Mapping[str, RepositoryEnhancement],
    ) -> list[RepositoryEnhancement]:
        return [
            completed[item.repository.full_name]
            for item in recommendations
            if item.repository.full_name in completed
        ]

    @staticmethod
    def _invalid_message(issue: str | None, retries: int, *, partial: bool) -> str:
        issue_label = {
            "choices_missing": "缺少 choices 字段",
            "invalid_items": "字段或中文内容校验失败",
            "json_payload": "JSON 内容无效",
            "message_missing": "缺少 message 字段",
            "output_truncated": "输出截断",
            "repositories_missing": "未完整返回全部项目",
            "response_envelope": "响应外层结构无效",
        }.get(issue, "响应结构无效")
        retry_text = f"，已自动重试 {retries} 次" if retries else ""
        availability = "部分项目的 AI 中文摘要暂不可用" if partial else "AI 中文摘要暂不可用"
        return f"MiniMax {issue_label}{retry_text}；{availability}。"

    def _failure_result(
        self,
        recommendations: list[Recommendation],
        completed: Mapping[str, RepositoryEnhancement],
        *,
        category: str,
        message: str,
    ) -> EnhancementResult:
        return EnhancementResult(
            enhancements=self._ordered_enhancements(recommendations, completed),
            error_category=category,
            message=message,
        )

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
        if not recommendations:
            return EnhancementResult(enhancements=[])

        pending = list(recommendations)
        completed: dict[str, RepositoryEnhancement] = {}
        last_category = "network_error"
        last_issue: str | None = None
        split_invalid_batches = False
        for attempt in range(self.config.max_retries + 1):
            if not pending:
                break
            batch_size = len(pending)
            if attempt and split_invalid_batches:
                batch_size = max(1, math.ceil(len(pending) / (2**attempt)))
            batches = [pending[index : index + batch_size] for index in range(0, len(pending), batch_size)]
            retry_pending: list[Recommendation] = []
            pass_had_invalid = False

            for batch in batches:
                payload = self._payload(batch, readmes, retry=attempt > 0)
                try:
                    response = self._client.post(self.config.api_url, json=payload)
                except httpx.TimeoutException:
                    last_category = "timeout"
                    retry_pending.extend(batch)
                    continue
                except httpx.NetworkError:
                    last_category = "network_error"
                    retry_pending.extend(batch)
                    continue

                if response.status_code >= 400:
                    last_category = self._category(response)
                    if response.status_code >= 500:
                        retry_pending.extend(batch)
                        continue
                    return self._failure_result(
                        recommendations,
                        completed,
                        category=last_category,
                        message="MiniMax 服务暂不可用；AI 中文摘要暂不可用。",
                    )

                try:
                    raw = response.json()
                except (TypeError, ValueError, json.JSONDecodeError):
                    last_category = "invalid_response"
                    last_issue = "response_envelope"
                    pass_had_invalid = True
                    retry_pending.extend(batch)
                    logger.warning(
                        "MiniMax response rejected: attempt=%s/%s issue=%s requested=%s accepted=0",
                        attempt + 1,
                        self.config.max_retries + 1,
                        last_issue,
                        len(batch),
                    )
                    continue
                if not isinstance(raw, dict):
                    last_category = "invalid_response"
                    last_issue = "response_envelope"
                    pass_had_invalid = True
                    retry_pending.extend(batch)
                    logger.warning(
                        "MiniMax response rejected: attempt=%s/%s issue=%s requested=%s accepted=0",
                        attempt + 1,
                        self.config.max_retries + 1,
                        last_issue,
                        len(batch),
                    )
                    continue
                if raw.get("input_sensitive") or raw.get("output_sensitive"):
                    return self._failure_result(
                        recommendations,
                        completed,
                        category="content_safety",
                        message="MiniMax 内容安全检查未返回摘要；已保留规则结果。",
                    )
                base = raw.get("base_resp") or {}
                if not isinstance(base, dict):
                    base = {}
                if base.get("status_code") not in {None, 0}:
                    return self._failure_result(
                        recommendations,
                        completed,
                        category="provider_error",
                        message="MiniMax 返回业务错误；AI 中文摘要暂不可用。",
                    )

                expected_names = [item.repository.full_name for item in batch]
                parsed = self._parse_response(raw, expected_names)
                for item in parsed.enhancements:
                    completed[item.full_name] = item
                missing = set(parsed.missing_names)
                retry_pending.extend(
                    item for item in batch if item.repository.full_name in missing
                )
                if parsed.issue:
                    last_category = "invalid_response"
                    last_issue = parsed.issue
                    pass_had_invalid = True
                    logger.warning(
                        "MiniMax response rejected: attempt=%s/%s issue=%s requested=%s "
                        "accepted=%s finish_reason=%s request_id=%s",
                        attempt + 1,
                        self.config.max_retries + 1,
                        parsed.issue,
                        len(batch),
                        len(parsed.enhancements),
                        parsed.finish_reason or "unknown",
                        parsed.request_id or "unknown",
                    )

            seen_pending: set[str] = set()
            pending = []
            for item in retry_pending:
                name = item.repository.full_name
                if name in completed or name in seen_pending:
                    continue
                seen_pending.add(name)
                pending.append(item)
            if not pending:
                break
            split_invalid_batches = split_invalid_batches or pass_had_invalid
            if attempt < self.config.max_retries:
                self._sleep(min(8.0, 2.0**attempt))

        ordered = self._ordered_enhancements(recommendations, completed)
        if not pending:
            return EnhancementResult(enhancements=ordered)
        if last_category == "invalid_response":
            return EnhancementResult(
                enhancements=ordered,
                error_category=last_category,
                message=self._invalid_message(
                    last_issue,
                    self.config.max_retries,
                    partial=bool(ordered),
                ),
            )
        return EnhancementResult(
            enhancements=ordered,
            error_category=last_category,
            message="MiniMax 请求超时或网络不可用；AI 中文摘要暂不可用。",
        )
