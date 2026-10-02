# Dataset Request Desk

**Live demo:** https://data-request-tracker.onrender.com — use the supplied accounts below. Free hosting can take a little longer to wake after inactivity.

[![Tests](https://github.com/MicoFaith/Data-request-tracker/actions/workflows/test.yml/badge.svg)](https://github.com/MicoFaith/Data-request-tracker/actions/workflows/test.yml)

A Python internal platform for robotics dataset requests, episode assignment and client delivery review. Built for the supplied Neotix technical test. The backend uses Django 5.2 with PostgreSQL for free public hosting or SQLite for the local demo, and committed Django migrations. The primary UI uses React, React Router, TanStack Query and Motion, built with Vite. It preserves the original teal, mint and dark-header palette. Django templates remain a functional fallback without JavaScript; HTMX loads only when the React build is absent.

This guide covers setup, demo accounts, everyday workflows, testing, implementation decisions and public-demo deployment.

## Start with one command

With Docker and Compose installed, from this directory:

```sh
docker compose up --build
```

Open http://127.0.0.1:8000. Startup applies migrations, creates the supplied users, imports the supplied episodes and collects static assets before Gunicorn starts. A named volume retains the SQLite database. A second service processes optional notification emails. Port 8000 is bound to the local computer. Restarting does not overwrite changed accounts or duplicate episodes.

Run all frontend tests, the production build, backend tests and migration checks with one command:

```sh
python scripts/test_all.py
```

The test runner creates and removes a separate test database. It never uses the demo database as the test database. To reset only the local Docker demo data deliberately: `docker compose down -v` (this deletes its data volume).

Docker Compose and the Python fallback have been verified locally. Current test results and remaining verification limits are listed below.

### Python fallback (no Docker)

Requires Python 3.12. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Then open http://127.0.0.1:8000. `run.py` brings up migrations, seed users/episodes, assets and the web/API server. The fallback development server is local only. Tests: `.venv/bin/python manage.py test --noinput` (Windows: `.\.venv\Scripts\python.exe manage.py test --noinput`). Dependencies are pinned in `requirements.txt`.

### React development and tests

Docker builds React automatically using Node 22 and the committed npm lockfile. To build locally, install Node 22.12+ and npm, then run:

```sh
cd frontend
npm ci
npm test
npm run build
cd ..
```

Then run `python run.py` using the virtual environment. Rebuild after frontend changes; `run.py` collects generated assets. Without a React build, Python startup uses server-rendered pages. Component tests run in jsdom and do not replace visual browser checks.

## Supplied demo users

| Role | Email | Password |
| --- | --- | --- |
| Admin | admin@example.com | admin123 |
| Operator | ops1@example.com | ops123 |
| Operator | ops2@example.com | ops123 |
| Client | client-a@example.com | client123 |
| Client | client-b@example.com | client123 |

These are the brief's demo credentials. Django hashes stored passwords; production would require replacing these accounts/passwords. Admin-created users require a password of 12-128 characters that is not entirely whitespace; password spaces are preserved. New login emails are limited to 150 characters to match the username field. The demo secret and insecure-cookie setting are local defaults, not production credentials. Configure `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and `COOKIE_SECURE=1` before any HTTPS deployment. Compose reads environment values or an optional `.env` based on `.env.example`. The Python fallback reads environment variables, not `.env` automatically.

## Role workspaces

The dashboard gives clients their own request totals and review shortcuts. Operators see new work, active fulfilment, rework and overdue requests; admins also get a people-management workspace. Search requests by task or number (staff can also search client names), sort by deadline, and jump from a metric card into the corresponding queue.

Episode inventory and user management include overview cards and filters. Request detail shows progress and the next action, while assignment submissions preserve the operator's filters. Forms show linked error summaries and inline errors without losing non-password inputs. Invalid filters and analytics dates remain editable on the same page. Navigation, keyboard focus, responsive layouts and optional JavaScript enhancements share a common interface; forms still work without JavaScript.

## Try the workflow

1. Log in as Client A, create a `pick cup` request for two episodes and sign out.
2. Log in as an operator, open the request and start fulfilment. Assign two matching good/usable episodes, then deliver.
3. Log in as Client A and accept or reject the delivery. If rejected, the operator can start rework, release/replace episodes and deliver again.
4. Client B cannot view/review Client A's request, including direct API URLs. Admins can manage users; existing sessions observe role/deactivation changes on the next request.
5. Operators can import another export on Episodes and see imported/skipped counts, reason totals and CSV line details. Filters support exact normalized task, quality and availability.

Optional local HTTP verification, while the app is running:

```sh
python scripts/smoke_test.py
```

This uses the supplied credentials and intentionally creates one demo request. It verifies actual sessions/CSRF, ownership, delivery threshold, assignment, rejection/rework, acceptance, audit events, health, analytics and HTML pages. It needs two unassigned good `pick cup` episodes; run on a fresh demo if the pool is exhausted.

## Verify every supplied user

While the app is running, run `.\.venv\Scripts\python.exe scripts\verify_roles.py` on Windows, or `.venv/bin/python scripts/verify_roles.py` on macOS/Linux. This checks both clients, both operators and admin using actual API sessions and HTML login/forms, including client isolation, delivery/rework, imports and admin user management. Each run adds two requests, eight test episodes and one deactivated test user; existing accounts and assignments are unchanged. It does not require unused seed episodes.

Additional HTTP checks while the app is running:

```sh
python scripts/verify_admin.py
python scripts/verify_react_assets.py
```

The admin check creates one temporary account, checks profile/email changes, validation, deletion and session revocation, then removes it. The asset check fetches the built React entry, stylesheets and staff chunk. These scripts do not test visual appearance. The backend suite also checks malformed UTF-8 headers, extreme timestamps and invalid durations in CSV uploads.

## REST API

All API routes and `/health` require a valid session except POST login and GET `/api/session/` (own login state, CSRF token and calendar dates only). Login and every write require CSRF protection. GET `/login/` establishes the CSRF cookie; submit it as `X-CSRFToken` with the session cookie. Django rotates the token on login, so use the updated cookie afterwards. The browser forms and smoke script handle this automatically. No JWT or client-supplied role/owner is trusted.

| Method | Route | Access / purpose |
| --- | --- | --- |
| POST | /api/login/ | email, password; start session |
| POST | /api/logout/ | end session |
| GET | /api/me/ | own identity (no password fields) |
| GET | /api/session/ | own login state, CSRF bootstrap and Kigali dates |
| GET | /api/dashboard/ | role-scoped request, inventory and people summaries |
| GET, POST | /api/requests/ | client own list/create; operators/admins list all |
| GET | /api/requests/{id}/ | visible request, assignments and status history |
| POST | /api/requests/{id}/status/ | `status`; actor and transition checks |
| POST | /api/requests/{id}/assignments/ | operator/admin, `episode_id` |
| DELETE | /api/requests/{id}/assignments/{episode_id}/ | operator/admin, release during in_progress |
| GET | /api/episodes/ | operator/admin; task_name, quality, available filters |
| POST | /api/episodes/import/ | operator/admin; multipart `file`, max 10 MiB |
| GET | /api/analytics/?start=YYYY-MM-DD&end=YYYY-MM-DD | operator/admin; inclusive Kigali dates |
| GET, POST | /api/users/ | admin list/create |
| PATCH, DELETE | /api/users/{id}/ | admin; edit profile/access or delete an unused account with email confirmation |
| GET | /health | authenticated DB probe; returns 503 on DB failure |

Create request JSON: `{"task_name":"pick cup","episodes_requested":2,"deadline":"2026-10-04","notes":"Cups only"}`. Replace the example deadline with a future date when testing. Owner comes from the session. List endpoints paginate 50 records with `page`, `total` and `has_next`. Validation errors are 422; access denials 401/403; invisible requests 404; conflicts/illegal state changes 409. CSRF failure is 403.

Each HTTP request logs one structured record with method, path (without query parameters), status, duration_ms and user_id when authentication can be resolved. Application errors use sanitized responses. Logs never include passwords, tokens or request bodies. Dynamic responses use no-store; HTMX history caching is disabled.

## Import rules and supplied-file result

IDs are trimmed and uppercased, robot/quality lowercased, task names casefolded with collapsed whitespace. Names retain casing. Naive timestamps mean Kigali; timezone-aware ISO timestamps retain their actual instant, stored in UTC. ISO timestamps and day/month/year hour:minute are accepted. The CSV must have the supplied seven columns in order, with a UTF-8/BOM-compatible encoding.

Reject unknown/missing robots, invalid/missing IDs/tasks/operators/quality/date, non-integer durations or durations outside 1–3600 seconds. Blank and short rows are skipped. A comma inside a correctly quoted task is valid. First valid occurrence of a canonical ID wins, including conflicting duplicates; existing records are never overwritten. Validation failures do not stop good rows. Unparseable CSV syntax/encoding aborts and rolls back that file.

The supplied file reads **191 data records: 172 imported, 19 skipped**. A second import adds zero episodes. Reports contain exact reason totals and up to 200 skipped-row examples; `unlisted_skips` states how many extra details were omitted. Imports process 500-row batches, look up only those IDs and bulk insert within one transaction. No query loads the entire episode inventory into Python.

## Domain and analytics decisions

Assignments may change only in `in_progress`. Episode task must match the normalized request task, and quality must be good/usable. A unique episode foreign key protects exclusivity. Rework keeps current assignments; operators can explicitly release/replace them after restarting. Accepted deliveries retain assignments. Delivery needs at least the requested count; extra assignments are allowed. Status and audit updates commit together.

Analytics episode counts/top tasks use recordings in the inclusive Kigali range. Request counts use the submission cohort in that range, grouped by current status. Median covers that cohort's first delivery (including a first delivery outside the range), excluding never-delivered requests; repeat delivery does not reset the timestamp. SQLite window ranking computes the median in SQL, including averaging the middle two values. Empty medians return null. Ties in top tasks sort by task name. New request deadlines must be tomorrow or later in Kigali time, enforced in HTML, API and the creation service. Existing deadlines are unchanged. The maximum requested count is 1,000,000.

### Five million episodes and production database

Queries filter the date interval before aggregation; lists are paginated. Migrations index `(recorded_at, robot_id)`, `(quality, recorded_at, task_name)`, and `(task_name, quality, episode_id)`, plus request submission/owner paths. These support range analytics and inventory filters; aggregates still scan matching rows and may be costly over long ranges. Query plans, realistic volume and load tests are needed; five million rows were not benchmarked here. Daily robot/task summary tables and cached reporting would reduce repeated broad scans.

Local SQLite uses `IMMEDIATE` transactions to acquire the writer lock before domain checks; a 20-second timeout bounds contention. Set `DATABASE_URL` for PostgreSQL: psycopg provides database connections, row locks protect requests/episodes, and transaction-scoped advisory locks serialize account maintenance and imports across rows. PostgreSQL uses `percentile_cont` for the database median. The full test command runs both database backends, including concurrency and analytics tests. Connections close between requests; server-side cursors are disabled for compatibility with Neon's pooled URL. Real production query plans and sustained load still need measurement.

## Verification, scope and source

Verification passed locally and in GitHub Actions: 110 backend tests on SQLite, the same 110 on PostgreSQL, 29 React component/API tests, the frontend production build and migration consistency. Fresh-database startup, the real HTTP delivery/rework and notification flows and served static assets have also been verified. Notification email tests use an in-memory backend and a mocked HTTPS transport; real provider delivery still needs configured credentials and an approved test mailbox.

The backend automated suite includes cross-client/role denials, active-session role changes, CSRF, valid/invalid transitions, audit rollback, N−1/N/N+1 delivery, unique/concurrent assignments, messy import/idempotency, SQL median/boundaries, pagination, logging/outage behavior, notification scoping, opt-in email, retry/lease recovery and client/operator templates. Test password hashing is intentionally fast inside test classes only; application seeds use Django's normal password hasher.

The deployment stretch is live on Render Free with Neon Free PostgreSQL. The public HTTPS walkthrough passed for all five supplied users, request delivery/rework, imports, analytics, full admin profile editing/deletion, notification isolation/read state and React assets. GitHub Actions CI runs on pushes and pull requests. Full visual browser QA remains outstanding. Seed CSV and account data are included in `seed/`.

AI tooling disclosure, as requested by the brief: Codex/ChatGPT helped implement the application, tests and documentation, and ran automated and HTTP checks. The published repository starts from a consolidated snapshot; its commit timestamps do not represent active development hours.

Primary references used: [Django databases](https://docs.djangoproject.com/en/5.2/ref/databases/), [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/), [Django CSRF](https://docs.djangoproject.com/en/5.2/ref/csrf/), [HTMX](https://htmx.org/docs/).


## Notifications and real email

Open **Notifications** in the navigation. The unread badge and inbox refresh every 30 seconds while the page is active; **Refresh** checks immediately. Use **Unread only**, **Mark as read**, or **Mark all as read**. Select an update's title to open the related request or workspace. Existing activity before this feature was installed is not backfilled.

| Activity | Recipients |
| --- | --- |
| Request submitted, status changed, episode assigned/removed | Owning client and active operators/admins |
| Episode import completed | Active operators/admins |
| User created, edited or deleted | Active admins |
| Welcome or own account edited | Affected active user |

Each role sees only its permitted updates. Downgrading a role hides earlier privileged notifications. Updates are saved in the same transaction as the action; failed actions create no notifications. The in-app inbox works without an email provider. The HTML fallback shows the latest 50 updates; live refresh, filters, read controls and preferences require the React build.

### Configure delivery

**Free Render deployment:** use Brevo's HTTPS API because Render Free blocks standard SMTP ports. Create a [Brevo Free account](https://www.brevo.com/), verify a sender, and set `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `DEFAULT_FROM_EMAIL`, `NOTIFICATION_EMAIL_RECIPIENTS` and `NOTIFICATION_EMAIL_ENABLED=1` in Render's environment settings. SMTP host/password fields are not used in this mode. The free provider has a daily send limit; verify your current allowance in its dashboard. Mail is queued durably in PostgreSQL, but delivery pauses while the free web service sleeps and resumes on wake-up.

For a local or Docker-server deployment with SMTP access:

1. Choose an SMTP provider, verify your sender/domain with that provider, and obtain its SMTP host, port and credentials. Configure the DNS records required by the provider for delivery.
2. For local Docker, copy `.env.example` to the ignored `.env`. For public Docker, use the ignored `.env.public`. Set `NOTIFICATION_EMAIL_ENABLED=1`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` (a plain verified sender address). Use the provider's TLS settings: usually port 587 with `EMAIL_USE_TLS=1`, `EMAIL_USE_SSL=0`, or port 465 with TLS=0 and SSL=1. Single-quote values containing dollar signs in Compose env files. Never commit credentials.
3. The public demo also requires `NOTIFICATION_EMAIL_RECIPIENTS`: comma-separated approved testing addresses. Shared demo accounts must not be allowed to email arbitrary recipients. Locally this list is optional. The public stack derives HTTPS links from `APP_DOMAIN`; locally set `APP_BASE_URL` to your actual application origin.
4. Restart both services with `docker compose up --build -d`, or the public command below. The `notifications` worker polls the durable queue every five seconds. With the Python fallback, export the same environment variables and run `python manage.py deliver_notifications --watch` in a second terminal; `.env` is not automatically loaded by Python.
5. As admin, create or update an account with the intended real address. Sign in to that account, open **Notifications**, select **Send activity alerts**, and save. Only new events after opt-in queue email. Changing the account email turns alerts off until the user opts in again. Opting out cancels queued messages; an email already being sent cannot be recalled.

Emails contain a secure link back to the inbox rather than private activity details. The worker checks current access, active status, preference, approved recipients and current address before sending. Failures retry with backoff, up to five attempts; an interrupted send is eligible again after ten minutes. A crash after SMTP acceptance may cause a duplicate, so this is not exactly-once delivery. A failed email never undoes the business action. Final failures appear on the corresponding inbox update. Monitor `docker compose logs --tail 50 notifications`; logs omit credentials and recipient addresses.

### Test as an end user

1. Open separate browser sessions for Client A, Client B, an operator and admin. Submit a request as Client A. Within 30 seconds, A and staff should see it; B should not.
2. Have the operator start work, assign an episode and deliver the requested amount. Check the client's inbox, open the request from its notification and accept/reject it. Mark updates read and verify the badge decreases after refresh.
3. As admin, create/edit/delete an unused account; verify admin account updates. Change a staff user's role to client and verify their old staff updates no longer appear.
4. After SMTP is configured for an approved mailbox, opt that user in and trigger new activity. Check the received email and its sign-in link. Turn email off and trigger another event: the in-app update should still arrive without another email. Provider acceptance alone does not establish inbox delivery; check the actual mailbox, including spam.

### Test as a developer

Run `python scripts/test_all.py` for the full Docker suite, or `python manage.py test desk.test_notifications desk.test_deployment --noinput` for focused backend checks. These tests do not send external mail. They cover recipient scoping, ownership, role changes, CSRF, read idempotency, pagination, atomic rollback, opt-in validation, address changes, cancellations, retry limits and interrupted-worker recovery. With the local demo running, `python scripts/verify_notifications.py` checks notifications through real HTTP sessions and intentionally creates one request. Real SMTP credentials, mailbox receipt and visual browser review remain external release checks.

The HTTP verification scripts also support hosted demos. Set `DESK_BASE_URL=https://data-request-tracker.onrender.com` before running them; they create synthetic test records and must be used only against an authorized demo environment. They send HTTPS origin/referrer headers for CSRF checks.

The notification API is authenticated and CSRF-protected for writes:

- `GET /api/notifications/?page=1&unread=true`: paginated inbox and unread count.
- `POST /api/notifications/`: `{"id":123}` or `{"all":true}` to mark read.
- `GET /api/notifications/preferences/`: own settings and email availability.
- `PATCH /api/notifications/preferences/`: `{"email_notifications":true}` or `false`.

The original interview brief is in `WORK_TASK.md`. Its written design, security, scale and tooling notes are consolidated into this README rather than the separate `NOTES.md` requested in the brief.

## Admin account maintenance

Admins can edit full names, email addresses, organisations, roles and account status. Email changes update the sign-in address; passwords and the user ID stay unchanged. Admins can edit their own profile while their access is protected. Unused accounts can be permanently deleted by typing the account email. Users referenced by requests, assignments or audit history must be deactivated instead; self-deletion and removing the last active admin are blocked. `PATCH /api/users/{id}/` accepts `name`, `email`, `organisation`, `role` and/or `is_active`. `DELETE` requires JSON `{"confirm_email":"user@example.com"}` and CSRF protection.

Startup seeding now runs once per database (`seed_demo --once`), preserving deliberate deletions across restarts. The new migration records that initialization. Manual `seed_demo` without `--once` explicitly restores missing seed accounts.

The GitHub Actions workflow runs `python scripts/test_all.py` on pushes and pull requests.

## Browser demo checks

1. Sign in with both client accounts and verify their requests stay separate. Try an empty task, a fractional episode count and today's deadline; correct the errors and submit once.
2. Use both operators to prepare a request, assign matching good/usable episodes and deliver it. Delivery must remain unavailable until the requested count is met. Have the client reject it, complete rework, then accept.
3. Import `seed/episodes.csv` twice. The second import must create no duplicates. Expand skipped-row results and review the reasons.
4. In Analytics, select **Last 90 days** to include historical seed recordings. Inspect chart bars, filter by robot and expand the exact data table. Try an invalid date range and correct it.
5. As admin, create a temporary account; edit its name, email, organisation, role and status. Check that the new email works for login. Delete this unused test account by typing its email. Accounts with history must be deactivated instead.
6. Test browser Back, refreshing filtered URLs, keyboard navigation, narrow screens and reduced-motion settings. Sign out and switch users; previous-account records must not remain visible.
7. If a connection fails during a save, check the current record after reconnecting before repeating the action.

## Implementation notes

State lives in the database. Requests belong to clients; assignments connect an episode exclusively to one request; status events record each transition's actor and time. Protected foreign keys preserve ownership and audit history. `desk/api.py` and the fallback HTML views call the same transactional services in `desk/services.py`.

Three main choices were Django sessions/CSRF instead of custom token authentication, SQLite for a reproducible single-instance demo, and analytics based on request submission cohorts and first delivery. Roles and active state are checked on each request. SQLite writer serialization and database uniqueness enforce assignment rules. First delivery remains unchanged after rework, while all subsequent transitions stay in the audit trail.

React components live in `frontend/src/`; shared forms and feedback are in `ui.jsx`, API requests in `api.js`, and role pages in `requests.jsx` and `staff.jsx`. Reads use TanStack Query; writes wait for the server and refresh relevant data. Account changes clear cached records. Staff screens load separately. Django templates remain a no-JavaScript fallback, at the cost of maintaining two renderers.

An outage test exposed a logging bug: after the health endpoint prepared a 503, resolving Django's lazy user object caused another query against the failed database. Middleware now catches that failure, logs a null user ID and preserves the sanitized response. A regression test covers it.

The main security concerns are cross-client access and misuse of cookie-authenticated sessions. Server-side ownership/role checks, CSRF, input validation, parameterized queries, escaped output and no-store responses address these boundaries. Passwords are hashed, and logs omit request bodies, passwords and tokens.

Real-time updates, export jobs, video delivery, email invitations and password reset are not implemented. The next priorities are visual browser sign-off, verified public hosting, login abuse controls, monitoring and PostgreSQL/load testing. At 10 times the users, SQLite writes and session traffic are likely bottlenecks; at 100 times the episodes, broad analytics and import/report work need attention. Query-plan measurement, pooling and daily aggregates would follow.

## Public demo deployment

### Render (recommended managed hosting)

The included `render.yaml` uses **Render Free** for the app and an external **Neon Free PostgreSQL** database for persistent records. There is no paid disk or paid service in the Blueprint. Render provides the HTTPS subdomain and generates the application secret. The web server and email worker run together under `scripts/serve.py`; if either exits unexpectedly, the supervisor stops the other and exits for the platform to restart the service.

1. Create a [Neon Free project](https://console.neon.tech/) in Ohio to match the web service. Copy its PostgreSQL connection string, including `sslmode=require`, from **Connect**. Keep it secret; the pooled URL is supported.
2. Open [Deploy on Render](https://render.com/deploy?repo=https://github.com/MicoFaith/Data-request-tracker), connect your GitHub account and choose the free service from the Blueprint. Paste the Neon connection string into the prompted `DATABASE_URL` secret. Keep both accounts on their free plans.
3. After deployment completes, use the actual HTTPS address shown by Render. No custom domain is required. The application reads `RENDER_EXTERNAL_HOSTNAME`; migrations and one-time seed setup run at startup. GitHub CI gates subsequent automatic deployments.
4. Configure the Brevo HTTPS email settings and approved recipients described above when ready. Email remains off until configured. Restart/redeploy after environment changes. Store secrets in Render, not GitHub source files.
5. Repeat the browser demo and mailbox checks. Verify that a restart preserves accounts and requests. The `/login/` route is the platform health probe; the authenticated `/health` endpoint remains available for application checks.

Render Free sleeps after 15 minutes without incoming traffic, so the first visit can be slow. Neon also scales down when idle; its storage/compute limits apply. Database records survive app restarts because they are stored separately. Email work pauses while the app is asleep. See [Render Free limits](https://render.com/docs/free), [Neon plans](https://neon.com/pricing) and [Blueprint settings](https://render.com/docs/blueprint-spec). Use PostgreSQL `pg_dump` backups and keep restricted off-platform copies. The current deployment uses the existing `data-request-robotics` Neon project in Ohio. Email delivery remains disabled until a Brevo key, verified sender and approved recipients are configured.

### Docker server alternative

For self-managed hosting instead of the live Render deployment, the included alternative uses a Docker server with a dedicated domain, persistent SQLite storage and a Caddy HTTPS proxy. Provision the server and domain before using this option.

1. Put the repository on the server and install Docker Compose.
2. Point the domain's DNS A record at the server. Add AAAA only if IPv6 is configured. Allow inbound TCP ports 80 and 443.
3. Copy `.env.public.example` to `.env.public`. Set `APP_DOMAIN` without a scheme. Generate a secret using `python -c "import secrets; print(secrets.token_urlsafe(64))"` and set `DJANGO_SECRET_KEY`. Keep this file private; it is excluded from Git and the Docker build context.
4. Start the standalone public stack:

```sh
docker compose --env-file .env.public -f compose.public.yaml up --build -d
docker compose --env-file .env.public -f compose.public.yaml logs --tail 40 web proxy
```

Do not merge this Compose file with the local one. It exposes only the proxy; the application port is private. Caddy manages HTTPS certificates once DNS and network access are ready. Production settings enforce Secure cookies, HTTPS redirects and explicit allowed hosts, and check deployment settings before startup. Database and certificate volumes persist across restarts.

This is a synthetic-data public demo with the supplied credentials, including admin access. A private production system needs individual credentials, disabled demo seeding, login abuse controls, monitoring and an agreed backup policy. Do not run multiple instances sharing this SQLite file.

After deployment, repeat the browser checks against the HTTPS URL and verify certificate validity and restart persistence. `/health` requires authentication; do not use it as an anonymous platform health probe.

### Backup and updates

Create a consistent SQLite backup and copy it off the server:

```sh
docker compose --env-file .env.public -f compose.public.yaml exec web python -c "import sqlite3; source=sqlite3.connect('/app/data/db.sqlite3'); target=sqlite3.connect('/app/data/backup.sqlite3'); source.backup(target); target.close(); source.close()"
docker compose --env-file .env.public -f compose.public.yaml cp web:/app/data/backup.sqlite3 ./backup.sqlite3
```

Keep dated, restricted off-server copies. Before upgrades, back up the database; migrations run on startup. For a restore, stop both the web and notifications services, preserve the current database, restore the chosen backup into the persistent data volume, then restart and verify it. Disable email while verifying a restored backup because it may contain previously sent outbox entries. Never use `down -v` for an ordinary update: it deletes data and certificate volumes.

### Troubleshooting

- Docker cannot connect: start Docker Desktop with Linux containers and retry.
- Port 8000 is occupied: stop the other service or change the local Compose port mapping.
- React changes are missing: rebuild with `docker compose up --build -d` and reload the browser.
- Login fails after an admin email change: use the new email and the existing password.
- A user cannot be deleted: requests or audit history reference the account; deactivate it instead.
- Seed users are not restored on restart: initialization runs once by design. Manual `seed_demo` without `--once` explicitly recreates missing seed accounts.
- Public startup fails: inspect logs and check the secret, allowed domain, DNS and port access.
