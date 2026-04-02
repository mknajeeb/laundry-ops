-- Per-organization branding: logo URL (HTTPS to CDN or blob) and optional future fields.
-- Run after organizations_multitenancy_v1.sql. Safe to re-run if column exists (will error once; ignore or use procedure).

SET NAMES utf8mb4;

-- Logo: store a stable HTTPS URL (Azure Blob, CDN, etc.). Max length fits most SAS URLs.
ALTER TABLE organizations
  ADD COLUMN logo_url VARCHAR(768) NULL
  COMMENT 'HTTPS URL to organization logo image'
  AFTER display_name;
