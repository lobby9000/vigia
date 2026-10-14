-- =============================================================================
-- Vigia | Reference data for local development
--
-- Every demo application gets a predictable API key: dev-key-<code>
-- (for example dev-key-payments-api). Only its SHA-256 hash is stored, the
-- same way the ingest service stores keys it generates. Never use these
-- keys outside your laptop: real applications are registered through
-- POST /api/v1/applications, which returns a random key exactly once.
-- =============================================================================

BEGIN;

INSERT INTO teams (name) VALUES
    ('Payments'),
    ('E-commerce'),
    ('Identity'),
    ('Customer'),
    ('Platform');

INSERT INTO applications (code, name, team_id, tier, slo_availability, slo_latency_p95_ms, api_key_hash)
SELECT
    v.code,
    v.name,
    t.id,
    v.tier,
    v.slo_availability,
    v.slo_latency_p95_ms,
    encode(sha256(convert_to('dev-key-' || v.code, 'UTF8')), 'hex')
FROM (VALUES
    ('payments-api',      'Payments API',       'Payments',   1, 0.99950,  600),
    ('checkout-web',      'Checkout Web',       'E-commerce', 1, 0.99900,  900),
    ('login-service',     'Login Service',      'Identity',   1, 0.99950,  400),
    ('catalog-api',       'Catalog API',        'E-commerce', 2, 0.99500,  700),
    ('loyalty-api',       'Loyalty Points API', 'Customer',   2, 0.99500,  800),
    ('notifications-api', 'Notifications API',  'Platform',   3, 0.99000, 1500)
) AS v (code, name, team, tier, slo_availability, slo_latency_p95_ms)
JOIN teams t ON t.name = v.team;

COMMIT;
