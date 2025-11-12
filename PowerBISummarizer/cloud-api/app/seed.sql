-- Enable pgcrypto so we can hash passwords using bcrypt (bf)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS layers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    schema TEXT NOT NULL DEFAULT 'public',
    srid INT NOT NULL,
    geom_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO users (email, password_hash, role)
VALUES ('admin@demo.dev', crypt('demo123', gen_salt('bf')), 'admin')
ON CONFLICT (email) DO NOTHING;

INSERT INTO layers (name, schema, srid, geom_type)
VALUES
    ('redes_esgoto', 'public', 31984, 'LINESTRING'),
    ('pocos_bombeamento', 'public', 31984, 'POINT'),
    ('bairros', 'public', 31984, 'MULTIPOLYGON')
ON CONFLICT (name) DO NOTHING;
