-- Rollback: 20260722_wordpress_plugin_connections
BEGIN;
DROP TABLE IF EXISTS wordpress_request_idempotency CASCADE;
DROP TABLE IF EXISTS wordpress_command_logs CASCADE;
DROP TABLE IF EXISTS wordpress_entitlements CASCADE;
DROP TABLE IF EXISTS wordpress_pairing_codes CASCADE;
DROP TABLE IF EXISTS wordpress_connections CASCADE;
COMMIT;
