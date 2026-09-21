-- Create method_app LOGIN using the Supabase SQL console with your own strong password.
-- Run schema first with a migration owner, then run this with that same owner.
GRANT USAGE ON SCHEMA method TO method_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA method TO method_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA method TO method_app;
DO $$ DECLARE t RECORD; BEGIN
FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='method' LOOP
EXECUTE format('DROP POLICY IF EXISTS app_access ON method.%I',t.tablename);
EXECUTE format('CREATE POLICY app_access ON method.%I TO method_app USING(true) WITH CHECK(true)',t.tablename);
END LOOP; END $$;
-- Never expose method through Supabase Data API or grant access to anon/authenticated roles.
