def chunk_document_text(text: str, limit: int = 1200) -> list[str]:
    if limit < 1:
        raise ValueError("Chunk limit must be positive.")
    chunks: list[str] = []
    current = ""
    for paragraph in text.splitlines():
        remaining = paragraph.strip()
        if not remaining:
            continue
        while len(remaining) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]
        if current and len(current) + len(remaining) + 1 > limit:
            chunks.append(current)
            current = remaining
        else:
            current = f"{current}\n{remaining}".strip()
    if current:
        chunks.append(current)
    return chunks
