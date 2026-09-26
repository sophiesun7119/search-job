PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS companies (
  company_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  official_url TEXT NOT NULL,
  source TEXT NOT NULL,
  scan_cohort TEXT NOT NULL DEFAULT 'new' CHECK (scan_cohort IN ('new','old')),
  validated_at TEXT
);
CREATE TABLE IF NOT EXISTS source_leads (
  lead_key TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_id TEXT NOT NULL,
  name TEXT NOT NULL,
  source_year INTEGER,
  source_url TEXT,
  profile_url TEXT,
  source_company_url TEXT,
  profile_company_url TEXT,
  sample_apply_url TEXT,
  sample_title TEXT,
  sample_location TEXT,
  sample_probe_url TEXT,
  sample_probe_status INTEGER,
  sample_probe_error TEXT,
  sample_probe_at TEXT,
  official_url TEXT,
  company_key TEXT REFERENCES companies(company_key),
  provider_hint TEXT,
  board_hint TEXT,
  route_evidence_url TEXT,
  route_resolution_method TEXT CHECK (route_resolution_method IN ('script_official_page','ai_official_page','user_official_page')),
  official_board_url TEXT,
  stage TEXT NOT NULL DEFAULT 'imported' CHECK (stage IN
    ('imported','route_pending','adapter_pending','board_pending','scan_pending','scanned')),
  last_error TEXT,
  checked_at TEXT,
  review_state TEXT NOT NULL DEFAULT 'script_pending' CHECK (review_state IN
    ('script_pending','ai_pending','ai_in_progress','needs_user','resolved')),
  ai_review_note TEXT,
  ai_reviewed_at TEXT,
  review_updated_at TEXT,
  UNIQUE (source_name, source_id)
);
CREATE TABLE IF NOT EXISTS provider_capabilities (
  provider TEXT PRIMARY KEY,
  adapter_key TEXT NOT NULL,
  support_status TEXT NOT NULL CHECK (support_status IN ('planned','tested','active'))
);
CREATE TABLE IF NOT EXISTS boards (
  board_key TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  board_token TEXT NOT NULL,
  board_url TEXT,
  route_status TEXT NOT NULL CHECK (route_status IN ('pending_recheck','active','failed')),
  last_complete_scan_at TEXT,
  UNIQUE (provider, board_token)
);
CREATE TABLE IF NOT EXISTS company_boards (
  company_key TEXT NOT NULL REFERENCES companies(company_key),
  board_key TEXT NOT NULL REFERENCES boards(board_key),
  evidence_url TEXT,
  brand_filter TEXT,
  checked_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('pending_recheck','pending_identity','verified','failed')),
  PRIMARY KEY (company_key, board_key)
);
CREATE TABLE IF NOT EXISTS scan_runs (
  scan_key TEXT PRIMARY KEY,
  board_key TEXT NOT NULL REFERENCES boards(board_key),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('complete','partial','failed')),
  error TEXT
);
CREATE TABLE IF NOT EXISTS openings (
  opening_key TEXT PRIMARY KEY,
  company_key TEXT NOT NULL REFERENCES companies(company_key),
  board_key TEXT REFERENCES boards(board_key),
  provider TEXT NOT NULL,
  provider_job_id TEXT,
  canonical_url TEXT NOT NULL,
  title TEXT NOT NULL,
  open_state TEXT NOT NULL CHECK (open_state IN ('open','inactive','unknown')),
  source_date_field TEXT,
  source_date_value TEXT,
  source_date_precision TEXT,
  published_at TEXT,
  updated_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status_evidence TEXT,
  missing_complete_scans INTEGER NOT NULL DEFAULT 0,
  CHECK (provider_job_id IS NOT NULL OR canonical_url <> '')
);
CREATE UNIQUE INDEX IF NOT EXISTS openings_by_provider_id ON openings(provider, board_key, provider_job_id) WHERE provider_job_id IS NOT NULL AND board_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS opening_variants (
  opening_key TEXT NOT NULL REFERENCES openings(opening_key) ON DELETE CASCADE,
  location TEXT NOT NULL DEFAULT '',
  apply_url TEXT NOT NULL,
  PRIMARY KEY (opening_key, location, apply_url)
);
CREATE TABLE IF NOT EXISTS opening_tags (
  opening_key TEXT NOT NULL REFERENCES openings(opening_key) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  evidence TEXT NOT NULL,
  PRIMARY KEY (opening_key, tag)
);
