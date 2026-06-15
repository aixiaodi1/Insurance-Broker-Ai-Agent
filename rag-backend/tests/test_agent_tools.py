from pathlib import Path

from app.services import agent_tools
from app.services.agent_tools import local_search


def test_local_search_ignores_project_test_files(tmp_path: Path) -> None:
    ignored_dir = tmp_path / "tests"
    ignored_dir.mkdir()
    (ignored_dir / "leak.md").write_text("复星联合医疗险 工程测试内容", encoding="utf-8")

    result = local_search("复星联合医疗险", tmp_path)

    assert result["data"]["matches"] == []


def test_local_search_deduplicates_same_line_matches(tmp_path: Path) -> None:
    source_file = tmp_path / "fosun.md"
    source_file.write_text("复星联合健康保险：医疗险产品线索。", encoding="utf-8")

    result = local_search("复星联合医疗险", tmp_path)

    matches = result["data"]["matches"]
    assert len(matches) == 1
    assert matches[0]["path"] == str(source_file)


def test_local_search_does_not_match_only_common_english_terms(tmp_path: Path) -> None:
    source_file = tmp_path / "golden_qa.json"
    source_file.write_text('"notes": "product coverage summary"', encoding="utf-8")

    result = local_search("Find a Fosun United medical insurance product", tmp_path)

    assert result["data"]["matches"] == []


def test_local_search_does_not_match_only_common_chinese_terms(tmp_path: Path) -> None:
    source_file = tmp_path / "notes.md"
    source_file.write_text("很多老款医疗险只赔住院费用。", encoding="utf-8")

    result = local_search("你帮我去复星联合找一款医疗险", tmp_path)

    assert result["data"]["matches"] == []


def test_local_search_does_not_match_generic_chinese_entity_fragments(tmp_path: Path) -> None:
    source_file = tmp_path / "cancer.md"
    source_file.write_text("TNM分期由美国癌症联合委员会制定。", encoding="utf-8")

    result = local_search("你帮我去复星联合找一款医疗险", tmp_path)

    assert result["data"]["matches"] == []


def test_web_search_removes_english_intent_words(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_web_fetch(url: str, max_chars: int = 4000) -> dict:
        captured["url"] = url
        return {"ok": True, "source": "web_fetch", "data": {"raw_html": ""}, "error": None}

    monkeypatch.setattr(agent_tools, "web_fetch", fake_web_fetch)

    result = agent_tools.web_search("Find a Fosun United medical insurance product")

    assert result["ok"] is True
    assert "Find" not in captured["url"]
    assert "Fosun+United+medical+insurance+product" in captured["url"]


def test_web_search_keeps_general_chinese_queries_domain_neutral(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_web_fetch(url: str, max_chars: int = 4000) -> dict:
        captured["url"] = url
        return {"ok": True, "source": "web_fetch", "data": {"raw_html": ""}, "error": None}

    monkeypatch.setattr(agent_tools, "web_fetch", fake_web_fetch)

    result = agent_tools.web_search("你帮我去复星联合找一款医疗险")

    assert result["ok"] is True
    assert not result["data"]["query"].startswith("site:fosun-uhi.com")
    assert "site%3Afosun-uhi.com" not in captured["url"]


def test_web_search_does_not_lock_dividend_irr_query_to_official_site(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_web_fetch(url: str, max_chars: int = 4000) -> dict:
        captured["url"] = url
        return {
            "ok": True,
            "source": "web_fetch",
            "data": {
                "raw_html": (
                    '<h2><a href="https://example.test/fosun-prudential">'
                    "Fosun Prudential Xingfu Jia dividend insurance IRR</a></h2>"
                )
            },
            "error": None,
        }

    monkeypatch.setattr(agent_tools, "web_fetch", fake_web_fetch)

    result = agent_tools.web_search("现在复星联合说有一款分红险IRR特别高，你能帮我找到吗")

    assert result["ok"] is True
    assert "site%3Afosun-uhi.com" not in captured["url"]
    assert "IRR" in captured["url"]
    urls = [item["url"] for item in result["data"]["results"]]
    assert "https://www.pramericalife.com.cn/" not in urls
    assert "https://example.test/fosun-prudential" in urls
