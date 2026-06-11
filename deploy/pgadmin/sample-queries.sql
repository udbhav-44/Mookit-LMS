-- pgvector + mooKIT LMS — handy queries (run in pgAdmin Query Tool)

-- Confirm pgvector extension
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- Uploaded files and indexing status
SELECT id, filename, filesize, extraction_status, created_at
FROM file_meta
ORDER BY created_at DESC
LIMIT 20;

-- Chunk counts per document
SELECT doc_id, COUNT(*) AS chunks, MAX(LENGTH(text)) AS max_chunk_len
FROM doc_chunks
GROUP BY doc_id
ORDER BY chunks DESC;

-- Peek at indexed text (no raw vectors)
SELECT doc_id, chunk_index, LEFT(text, 120) AS preview
FROM doc_chunks
ORDER BY doc_id, chunk_index
LIMIT 20;

-- Vector dimensions (should be 1536 for text-embedding-3-small)
SELECT doc_id, chunk_index, vector_dims(embedding) AS dims
FROM doc_chunks
LIMIT 5;

-- Nearest chunks to a doc's first chunk (cosine distance demo)
SELECT b.doc_id, b.chunk_index, LEFT(b.text, 80) AS preview,
       a.embedding <=> b.embedding AS distance
FROM doc_chunks a
JOIN doc_chunks b ON b.doc_id = a.doc_id AND b.id <> a.id
WHERE a.doc_id = (SELECT doc_id FROM doc_chunks LIMIT 1)
  AND a.chunk_index = 0
ORDER BY distance
LIMIT 5;

-- Announcement / quiz drafts
SELECT id, type, title, status, version, user_id, updated_at
FROM artifacts
ORDER BY updated_at DESC
LIMIT 20;
