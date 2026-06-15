from app.web_acquisition.config import WebAcquisitionConfig
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
