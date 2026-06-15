from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.extractor import Extractor
from app.web_acquisition.quality import score_quality
from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep


def test_stage1_defaults_and_result_shape():
    config = WebAcquisitionConfig()
    step = AcquisitionStep(layer="security", action="validate", description="validated input URL")
    result = AcquisitionResult(
        success=True,
        input_url="https://example.com/product",
        final_url="https://example.com/product",
        strategy_used="http",
        title="Example",
        steps=[step],
        quality_score=0.8,
    )

    assert config.max_redirects == 5
    assert config.max_file_size_bytes == 50 * 1024 * 1024
    assert config.max_total_download_bytes == 200 * 1024 * 1024
    assert "application/pdf" in config.allowed_content_types
    assert result.steps[0].layer == "security"
    assert result.errors == []


def test_quality_score_rewards_insurance_content_and_pdf_links():
    html = """
    <html><head><title>保险产品信息披露</title></head><body>
    <p>保险 产品 条款 费率 现金价值 产品说明书 投保须知 信息披露 分红 红利实现率 年金 终身寿 医疗险 重疾险</p>
    <p>""" + ("保险责任 " * 80) + """</p>
    <a href="/clause.pdf">产品条款</a>
    </body></html>
    """
    extracted = Extractor().extract_html(html, "https://example.com/product")

    assessment = score_quality(extracted)

    assert assessment.score >= 0.65
    assert assessment.should_escalate is False


def test_quality_score_escalates_javascript_shell():
    html = """
    <html><head><title>Loading</title></head><body>
      <div id="app-root"></div>
      <script>window.__NEXT_DATA__ = {"props": {}};</script>
      <script src="/bundle.js"></script>
    </body></html>
    """
    extracted = Extractor().extract_html(html, "https://example.com/product")

    assessment = score_quality(extracted)

    assert assessment.score < 0.65
    assert assessment.should_escalate is True
    assert "js_shell" in assessment.reasons
