from pathlib import Path

from app.memory.schemas import ToolResult


def validate_pdf(path: str) -> ToolResult:
    file_path = Path(path)
    if not file_path.exists():
        return ToolResult(ok=False, source="pdf", error="文件不存在")
    with file_path.open("rb") as fh:
        magic = fh.read(4)
    return ToolResult(
        ok=magic == b"%PDF",
        source="pdf",
        data={"path": str(file_path), "is_valid_pdf": magic == b"%PDF"},
        error=None if magic == b"%PDF" else "不是PDF魔数",
    )
