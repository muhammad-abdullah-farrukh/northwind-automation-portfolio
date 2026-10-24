-- InvoiceIQ finance schema, in the OpsCore Postgres (n8n reaches it at host.docker.internal:5433).
-- Re-runnable. Apply with the role passwords as psql variables (see invoiceiq/README.md):
--   psql -v writer_pw=... -v agent_pw=... -f 001_finance_schema.sql
-- finance_writer: used by workflows 1 and 3 (insert invoices, log intake events and errors).
-- finance_agent:  used by the Q&A agent's SQL tool. Read-only, short statement timeout, invoices only.

CREATE SCHEMA IF NOT EXISTS finance;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_writer') THEN CREATE ROLE finance_writer LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_agent') THEN CREATE ROLE finance_agent LOGIN; END IF;
END $$;
ALTER ROLE finance_writer PASSWORD :'writer_pw';
ALTER ROLE finance_agent PASSWORD :'agent_pw';

ALTER ROLE finance_writer SET search_path = finance, public;
ALTER ROLE finance_agent SET search_path = finance, public;
ALTER ROLE finance_agent SET default_transaction_read_only = on;
ALTER ROLE finance_agent SET statement_timeout = '5s';

CREATE TABLE IF NOT EXISTS finance.invoices (
    id            bigserial PRIMARY KEY,
    job_id        text NOT NULL UNIQUE,            -- OpsCore job id
    invoice_no    text NOT NULL,
    vendor        text NOT NULL,
    invoice_date  date,
    due_date      date,
    currency      char(3) NOT NULL,
    subtotal      numeric(14, 2),
    tax           numeric(14, 2),
    total         numeric(14, 2) NOT NULL,
    status        text NOT NULL CHECK (status IN ('auto_approved', 'approved', 'approved_with_edits')),
    confidence    numeric(4, 3),
    approved_by   text,
    source        text NOT NULL CHECK (source IN ('email', 'form')),
    source_email  text,
    paid          boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_invoices_vendor ON finance.invoices (vendor);
CREATE INDEX IF NOT EXISTS ix_invoices_invoice_date ON finance.invoices (invoice_date);

CREATE TABLE IF NOT EXISTS finance.line_items (
    id          bigserial PRIMARY KEY,
    invoice_id  bigint NOT NULL REFERENCES finance.invoices (id) ON DELETE CASCADE,
    line_no     integer NOT NULL,
    description text NOT NULL,
    qty         numeric(12, 3),
    unit_price  numeric(14, 2),
    amount      numeric(14, 2) NOT NULL,
    UNIQUE (invoice_id, line_no)
);

-- Every file that enters workflow 1 ends in exactly one outcome row (stored, duplicate, rejected, failed).
CREATE TABLE IF NOT EXISTS finance.intake_events (
    id          bigserial PRIMARY KEY,
    job_id      text,
    file_sha256 text NOT NULL,
    file_name   text,
    source      text NOT NULL,
    outcome     text NOT NULL CHECK (outcome IN ('stored', 'duplicate', 'rejected', 'failed')),
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.errors (
    id            bigserial PRIMARY KEY,
    workflow      text NOT NULL,
    node          text,
    message       text NOT NULL,
    execution_url text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

GRANT USAGE, CREATE ON SCHEMA finance TO finance_writer;   -- CREATE: n8n creates its vector and chat-memory tables
GRANT USAGE ON SCHEMA finance TO finance_agent;
GRANT SELECT, INSERT, UPDATE ON finance.invoices, finance.line_items, finance.intake_events, finance.errors TO finance_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA finance TO finance_writer;
GRANT SELECT ON finance.invoices, finance.line_items TO finance_agent;
