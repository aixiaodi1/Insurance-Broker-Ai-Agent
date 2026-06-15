from app.memory.schemas import ToolResult


def rag_search(query: str) -> ToolResult:
    return ToolResult(
        ok=True,
        source="rag",
        data={
            "query": query,
            "citations": [],
            "status": "placeholder",
            "configured": False,
            "message": "RAG corpus is not configured yet, so this placeholder does not produce formal citations.",
        },
    )
