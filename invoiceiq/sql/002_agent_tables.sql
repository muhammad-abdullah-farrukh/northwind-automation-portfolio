-- InvoiceIQ: tables for the finance Q&A agent (workflow 4). Re-runnable; apply as the database owner
-- after 001_finance_schema.sql:
--   psql -f 002_agent_tables.sql
-- n8n's PGVector and Postgres-memory nodes run "CREATE ... IF NOT EXISTS" on start-up. Creating the tables
-- here first fixes the embedding size (nomic-embed-text = 768) and lets us add an index and exact grants.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- the PGVector node's id default uses uuid_generate_v4()

-- One row per stored invoice: a plain-text summary (vendor, number, dates, totals, line items) and its embedding.
CREATE TABLE IF NOT EXISTS finance.invoice_embeddings (
    id        uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    text      text,
    metadata  jsonb,
    embedding vector(768)
);
CREATE INDEX IF NOT EXISTS ix_invoice_embeddings_hnsw ON finance.invoice_embeddings USING hnsw (embedding vector_cosine_ops);

-- Chat history for the agent (same layout n8n's Postgres Chat Memory node creates).
CREATE TABLE IF NOT EXISTS finance.agent_chat_memory (
    id         serial PRIMARY KEY,
    session_id varchar(255) NOT NULL,
    message    jsonb NOT NULL
);

GRANT SELECT, INSERT, DELETE ON finance.invoice_embeddings TO finance_writer;
GRANT SELECT, INSERT, DELETE ON finance.agent_chat_memory TO finance_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA finance TO finance_writer;
-- finance_agent (the role the LLM's SQL runs as) still sees only invoices and line_items:
-- semantic search and memory go through fixed, parameterised node queries as finance_writer.
