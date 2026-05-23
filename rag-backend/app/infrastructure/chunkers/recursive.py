from app.domain import TextChunk


class RecursiveTextChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str) -> list[TextChunk]:
        normalized_text = " ".join(text.split())
        if not normalized_text:
            raise ValueError("Cannot chunk empty text")

        tokens = normalized_text.split()
        step = self.chunk_size - self.chunk_overlap
        chunks: list[TextChunk] = []

        for start in range(0, len(tokens), step):
            chunk_tokens = tokens[start : start + self.chunk_size]
            if not chunk_tokens:
                break

            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    text=" ".join(chunk_tokens),
                    token_count=len(chunk_tokens),
                )
            )

            if start + self.chunk_size >= len(tokens):
                break

        return chunks
