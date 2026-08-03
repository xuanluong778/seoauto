-- SEOAuto WordPress plugin connection schema (PostgreSQL)
-- Revision: 20260722_wordpress_plugin_connections
-- Tenant: user_id + organization_id (personal org = user_id until organizations table exists).
-- Secrets: site_secret_encrypted stores Fernet enc:v1: strings (app-layer).
-- Pairing: only code_hash (HMAC-SHA256), never plaintext.

BEGIN;

CREATE TABLE IF NOT EXISTS wordpress_connections (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     INTEGER NOT NULL,
    publishing_site_id  VARCHAR(64) NULL,
    site_url            VARCHAR(2000) NOT NULL,
    domain_normalized   VARCHAR(255) NOT NULL,
    site_secret_encrypted TEXT NOT NULL DEFAULT '',
    plugin_version      VARCHAR(32) NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    last_seen_at        TIMESTAMPTZ NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wordpress_connections_org_domain
        UNIQUE (organization_id, domain_normalized)
);

CREATE INDEX IF NOT EXISTS ix_wordpress_connections_user_id
    ON wordpress_connections (user_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_connections_organization_id
    ON wordpress_connections (organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_connections_user_org
    ON wordpress_connections (user_id, organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_connections_org_status
    ON wordpress_connections (organization_id, status);
CREATE INDEX IF NOT EXISTS ix_wordpress_connections_publishing_site
    ON wordpress_connections (publishing_site_id);

CREATE TABLE IF NOT EXISTS wordpress_pairing_codes (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     INTEGER NOT NULL,
    connection_id       INTEGER NULL REFERENCES wordpress_connections(id) ON DELETE SET NULL,
    code_hash           VARCHAR(128) NOT NULL,
    code_prefix         VARCHAR(16) NOT NULL DEFAULT '',
    domain_normalized   VARCHAR(255) NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    consumed_at         TIMESTAMPTZ NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wordpress_pairing_codes_hash UNIQUE (code_hash)
);

CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_user_id
    ON wordpress_pairing_codes (user_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_organization_id
    ON wordpress_pairing_codes (organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_org_status
    ON wordpress_pairing_codes (organization_id, status);
CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_user_org
    ON wordpress_pairing_codes (user_id, organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_expires
    ON wordpress_pairing_codes (expires_at);
CREATE INDEX IF NOT EXISTS ix_wordpress_pairing_codes_connection_id
    ON wordpress_pairing_codes (connection_id);

CREATE TABLE IF NOT EXISTS wordpress_entitlements (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id         INTEGER NOT NULL,
    connection_id           INTEGER NOT NULL REFERENCES wordpress_connections(id) ON DELETE CASCADE,
    allowed                 BOOLEAN NOT NULL DEFAULT FALSE,
    reason                  VARCHAR(64) NOT NULL DEFAULT '',
    plan_code               VARCHAR(64) NULL,
    subscription_status     VARCHAR(32) NULL,
    expires_at              TIMESTAMPTZ NULL,
    grace_until             TIMESTAMPTZ NULL,
    max_sites               INTEGER NOT NULL DEFAULT 0,
    enabled_features_json   TEXT NOT NULL DEFAULT '[]',
    snapshot_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wordpress_entitlements_org_connection
        UNIQUE (organization_id, connection_id)
);

CREATE INDEX IF NOT EXISTS ix_wordpress_entitlements_user_id
    ON wordpress_entitlements (user_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_entitlements_organization_id
    ON wordpress_entitlements (organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_entitlements_connection_id
    ON wordpress_entitlements (connection_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_entitlements_user_org
    ON wordpress_entitlements (user_id, organization_id);

CREATE TABLE IF NOT EXISTS wordpress_command_logs (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     INTEGER NOT NULL,
    connection_id       INTEGER NOT NULL REFERENCES wordpress_connections(id) ON DELETE CASCADE,
    command_type        VARCHAR(64) NOT NULL,
    direction           VARCHAR(16) NOT NULL DEFAULT 'saas_to_wp',
    payload_json        TEXT NOT NULL DEFAULT '{}',
    status              VARCHAR(32) NOT NULL DEFAULT 'queued',
    request_id          VARCHAR(64) NULL,
    error_message       TEXT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_user_id
    ON wordpress_command_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_organization_id
    ON wordpress_command_logs (organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_connection_id
    ON wordpress_command_logs (connection_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_org_connection_created
    ON wordpress_command_logs (organization_id, connection_id, created_at);
CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_user_org
    ON wordpress_command_logs (user_id, organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_command_logs_request_id
    ON wordpress_command_logs (request_id);

CREATE TABLE IF NOT EXISTS wordpress_request_idempotency (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     INTEGER NOT NULL,
    connection_id       INTEGER NULL REFERENCES wordpress_connections(id) ON DELETE CASCADE,
    idempotency_key     VARCHAR(128) NOT NULL,
    request_path        VARCHAR(255) NOT NULL DEFAULT '',
    response_code       INTEGER NULL,
    response_body_json  TEXT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wordpress_request_idempotency_org_key
        UNIQUE (organization_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_wordpress_request_idempotency_user_id
    ON wordpress_request_idempotency (user_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_request_idempotency_organization_id
    ON wordpress_request_idempotency (organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_request_idempotency_connection_id
    ON wordpress_request_idempotency (connection_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_request_idempotency_user_org
    ON wordpress_request_idempotency (user_id, organization_id);
CREATE INDEX IF NOT EXISTS ix_wordpress_request_idempotency_created
    ON wordpress_request_idempotency (created_at);

COMMIT;
