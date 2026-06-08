-- migrations/004_academic_system.sql
-- Create isolated academic document tables

CREATE TABLE IF NOT EXISTS academic_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_type VARCHAR(50) NOT NULL,
    confidence FLOAT NOT NULL,
    extracted JSONB,
    warnings JSONB,
    raw_text TEXT,
    status VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- Note: In a full enterprise system, we would also have academic_subjects
-- and academic_semesters tables for normalized relational querying,
-- but storing extracted data in JSONB is preferred for document stores.
