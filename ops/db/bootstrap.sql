-- One-time setup of the database roles. Run as a PostgreSQL superuser:
--
--   psql -U postgres -h localhost -f ops/db/bootstrap.sql -v dbname=payroll -v owner_pw=... -v rw_pw=... -v platform_pw=...
--
-- payroll_owner     owns the tables; runs migrations and the test suite (CREATEDB for the
--                   test DB). Not a superuser, so FORCE ROW LEVEL SECURITY applies to it too.
-- payroll_rw        what the running application connects as. No BYPASSRLS.
-- payroll_platform  platform jobs (backups, cross-tenant ops). BYPASSRLS; used only from
--                   platform modules, never from tenant request handling.
--
-- The database is created if missing; an existing (empty) one is handed to payroll_owner.
-- The roles are Payroll's own, so they never share privileges with another project's database
-- on the same server.

\set ON_ERROR_STOP on

CREATE ROLE payroll_owner LOGIN PASSWORD :'owner_pw' CREATEDB NOSUPERUSER NOBYPASSRLS;
CREATE ROLE payroll_rw LOGIN PASSWORD :'rw_pw' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE payroll_platform LOGIN PASSWORD :'platform_pw' NOSUPERUSER BYPASSRLS;

SELECT format('CREATE DATABASE %I OWNER payroll_owner ENCODING %L TEMPLATE template0', :'dbname', 'UTF8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname') \gexec
ALTER DATABASE :"dbname" OWNER TO payroll_owner;

\connect :"dbname"

-- PostgreSQL 15+: public is owned by pg_database_owner, i.e. payroll_owner from here on.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO payroll_rw, payroll_platform;

-- Every table and sequence payroll_owner creates from now on is usable by the other two roles.
-- No TRUNCATE, no DDL, no ownership: payroll_rw cannot disable RLS on anything.
ALTER DEFAULT PRIVILEGES FOR ROLE payroll_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO payroll_rw, payroll_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE payroll_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO payroll_rw, payroll_platform;
