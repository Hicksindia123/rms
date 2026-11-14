# supabase/

- `migrations/` — timestamped SQL; the **only** schema source of truth. Never edit an applied migration; add a new one.
- `seed.sql` — reference seed + demo block between the `-- DEMO:BEGIN` / `-- DEMO:END` lines (stripped for remote; see docs/SETUP.md).
- `tests/` — pgTAP tests run with `supabase test db`.
- `config.toml` — created by `supabase init` in P1-02 (project_id `rms`, public sign-up disabled, site URL http://localhost:5173).
- New tables in later migrations: call `select rms_private.attach_standard_triggers('public.<table>');` and enable RLS (see docs/ARCHITECTURE.md).
