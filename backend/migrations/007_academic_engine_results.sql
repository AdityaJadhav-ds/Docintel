-- migrations/007_academic_engine_results.sql
-- Persistent store for Academic Engine v2 (/api/v2/academic/analyze) results.
-- Used by academic_engine_routes.py _persist() function.

CREATE TABLE IF NOT EXISTS academic_engine_results (
    id                  UUID PRIMARY KEY,
    document_category   VARCHAR(50),
    document_type       VARCHAR(100),
    candidate_name      VARCHAR(255),
    board_university    VARCHAR(255),
    passing_year        VARCHAR(20),
    percentage          VARCHAR(20),
    cgpa                VARCHAR(20),
    grade_class         VARCHAR(100),
    result              VARCHAR(50),
    confidence          FLOAT DEFAULT 0.0,
    status              VARCHAR(50),
    elapsed_s           FLOAT,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- Index for fast lookup by status and created_at
CREATE INDEX IF NOT EXISTS idx_academic_engine_results_status
    ON academic_engine_results(status);

CREATE INDEX IF NOT EXISTS idx_academic_engine_results_created
    ON academic_engine_results(created_at DESC);

-- Optional RLS (Row Level Security) — disabled by default for service role
ALTER TABLE academic_engine_results DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE academic_engine_results IS
    'Persistent results from the Academic Engine v2 pipeline (MasterPipeline). '
    'Each row corresponds to one document analyzed via POST /api/v2/academic/analyze.';
