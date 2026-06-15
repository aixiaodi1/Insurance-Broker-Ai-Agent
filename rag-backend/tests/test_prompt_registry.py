from pathlib import Path

import pytest

from app.services.prompt_registry import PromptRegistry, get_default_prompt_registry


def test_prompt_registry_renders_template_with_blocks(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text(
        """
blocks:
  grounding: |
    只能依据证据回答。
prompts:
  rag_clause_qa:
    version: v1
    system_blocks:
      - grounding
    user: |
      问题：{query}
      资料：{packed_context}
""".strip(),
        encoding="utf-8",
    )

    registry = PromptRegistry.from_file(prompt_file)
    rendered = registry.render("rag_clause_qa", query="等待期多久？", packed_context="[1] 等待期30天")

    assert rendered.version == "v1"
    assert rendered.system == "只能依据证据回答。"
    assert "问题：等待期多久？" in rendered.user
    assert "资料：[1] 等待期30天" in rendered.user


def test_prompt_registry_raises_for_missing_variable(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text(
        """
prompts:
  var_extract:
    user: "用户输入：{query}"
""".strip(),
        encoding="utf-8",
    )

    registry = PromptRegistry.from_file(prompt_file)

    with pytest.raises(KeyError, match="query"):
        registry.render("var_extract")


def test_entry_planner_prompt_routes_tool_capability_questions_away_from_identity() -> None:
    rendered = get_default_prompt_registry().render("entry_planner", query="你能检查我本地的文件吗？")

    assert "你能检查我本地的文件吗？" in rendered.user
    assert '=> {"route":"capability_answer","answer_key":null}' in rendered.user
    assert "不要把“你能做什么”“你能不能检查文件”“你能执行命令吗”这类能力问题塞进 direct_answer" in rendered.user
