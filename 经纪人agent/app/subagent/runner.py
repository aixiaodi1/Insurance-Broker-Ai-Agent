from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.subagent.loader import SubagentLoader
from app.subagent.output_mode import build_request_kwargs, resolve_output_mode
from app.subagent.registry import RegistryBuilder
from app.subagent.schemas import SubagentDefinition, SubagentResult, SubagentTrace

_MAX_SPAWN_DEPTH = 1


def _validate_input(definition: SubagentDefinition, context: dict) -> str | None:
    schema = definition.input_schema
    required = schema.get("required", [])
    for field in required:
        if field not in context:
            return f"缺少必填字段 '{field}'"
    props = schema.get("properties", {})
    for field, value in context.items():
        if field in props:
            expected_type = props[field].get("type")
            if expected_type == "string" and not isinstance(value, str):
                return f"字段 '{field}' 应为 string, 收到 {type(value).__name__}"
            if expected_type == "integer" and not isinstance(value, int):
                return f"字段 '{field}' 应为 integer, 收到 {type(value).__name__}"
            if expected_type == "number" and not isinstance(value, (int, float)):
                return f"字段 '{field}' 应为 number, 收到 {type(value).__name__}"
    return None


def _parse_llm_output(
    raw: dict,
    output_schema: dict | None,
    output_mode: str,
) -> tuple[Any, str | None]:
    answer = raw.get("answer", "")

    if output_mode == "function_calling":
        calls = raw.get("tool_calls", [])
        if calls:
            try:
                args = calls[0].get("function", {}).get("arguments", "{}")
                return json.loads(args), None
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

    if answer:
        try:
            return json.loads(answer), None
        except json.JSONDecodeError:
            pass

    if output_schema:
        return answer, "输出不是有效 JSON"
    return answer, None


def _validate_output(result: Any, output_schema: dict | None) -> str | None:
    if output_schema is None:
        return None
    if not isinstance(result, dict):
        return "输出不是 JSON 对象"
    props = output_schema.get("properties", {})
    for field, prop in props.items():
        if field in prop.get("required", []) and field not in result:
            return f"缺少必填输出字段 '{field}'"
    return None


class SubagentRunner:
    def __init__(
        self,
        loader: SubagentLoader,
        llm_client: Any,
        contracts_dir: str | Path = "",
    ) -> None:
        self._loader = loader
        self._llm = llm_client
        self._pool = ThreadPoolExecutor(max_workers=10)
        self._registry = RegistryBuilder(loader) if loader else None

    def get_registry_prompt(self) -> str:
        if self._registry:
            return self._registry.build_registry_prompt()
        return ""

    async def spawn(
        self,
        name: str,
        context: dict[str, Any],
        parent_trace_id: str = "main",
        _depth: int = 0,
    ) -> SubagentResult:
        if _depth >= _MAX_SPAWN_DEPTH:
            return SubagentResult(
                status="error",
                error_message=f"subagent 调用深度已达上限 ({_MAX_SPAWN_DEPTH})",
            )

        trace = SubagentTrace(parent_trace_id=parent_trace_id)

        try:
            definition = self._loader.load_sync(name)
        except FileNotFoundError as exc:
            return SubagentResult(status="error", error_message=str(exc), trace=trace)

        input_error = _validate_input(definition, context)
        if input_error:
            return SubagentResult(status="error", error_message=input_error, trace=trace)

        return await self._execute(definition, context, trace)

    async def spawn_many(
        self,
        name: str,
        contexts: list[dict[str, Any]],
        strategy: str = "all_success",
        parent_trace_id: str = "main",
    ) -> list[SubagentResult]:
        async def _run_one(ctx: dict) -> SubagentResult:
            return await self.spawn(name, ctx, parent_trace_id=parent_trace_id)

        tasks = [_run_one(ctx) for ctx in contexts]
        done = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[SubagentResult] = []
        for item in done:
            if isinstance(item, Exception):
                results.append(
                    SubagentResult(
                        status="error",
                        error_message=str(item),
                        trace=SubagentTrace(parent_trace_id=parent_trace_id),
                    )
                )
            else:
                results.append(item)

        if strategy == "any_success":
            for r in results:
                if r.status == "success":
                    return [r]
            return results
        if strategy == "return_first":
            for r in results:
                if r.status == "success":
                    return [r]
            return results[:1]

        return results

    async def _execute(
        self,
        definition: SubagentDefinition,
        context: dict[str, Any],
        trace: SubagentTrace,
    ) -> SubagentResult:
        output_cfg = definition.output
        output_schema = output_cfg.get("schema")
        max_retry = output_cfg.get("retry", 2)
        temperature = output_cfg.get("temperature", 0.0)
        configured_mode = output_cfg.get("mode", "auto")
        retry_first_temp = output_cfg.get("retry_strategy", {}).get(
            "first_retry_temperature", 0.3
        )
        retry_second_temp = output_cfg.get("retry_strategy", {}).get(
            "second_retry_temperature", 0.5
        )
        fallback_on_exhausted = output_cfg.get("retry_strategy", {}).get(
            "fallback_on_exhausted", "return_raw"
        )

        exec_cfg = definition.execution
        max_turns = exec_cfg.get("max_turns", 10)
        max_tool_calls = exec_cfg.get("max_tool_calls", 30)
        max_consecutive_identical = exec_cfg.get("max_consecutive_identical", 3)
        timeout_secs = exec_cfg.get("timeout", 30)
        on_timeout = exec_cfg.get("on_timeout", "retry_once")

        sandbox_cfg = exec_cfg.get("sandbox", {})
        sandbox_dir: str | None = None
        if sandbox_cfg.get("temp_dir", False):
            sandbox_dir = tempfile.mkdtemp(
                prefix=f"subagent_{trace.trace_id}_"
            )

        try:
            return await self._run_llm_loop(
                definition=definition,
                context=context,
                trace=trace,
                output_schema=output_schema,
                max_retry=max_retry,
                temperature=temperature,
                configured_mode=configured_mode,
                retry_first_temp=retry_first_temp,
                retry_second_temp=retry_second_temp,
                fallback_on_exhausted=fallback_on_exhausted,
                max_turns=max_turns,
                max_tool_calls=max_tool_calls,
                max_consecutive_identical=max_consecutive_identical,
                timeout_secs=timeout_secs,
                on_timeout=on_timeout,
                sandbox_dir=sandbox_dir,
            )
        finally:
            if sandbox_dir and sandbox_cfg.get("temp_dir_cleanup", True):
                import shutil

                shutil.rmtree(sandbox_dir, ignore_errors=True)

    async def _run_llm_loop(
        self,
        definition: SubagentDefinition,
        context: dict[str, Any],
        trace: SubagentTrace,
        output_schema: dict | None,
        max_retry: int,
        temperature: float,
        configured_mode: str,
        retry_first_temp: float,
        retry_second_temp: float,
        fallback_on_exhausted: str,
        max_turns: int,
        max_tool_calls: int,
        max_consecutive_identical: int,
        timeout_secs: int,
        on_timeout: str,
        sandbox_dir: str | None,
    ) -> SubagentResult:
        system_prompt = self._build_system_prompt(definition, context)
        user_message = json.dumps(context, ensure_ascii=False, indent=2)

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        model = getattr(self._llm, "model", "unknown")
        output_mode = resolve_output_mode(model, configured_mode)
        current_temperature = temperature
        last_raw: dict | None = None
        consecutive_identical_count = 0
        last_tool_sig: str | None = None
        total_tool_calls = 0

        for turn in range(max_turns):
            if total_tool_calls >= max_tool_calls:
                trace.log.append({"turn": turn, "event": "max_tool_calls_reached"})
                break

            kwargs = build_request_kwargs(output_mode, output_schema, current_temperature)

            start = time.monotonic()
            try:
                raw = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        self._pool,
                        self._call_llm,
                        messages,
                        kwargs,
                    ),
                    timeout=timeout_secs,
                )
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - start
                trace.log.append({"turn": turn, "event": "timeout", "elapsed": round(elapsed, 2)})

                if on_timeout == "retry_once" and turn == 0:
                    try:
                        raw = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                self._pool,
                                self._call_llm,
                                messages,
                                kwargs,
                            ),
                            timeout=timeout_secs,
                        )
                    except asyncio.TimeoutError:
                        return SubagentResult(
                            status="timeout",
                            error_message=f"subagent 超时（重试后依然超时）",
                            trace=trace,
                        )
                else:
                    return SubagentResult(status="timeout", trace=trace)

            elapsed = time.monotonic() - start
            trace.turn_count = turn + 1
            trace.tokens_used += self._extract_tokens(raw)

            result, parse_error = _parse_llm_output(raw, output_schema, output_mode)
            last_raw = raw

            tool_calls = raw.get("tool_calls", [])
            total_tool_calls += len(tool_calls)
            if tool_calls:
                sig = json.dumps(
                    [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments"))
                     for tc in tool_calls],
                    sort_keys=True,
                )
                if sig == last_tool_sig:
                    consecutive_identical_count += 1
                    if consecutive_identical_count >= max_consecutive_identical:
                        return SubagentResult(
                            status="error",
                            error_message=f"连续 {max_consecutive_identical} 次相同工具调用",
                            trace=trace,
                        )
                else:
                    consecutive_identical_count = 0
                    last_tool_sig = sig

            validation_error = _validate_output(result, output_schema)

            if validation_error is None:
                return SubagentResult(
                    status="success",
                    result=result,
                    trace=trace,
                )

            if parse_error:
                messages.append({"role": "assistant", "content": raw.get("answer", "")})
                messages.append({
                    "role": "user",
                    "content": f"输出格式有误：{parse_error}。请严格按照要求的 JSON 格式返回。",
                })
            else:
                messages.append({"role": "assistant", "content": raw.get("answer", "")})
                messages.append({
                    "role": "user",
                    "content": f"输出验证失败：{validation_error}。请修正后重试。",
                })

            trace.retry_count += 1
            if trace.retry_count > max_retry:
                trace.log.append({"event": "max_retry_exceeded"})
                if fallback_on_exhausted == "return_raw" and last_raw:
                    return SubagentResult(
                        status="schema_validation_failed",
                        raw_output=last_raw.get("answer", ""),
                        trace=trace,
                        error_message="重试耗尽，返回原始输出",
                    )
                return SubagentResult(
                    status="schema_validation_failed",
                    trace=trace,
                    error_message="重试耗尽，无降级输出",
                )

            if trace.retry_count == 1:
                current_temperature = retry_first_temp
            elif trace.retry_count >= 2:
                current_temperature = retry_second_temp

        return SubagentResult(
            status="error",
            error_message=f"达到最大轮数 {max_turns}，未完成任务",
            trace=trace,
        )

    def _build_system_prompt(
        self,
        definition: SubagentDefinition,
        context: dict[str, Any],
    ) -> str:
        parts = [definition.prompt]

        ctx_cfg = definition.context
        if ctx_cfg.get("project_rules", False):
            agents_path = Path.cwd() / "AGENTS.md"
            if agents_path.is_file():
                text = agents_path.read_text(encoding="utf-8")[:2000]
                parts.append(f"\n[项目规则]\n{text}")
        if ctx_cfg.get("tool_docs", False):
            tools_path = Path.cwd() / "TOOLS.md"
            if tools_path.is_file():
                text = tools_path.read_text(encoding="utf-8")[:2000]
                parts.append(f"\n[工具说明]\n{text}")

        extra = context.get("extra_instructions", "")
        if extra:
            parts.append(f"\n[额外指示]\n{extra}")

        out_schema = definition.output.get("schema")
        if out_schema:
            parts.append(
                f"\n[输出要求]\n严格返回符合以下 JSON Schema 的数据：\n"
                f"{json.dumps(out_schema, ensure_ascii=False, indent=2)}"
            )

        return "\n".join(parts)

    def _call_llm(self, messages: list[dict], kwargs: dict) -> dict:
        system_content = ""
        user_prompt = ""
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")
        response_format = kwargs.get("response_format")

        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            elif msg["role"] == "user":
                user_prompt = msg["content"]

        raw = self._llm.generate(
            prompt=user_prompt,
            system_prompt=system_content or None,
            tools=tools,
            tool_choice=tool_choice,
        )
        return {
            "answer": raw.get("answer", ""),
            "tool_calls": raw.get("tool_calls", []),
            "tokens": raw.get("tokens", {}),
        }

    @staticmethod
    def _extract_tokens(raw: dict) -> int:
        tokens = raw.get("tokens", {})
        if isinstance(tokens, dict):
            return tokens.get("total_tokens", 0) or 0
        return 0
