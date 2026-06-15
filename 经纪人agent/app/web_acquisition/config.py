from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WebAcquisitionConfig:
    request_timeout_seconds: int = 10
    total_timeout_seconds: int = 90
    download_timeout_seconds: int = 30
    page_timeout_seconds: int = 60
    step_timeout_seconds: int = 10
    browser_pool_size: int = 1
    max_redirects: int = 5
    max_file_size_bytes: int = 50 * 1024 * 1024
    max_total_download_bytes: int = 200 * 1024 * 1024
    quality_success_threshold: float = 0.65
    downloads_dir: Path = Path("data/downloads")
    allowed_click_texts: tuple[str, ...] = (
        "下载",
        "查看",
        "详情",
        "产品条款",
        "条款",
        "产品说明书",
        "信息披露",
        "展开",
        "更多",
        "下一页",
        "PDF",
        "费率表",
        "现金价值表",
        "红利实现率",
        "分红实现率",
        "投保须知",
    )
    blocked_click_texts: tuple[str, ...] = (
        "登录",
        "注册",
        "购买",
        "立即投保",
        "支付",
        "个人中心",
        "客服",
        "在线咨询",
        "分享",
        "广告",
        "立即预约",
        "提交",
        "验证码",
    )
    allowed_content_types: set[str] = field(
        default_factory=lambda: {
            "text/html",
            "text/plain",
            "application/json",
            "application/pdf",
        }
    )
