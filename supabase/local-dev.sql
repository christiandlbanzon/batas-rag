-- Local-dev emulation of Supabase's PostgREST roles, for running the web app
-- against the docker pgvector database. NOT needed on real Supabase (it ships
-- these roles).

do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end $$;

grant usage on schema public to anon, service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;
