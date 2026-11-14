# DEPLOY_HELPER — RMS: GitHub → Supabase → Render

Your step-by-step checklist for putting RMS online. Work top to bottom and tick each box.
Total time: about 2 hours.

> **Golden rules**
> 1. Secrets (DB password, `service_role` key, `rms_api` password) go **only** into your password manager and Render's
>    environment variables. Never put them in Git, chat, tickets or any `frontend` variable.
> 2. **Never** run `supabase db reset`, `supabase db push --include-seed`, `scripts/reset-db.*` or `scripts/uat-reset.*`
>    against production. They wipe data or create test accounts.
> 3. The GitHub repository must be **Private**. It contains your party and product master data.

---

## 0. Before you start (10 min)

**Accounts:** GitHub · Supabase (supabase.com) · Render (render.com, sign in with GitHub).

**On this PC:** Git, Docker Desktop (running), Supabase CLI, Python. All are installed already.

**Your values sheet.** Keep this in your password manager and fill it in as you go:

| # | Value | Where you get it | Secret? |
|---|---|---|---|
| V1 | Supabase project ref (e.g. `abcdwxyz…`) | Supabase → Project Settings → General | no |
| V2 | Supabase DB password | you create it in step 2.1 | **YES** |
| V3 | Supabase URL `https://<V1>.supabase.co` | Project Settings → API | no |
| V4 | anon key (public) | Project Settings → API Keys → **Legacy API keys** tab | no |
| V5 | service_role key | same tab ("Reveal") | **YES** |
| V6 | Pooler host `aws-<n>-ap-south-1.pooler.supabase.com` | **Connect** button → Session pooler | no |
| V7 | `rms_api` password (32 random letters + digits only) | you generate it in step 2.6 | **YES** |
| V8 | API URL, e.g. `https://rms-api.onrender.com` | Render, step 3.1 | no |
| V9 | Frontend URL, e.g. `https://rms-web.onrender.com` | Render, step 3.3 | no |

> Use **letters and digits only** for V2 and V7. Symbols like `@ : / # ?` break connection strings.

**Known gap. Read this before going live:**
- The Admin **Form Builder** and **Option Sets** screens (`frontend/src/lib/api/configApi.ts`, audit item B3) do not
  send the login token yet, so they will fail in production. Everything else works. Ask Claude to finish
  "Production Phase 3 (frontend)" first if you need those screens on day one.

---

## 1. GitHub: create the repo and push (15 min)

### 1.1 Create the empty repository (browser)
- [ ] github.com → **+** → **New repository**
- [ ] Name: `rms` · Visibility: **Private**
- [ ] Leave README, .gitignore and license **unticked** (the repo must be empty) → **Create repository**
- [ ] Copy the HTTPS URL: `https://github.com/<your-user>/rms.git`

### 1.2 Run the safety checks (PowerShell, in `C:\Kuldeep510V07\RMS--`)
```powershell
.\scripts\check-secrets.ps1          # must pass
git add --dry-run . | Select-String -CaseSensitive -Pattern "\.env'|\.env\.local|CREDENTIALS|\.csv'|frontend/x/"
```
- [ ] The second command must print **nothing**. If it prints a file, stop and ask Claude.

### 1.3 First commit and push
```powershell
git add .
git status                           # skim the list: no backend/.env, no RMS_USER_CREDENTIALS.txt
git commit -m "RMS initial commit"
git branch -M main
git remote add origin https://github.com/<your-user>/rms.git
git push -u origin main
```
- [ ] A browser window asks you to sign in to GitHub the first time (Git Credential Manager). Approve it.
- [ ] Refresh the repository page on GitHub. Confirm that `backend/`, `frontend/` and `supabase/` are there, and that
      **no** `.env` or `RMS_USER_CREDENTIALS.txt` file appears anywhere.

---

## 2. Supabase: create the production database (40 min)

### 2.1 Create the project
- [ ] supabase.com → **New project** · Plan **Free** · Region **South Asia (Mumbai)**
- [ ] Database password → generate one (letters and digits) → save as **V2** → **Create**
- [ ] Wait until the project shows "Healthy". Note **V1** and **V3**.

### 2.2 Dashboard settings
- [ ] **Authentication → Sign In / Providers → Email**: enabled. **Allow new users to sign up: OFF**.
- [ ] **Authentication → Providers → Email**: minimum password length **8**, require **letters and digits**.
- [ ] **Authentication → JWT Keys**: must show an **asymmetric** current key (ECC/RSA). If it says "Legacy JWT secret",
      click **Migrate JWT secret**, then **Rotate keys**.
- [ ] **Database → Settings → SSL**: **Enforce SSL** on.
- [ ] **Storage → Settings**: global file size limit = **50 MB** (the Free maximum).
- [ ] **Project Settings → API Keys → Legacy API keys**: copy **anon** → V4 and **service_role** → V5.
- [ ] **Connect** (top bar) → **Session pooler**: copy the host → V6.

### 2.3 Link the repo and apply the schema (PowerShell, repo root)
```powershell
supabase link --project-ref <V1>          # enter V2 when asked
supabase db push --dry-run                # must list 52 migrations, nothing else
supabase db push                          # type Y.  NEVER add --include-seed
```
- [ ] The push finishes without errors.

### 2.4 Load the reference data and master data (once only)
Start the local stack first, because its container provides `psql`: `supabase start`.
Then, in **Git Bash** (not PowerShell), from the repo root:
```bash
python scripts/build_production_seed.py
ADMIN_URL="postgresql://postgres.<V1>:<V2>@<V6>:5432/postgres?sslmode=require"
docker exec -i supabase_db_rms psql "$ADMIN_URL" -X -v ON_ERROR_STOP=1 < supabase/.temp/production_seed.sql
```
- [ ] It ends with `COMMIT`. If it errors, nothing is saved, so fix the problem and re-run it.

### 2.5 Free-plan upload limit
Supabase → **SQL Editor** → New query → run:
```sql
update public.system_settings set value = '52428800' where key = 'upload_max_video_bytes';
```

### 2.6 Give the API role its password
Generate V7 (32 letters and digits). In the SQL Editor:
```sql
alter role rms_api with password '<V7>';
alter role rms_api set statement_timeout = '30s';
```

### 2.7 Verify (Git Bash)
```bash
docker exec -i supabase_db_rms psql "$ADMIN_URL" -X -v ON_ERROR_STOP=1 < scripts/verify_production_db.sql
```
- [ ] Every row shows `ok = t`, **except** "at least one Super Admin". That one turns true after step 5.

**Your API connection string (keep it secret):**
```
postgresql://rms_api.<V1>:<V7>@<V6>:5432/postgres?sslmode=require
```

---

## 3. Render: create three services (30 min)

### Option A: Blueprint (recommended, 10 min)
`render.yaml` in the repo defines all three services with the right commands, plans, headers and SPA rewrite.
- [ ] Render → left sidebar **Blueprints** → **New Blueprint Instance** (or open
      `https://dashboard.render.com/select-repo?type=blueprint`) → select the `rms` repo, branch `main` →
      Blueprint name `rms`. (Blueprint is not one of the service tiles on the "New" page.)
- [ ] Render asks for every value marked `sync: false`. Fill them in from the tables in 3.1–3.3 below. For SMTP, leave
      all values empty if you don't use e-mail yet. For `CORS_ORIGINS`, `APP_PUBLIC_URL` and `VITE_API_BASE_URL`, use
      the expected URLs (`https://rms-web.onrender.com` and `https://rms-api.onrender.com`). Correct them in step 4 if
      Render assigns different ones.
- [ ] **Apply**. Wait for all three services to deploy. Note the real URLs as **V8** (`rms-api`) and **V9**
      (`rms-web`). Open `<V8>/health/ready` and check that it shows `"database":"ok"`. Then go to step 4. The
      rewrite rule and headers are already set by the Blueprint.

### Option B: create the services by hand
Use this only if the Blueprint fails. In every service: **Connect repository** → `rms` · Branch `main` ·
Region **Singapore** · **Auto-Deploy: Off**.

### 3.1 Backend API (New → **Web Service**)
| Field | Value |
|---|---|
| Name | `rms-api` |
| Language | Python 3 |
| Root Directory | `backend` |
| Build Command | `pip install --upgrade pip uv && uv export --frozen --no-dev --no-emit-project -o requirements.txt && pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*" --no-server-header` |
| Instance type | **Starter** (recommended; Free sleeps after 15 min idle and takes ~1 min to wake up) |
| Health Check Path (Advanced) | `/health/ready` |

**Environment variables:**
| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.16` |
| `APP_ENV` | `prod` |
| `DATABASE_URL` | the API connection string from the end of step 2 |
| `SUPABASE_URL` | V3 |
| `SUPABASE_SERVICE_ROLE_KEY` | V5 |
| `CORS_ORIGINS` | `https://rms-web.onrender.com` (temporary; corrected in step 4) |
| `APP_PUBLIC_URL` | same as `CORS_ORIGINS` |
| `DB_POOL_SIZE` | `5` |
| `DB_MAX_OVERFLOW` | `5` |
| `TZ` | `Asia/Kolkata` |
| `LOG_LEVEL` | `INFO` |

- [ ] **Create Web Service** → wait until it shows "Live". Save the URL as **V8**.
- [ ] Open `<V8>/health/ready` in a browser. Expected result: `"database":"ok"`.

### 3.2 Background worker (New → **Background Worker**)
Runs notifications, emails, SLA escalation and nightly checks. Render has **no free plan** for workers
(Starter, about $7/month).

| Field | Value |
|---|---|
| Name | `rms-worker` |
| Root Directory | `backend` |
| Build Command | same as 3.1 |
| Start Command | `python -m app.worker` |

Environment variables: the **same as 3.1**, except `DB_POOL_SIZE=2` and `DB_MAX_OVERFLOW=2`.
Email is optional. To turn it on, add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM`.
- [ ] The logs show the scheduler starting, with no errors.

### 3.3 Frontend (New → **Static Site**)
| Field | Value |
|---|---|
| Name | `rms-web` |
| Root Directory | `frontend` |
| Build Command | `npx --yes pnpm@9.15.9 install --frozen-lockfile && npx --yes pnpm@9.15.9 build` |
| Publish Directory | `dist` |

**Environment variables** (public values only, **never** V2/V5/V7):
| Key | Value |
|---|---|
| `NODE_VERSION` | `22` |
| `VITE_API_BASE_URL` | V8 (no trailing slash, no `/api/v1`) |
| `VITE_SUPABASE_URL` | V3 |
| `VITE_SUPABASE_ANON_KEY` | V4 |

After creating it:
- [ ] **Redirects/Rewrites** → Add rule: Source `/*` · Destination `/index.html` · Action **Rewrite**
- [ ] **Headers** → Path `/*`: `X-Content-Type-Options: nosniff` · `X-Frame-Options: DENY` ·
      `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] Save the site URL as **V9**.

---

## 4. Connect everything (5 min)

- [ ] Render → `rms-api` **and** `rms-worker` → Environment: set `CORS_ORIGINS` and `APP_PUBLIC_URL` to **V9**
      exactly (`https://…`, no trailing slash) → **Save, rebuild and deploy**.
- [ ] Supabase → **Authentication → URL Configuration**: Site URL = **V9** · Redirect URLs = **V9** only.

---

## 5. Create the first Super Admin (5 min)

PowerShell, from `C:\Kuldeep510V07\RMS--\backend`. The values live in this window only and disappear when you close it:
```powershell
$env:APP_ENV="prod"
$env:DATABASE_URL="postgresql://rms_api.<V1>:<V7>@<V6>:5432/postgres?sslmode=require"
$env:SUPABASE_URL="<V3>"
$env:SUPABASE_SERVICE_ROLE_KEY="<V5>"
$env:CORS_ORIGINS="<V9>"
.\.venv\Scripts\python.exe scripts\bootstrap_super_admin.py
```
- [ ] Enter a **real** e-mail address and a strong password (asked twice). Close the PowerShell window afterwards.
- [ ] Run step 2.7 again. **All** rows must now show `ok = t`.

---

## 6. Go-live smoke test (10 min)

- [ ] Open **V9** on desktop: sign in as the Super Admin. The browser console (F12) shows no red errors.
- [ ] **Administration → Users**: create one real user. Sign in as that user in a private window. RMS forces a
      password change.
- [ ] Open a party lookup and a product lookup. Data appears.
- [ ] Open **V9** on a phone. The sign-in and home screens fit the screen width.
- [ ] Upload one small photo or document on a test entry. It saves and opens again.
- [ ] Render → `rms-api` → Logs: no errors.

---

## 7. If something goes wrong

| Symptom | Fix |
|---|---|
| `supabase db push` stops partway with an error | Migrations that already succeeded stay applied. Fix the cause (ask Claude, paste the error), then run `supabase db push --dry-run` and `supabase db push` again. It continues from the failed file. |
| API won't start: "sslmode=require" | `DATABASE_URL` must end with `?sslmode=require`. |
| API won't start: password or tenant error | Check the user is `rms_api.<V1>`, the host is the **session** pooler on port **5432**, and V7 matches step 2.6. |
| Browser: "CORS" error | `CORS_ORIGINS` must equal V9 exactly (https, no slash). Redeploy the API. |
| Login works but every page errors with 401 | JWT keys are not asymmetric (step 2.2), or `SUPABASE_URL` is wrong. |
| Refreshing a page shows "Not Found" | The rewrite rule from step 3.3 is missing. |
| Frontend calls `localhost:8000` | `VITE_API_BASE_URL` was missing at build time. Set it, then **Manual Deploy → Clear build cache & deploy**. |
| Site stops working after a quiet week | The Free Supabase project paused. Dashboard → **Restore project**. |

---

## 8. Every later release

1. Back up: `supabase db dump --linked -f backups/prod-<yyyymmdd>-schema.sql` and
   `supabase db dump --linked --data-only -f backups/prod-<yyyymmdd>-data.sql` (Free has **no** automatic backups).
2. `git push` the new code.
3. `supabase db push --dry-run` → only the **new** migrations may appear → `supabase db push`.
4. Render → `rms-api`, `rms-worker` and `rms-web` → **Manual Deploy → Deploy latest commit**.
5. Run step 2.7 and the smoke test in step 6.

Full background: [docs/DATABASE_MIGRATION_GUIDE.md](docs/DATABASE_MIGRATION_GUIDE.md) · [docs/PRODUCTION_AUDIT.md](docs/PRODUCTION_AUDIT.md)
