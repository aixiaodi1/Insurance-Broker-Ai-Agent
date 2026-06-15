from app.web_acquisition.extractor import Extractor, classify_document


def test_extractor_finds_title_text_links_and_pdf_candidates():
    html = """
    <html>
      <head><title>官方产品资料</title></head>
      <body>
        <h1>保险产品信息披露</h1>
        <a href="/docs/clause.pdf">产品条款 PDF</a>
        <a href="https://static.example.com/rate.pdf">费率表</a>
        <iframe src="/frame/disclosure.html"></iframe>
        <button data-url="/download/cash-value.pdf">现金价值表下载</button>
        <button onclick="window.open('/notice/application.pdf')">投保须知</button>
        <script>var u = "https://example.com/files/dividend.pdf";</script>
      </body>
    </html>
    """

    extracted = Extractor().extract_html(html, "https://example.com/product/index.html")

    assert extracted.title == "官方产品资料"
    assert "保险产品信息披露" in extracted.text
    assert {item.url for item in extracted.pdf_links} >= {
        "https://example.com/docs/clause.pdf",
        "https://static.example.com/rate.pdf",
        "https://example.com/download/cash-value.pdf",
        "https://example.com/notice/application.pdf",
        "https://example.com/files/dividend.pdf",
    }
    assert extracted.iframe_links[0].url == "https://example.com/frame/disclosure.html"
    assert any(item.document_type == "cash_value_table" for item in extracted.document_links)


def test_classify_document_uses_chinese_text_and_url():
    clause = classify_document("产品条款", "https://example.com/a.pdf")
    rate = classify_document("", "https://example.com/files/rate-table.pdf")
    unknown = classify_document("下载", "https://example.com/file.bin")

    assert clause.document_type == "insurance_clause"
    assert clause.confidence >= 0.8
    assert rate.document_type == "rate_table"
    assert unknown.document_type == "unknown"
