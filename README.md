# Author Portfolio

A responsive author website with a FastAPI/MongoDB API and a secure Admin Panel for published works, public profile content, and gallery images. Sample author data and image URLs are placeholders.

## Run locally

Install Node.js 20.9 or later, Python 3.11 or later, and MongoDB Community Server. Start MongoDB, then open a PowerShell terminal in this project folder.

```powershell
npm install
Copy-Item .env.local.example .env.local
Copy-Item server/.env.example server/.env
```

Set `APP_ENV=development` in `server/.env`, use `MONGODB_URI=mongodb://127.0.0.1:27017/evelyn-hart-portfolio`, and set the frontend/site URL to `http://localhost:3000`. Keep `NEXT_PUBLIC_API_URL` empty for the default same-origin API proxy; `API_SERVER_URL` should point to the backend origin (default `http://127.0.0.1:4000`). Generate independent, stable values for `JWT_SECRET`, `DATA_ENCRYPTION_KEY`, and `EMAIL_INDEX_SECRET`; do not rotate the encryption or email-index keys without migrating encrypted database fields and indexes. Set `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` of at least 12 characters. On first startup, the password is Argon2id-hashed into MongoDB and an administrator account is created. Configure a dedicated SMTP relay using its exact `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, and `SMTP_FROM` values, plus both `SMTP_USERNAME` and `SMTP_PASSWORD` if authentication is required. For Google Workspace SMTP Relay, use the relay host and authentication method authorized by your Workspace administrator; sender addresses must be permitted by that relay. After editing `server/.env`, restart the API for changes to take effect. Verification and password-reset codes are not sent until this relay is configured; do not disable email verification to work around missing SMTP. Never use your primary Google account password as SMTP credentials.

If Google Workspace closes the SMTP connection during authentication, verify in the Workspace Admin console that SMTP AUTH is enabled for the relay, the authenticating account is allowed to use it, and the sender address is authorized. If the relay is configured for public-IP allowlisting instead, allowlist the API server's public IP and leave `SMTP_USERNAME` and `SMTP_PASSWORD` empty. A personal Gmail account may need Gmail's SMTP service and a Google App Password instead of the Workspace relay; do not substitute the primary Google account password.

If the relay accepts authentication but returns `550 5.7.0 Mail relay denied`, its policy is rejecting the envelope sender domain or the API server's public egress IP. Register/authorize the sender domain and egress IP in Google Workspace, or use an authorized Workspace sender. Consumer `@gmail.com` addresses are not Workspace-owned domains; use Gmail SMTP with an App Password for a personal Gmail mailbox.

Keep `NEXT_PUBLIC_API_URL` empty and set `API_SERVER_URL=http://127.0.0.1:4000` in `.env.local`. Next.js proxies browser `/api/*` requests to that backend origin, keeping admin session cookies same-origin. For a separately hosted API, set `NEXT_PUBLIC_API_URL` to its public HTTPS origin before building the frontend. Then start two PowerShell terminals:

```powershell
# Terminal 1 — website
npm run dev

# Terminal 2 — FastAPI
npm run api
```

Open `http://localhost:3000`. The API seeds sample published works the first time its catalog is empty. Sign in at `/admin` using the bootstrap admin email and password. `npm run api` locates Python 3.11+, installs `server/requirements.txt` if needed, then starts Uvicorn; `npm run check --prefix server` runs syntax checks and security unit tests. Interactive API docs are available at `/api/docs` in development only. If SMTP settings are incomplete, admin verification and password reset will report which server settings to configure.

## Admin Panel

`/admin` is the protected Admin Panel. It uses rate-limited login and a server-set HttpOnly, SameSite JWT session cookie with server-side revocation. Passwords use Argon2id; legacy bcrypt hashes are upgraded at login. Admin APIs require an admin-issued session, re-check the active user and role on each request, enforce origin checks on writes, validate editable fields and write an activity log. Roles are `admin`, `manager`, `editor` and `support`, with distinct API permissions. Only the email configured in `ADMIN_EMAIL` can sign in to or use the Admin Panel; other staff accounts cannot access it even if assigned an admin-capable role.

Admin sign-in uses the bootstrap administrator email and password from `server/.env`. A newly created admin, and the existing bootstrap admin on the first startup after this update, must verify the configured email address using a time-limited, one-time code before signing in. The configured email can be changed through `ADMIN_EMAIL`; on API startup the bootstrap account is updated, its email verification is cleared, and existing sessions are revoked. `ADMIN_PASSWORD` is used to initialize the password hash when the account is first created; use **Forgot password?** in the Admin Panel to change an existing password. Password reset codes expire after 10 minutes, can only be used once, and revoke all active sessions.

The admin email/password are separate from any mail-relay credentials. The local `server/.env` is ignored by Git; keep it private and use a unique password. Never use a Gmail password as the admin password or SMTP password.

Existing MongoDB data is preserved; no historical collections are deleted. The API migrates sensitive legacy fields to application-level encryption. Database backups should be protected and encrypted independently. Keep the encryption and email-index secrets stable and backed up.

The Admin Panel includes a portfolio overview, Home/About/Contact editors, published works, a curated public gallery, Site Settings & SEO, team and roles, and a searchable activity log. Editors can add, edit, publish/unpublish, and delete works; gallery images can be published or hidden. Gallery assets are HTTPS image URLs; files are not uploaded or served by this app. Site Settings controls the browser/search title, SEO description, and social-sharing image. Contact content controls public social links, including Facebook, Instagram, and LinkedIn. Public metadata is rendered by Next.js from the published settings; the open portfolio picks up published changes within 20 seconds (polling pauses while the tab is in the background). Publish profile content through `/api/admin/content/:key` with `public: true`; only public content is exposed by `/api/content`. The public gallery contains only media records marked public and categorized as `gallery`.

To customize the sample author profile from the dashboard, use the Home, About, and Contact editors. They save the public `author-profile` document, which contains author text, images, contact information, and supported social URLs. Site Settings & SEO saves the separate public `site-settings` document. Published works are loaded from the Admin Panel; drafts remain private.

## Online Bookstore

The separate `/store` page adds a searchable, category-filtered catalogue, book details, a persistent shopping bag, and guest checkout in Nepalese rupees. The existing portfolio sections and published-work presentation remain unchanged; the portfolio navigation only gains a Bookstore link. Store products reuse published book records, so set a category, NPR price, and stock quantity under **Admin Panel → Store inventory** before a published work is available to purchase. Unpriced works stay out of the storefront; existing records are not assigned invented prices or inventory.

Checkout reserves stock on the API and calculates prices from MongoDB, not from browser totals. Published works remain browseable before pricing is configured, but cannot be purchased until an administrator sets a positive NPR price and stock quantity. eSewa and Khalti checkout sessions are initiated server-side and their callbacks are verified against the provider before an order is marked paid. Bank transfer is enabled after configuring the bank name, account holder, and account number under **Admin Panel → Store settings**. Bank-transfer orders remain pending until an administrator checks the bank statement and confirms the payment in **Payments**; customers cannot mark their own transfer paid. Bank account numbers are encrypted in the database, and order/customer contact fields use the existing application-level encryption.

Configure payment credentials in `server/.env` (or the backend secret manager), never in a `NEXT_PUBLIC_*` variable:

```text
ESEWA_MODE=test
ESEWA_TEST_PRODUCT_CODE=...
ESEWA_TEST_SECRET_KEY=...
KHALTI_MODE=test
KHALTI_TEST_SECRET_KEY=...
```

Use the provider-issued test credentials for test mode. For production, set each provider's mode to `live` and supply its separate `ESEWA_LIVE_PRODUCT_CODE`, `ESEWA_LIVE_SECRET_KEY`, or `KHALTI_LIVE_SECRET_KEY`. Live payments require public HTTPS frontend/API URLs and provider callbacks that can reach the API. Store availability is shown at checkout only when the selected payment method is configured. The backend sends order-received, payment-confirmed, and order-status emails using the configured SMTP relay; mail delivery failures are logged and do not reverse a recorded order or payment. Customer order status is available through the checkout's short-lived HttpOnly tracking cookie.

The storefront has a catalogue at `/store` (search, category filters, sorting, in-stock filter), a shareable page per book at `/store/books/:id` with SEO metadata and related titles, a shared bag and two-step checkout, and an order page at `/store/orders/:id` showing a progress timeline, status history, shipment tracking and bank-transfer instructions. Customers can report their bank-transfer reference from the order page; this notifies the administrator but never marks the order paid. `/store/track` lets customers reopen an order with its reference and checkout email, which sets a 30-day, order-scoped HttpOnly cookie.

The Admin Panel groups the bookstore under **Store dashboard** (KPIs, tasks needing attention, recent activity, 30-day sales), **Orders** (status filters, an order drawer with customer, items, payment and timeline; paid → processing → shipped (carrier and tracking number) → delivered; cancelling a paid order restocks it and marks a refund as due until **Record refund**), **Payments** (provider verification and a checked confirmation dialog for bank transfers, showing the customer-reported reference), **Inventory & prices** (stock value, low-stock filters, audited stock adjustments that cannot go below zero), **Categories** (ordering, hiding, renaming moves books, deletion only when empty), **Customers** (order counts, lifetime spend, order history), **Sales reports** (monthly and daily revenue, best sellers, payment-method mix, CSV export of orders) and **Store & bank settings**. A notification bell polls for new orders, confirmed payments, reported bank transfers and low-stock alerts. Customers receive status emails, including any note and tracking number. Store/order/payment/customer/report endpoints are restricted to the configured administrator; existing staff roles do not gain commerce access (editors can manage categories through `books:write`).

## Customer accounts

Shoppers can create an account at `/store/account`. Sign-up sends a 6-digit email code (via the SMTP settings) and the account is usable once the address is verified. Signed-in shoppers get checkout pre-filled with their saved delivery details, their email fixed to the verified address, and every order listed under **My account**; earlier guest orders placed with the same email join the account after verification. Customers can update delivery details, change their password (signing out other devices) or reset a forgotten password by email code. Customer sessions use the `store_session` HttpOnly cookie and never grant Admin Panel access; staff accounts cannot sign in through the storefront. In the Admin Panel, **Customers → Registered accounts** lists shopper accounts with their order counts and lets the administrator suspend (sign out and block) or reactivate an account.

On first start after this update, the four bundled sample books are given a price, 25 copies of stock and a store category (Novel or Essays) if those fields are empty. This runs once; prices and stock an administrator sets are never overwritten.

## Maintenance mode

**Admin Panel → Maintenance mode** switches the public website off and on. When it is ON, every public page (portfolio, store, book pages, account and order pages) is answered with a maintenance page and an HTTP 503 status (so search engines do not index it), and the public API (catalogue, checkout, sign-in, content) returns 503 too, so nothing can be ordered directly. The Admin Panel, health checks and eSewa/Khalti payment callbacks stay available, so payments already in progress still settle. An optional message and "expected back" time (shown as a live countdown) can be set. The maintenance page checks every 15 seconds and returns visitors to the page they wanted as soon as maintenance is turned OFF. Enforcement happens in `proxy.js` (website) and the API middleware; if the maintenance status cannot be read, the site stays online rather than locking visitors out.

## Backup & restore

**Admin Panel → Backup & restore** (administrator role only) has two actions:

- **Download backup** saves `binodmahato_backup_data.zip`. It contains every database collection (books, users and team, customers, orders, payments, reviews, categories, website content, media/gallery, store and site settings, newsletter, notifications, activity log) in MongoDB Extended JSON under `database/`, copies of the book-cover, gallery and website images under `images/`, and a `manifest.json` with SHA-256 checksums signed by `manifest.sig`. Login sessions are not included. Personal details stay encrypted as they are in the database, and passwords are included only as hashes. Even so, keep the file private.
- **Restore backup** checks the file first: size (200 MB maximum), ZIP structure, an exact file allow-list (which blocks path traversal), zip-bomb ratios, the HMAC signature, every checksum, and every record. It then shows what the backup contains. Restoring requires typing `RESTORE`. All current data is replaced and missing collections are emptied. If anything fails partway, the previous data is put back automatically. The signed-in administrator keeps their account and session, and every other session is signed out. Restores are audited.

Backups are signed with a key derived from `DATA_ENCRYPTION_KEY` and `EMAIL_INDEX_SECRET`, so a backup restores only on a server that uses the same two secrets. Keep those secrets with your backups. Image downloads only reach public HTTPS hosts; images that cannot be fetched are listed in `images/index.json` and do not stop the backup.

## Light and dark mode

The homepage and bookstore headers have a sun/moon button. The site's signature forest-green and gold look is the default for first-time visitors; choosing light mode is saved in the browser (`localStorage` key `site-theme`) and applied before the page paints, so there is no flash of the wrong theme. The switch animates with a circular reveal where supported (a cross-fade otherwise; instant for reduced-motion users). The theme applies to the portfolio and every bookstore page (catalogue, book pages, bag, checkout, accounts and order tracking); the Admin Panel keeps its own design with the shared book-and-pen logo.

## API notes

- `GET /api/books`, `/api/gallery`, and `/api/content` are the public portfolio read endpoints. `GET /api/store/books` returns published works and their store availability; `GET /api/store/settings` exposes the configured public bank-transfer details and payment-method availability.
- Store checkout uses `POST /api/payments/nepal/esewa/initiate`, `POST /api/payments/nepal/khalti/initiate`, or `POST /api/orders/bank-transfer`. Provider callbacks and `GET /api/payments/nepal/track/:orderId` verify and report order status.
- `GET /api/site/status` reports maintenance mode for the website; `GET`/`PUT /api/admin/maintenance` reads and switches it (administrator only).
- Customer accounts: `POST /api/auth/register`, `/verify-email`, `/resend-verification`, `/login`, `/logout`, `/password/request`, `/password/reset`; `GET /api/auth/me`; `GET /api/account/orders`, `PATCH /api/account/profile`, `POST /api/account/password`. Admin: `GET /api/admin/accounts`, `PATCH /api/admin/accounts/:id`.
- `GET /api/store/books/:id` returns one published book with related titles. `POST /api/orders/lookup` (order id + checkout email) unlocks tracking; `POST /api/payments/nepal/track/:orderId/bank-reference` records a customer-reported transfer reference.
- Store administration is available under `/api/admin`: `/books` manages book pricing and stock; `/orders` manages order fulfillment; `/payments` reconciles provider transactions and confirms checked bank transfers; `/customers` manages customer records; `/settings` manages public bank details; `/store/analytics` provides sales reports; `/categories` manages store categories; `/notifications` lists dashboard alerts; `/orders/export` downloads a CSV; `/orders/:id/refund` records a refund; `/books/:id/stock` adjusts stock; `/customers/:id/orders` lists a customer's orders.
- Admin routes live under `/api/admin`; `POST /api/admin/auth/login` verifies the admin email and password. `POST /api/admin/auth/email/request` and `/email/verify` verify the admin mailbox; `/password/request` and `/password/reset` provide one-time email-code password recovery.
- `POST /api/newsletter/subscribe` saves a newsletter subscription with an encrypted email address; duplicate subscriptions are idempotent.
- Check the API with `npm run check --prefix server`.

## Production deployment

The application is domain-configurable; no deployment domain or hosting provider is assumed. Do not copy real secrets into this repository or chat. Configure the API's environment variables in the backend host's secret manager, and configure the frontend variables in the frontend host before `next build` because `NEXT_PUBLIC_*` values are embedded into the browser bundle at build time.

1. Provision a MongoDB deployment with TLS, authentication, backups, and network access restricted to the API host. Set `MONGODB_URI` and `MONGODB_DATABASE`.
2. Set `APP_ENV=production`, `FRONTEND_URL`, `PUBLIC_WEBSITE_URL`, `API_PUBLIC_URL`, and exact comma-separated `API_ALLOWED_ORIGINS` values. Use the actual HTTPS origins, with no wildcard, path, or trailing route. The API refuses to start in production when these domains, secure database settings, SMTP relay, or required secrets are invalid.
3. Generate separate random values of at least 32 characters for `JWT_SECRET`, `DATA_ENCRYPTION_KEY`, and `EMAIL_INDEX_SECRET`. Store and back up the encryption/index keys securely; rotating either without a data migration can make stored fields or lookups unreadable. Set the bootstrap `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` of at least 12 characters. The bootstrap password is used only when initially creating the admin.
4. Configure a dedicated SMTP relay with `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls` or `ssl`), and `SMTP_FROM`; configure both `SMTP_USERNAME` and `SMTP_PASSWORD` or neither. Admin email verification and password reset depend on successful delivery. Never use Gmail account credentials.
5. For separate frontend and API domains, set the frontend's `NEXT_PUBLIC_API_URL` to the public HTTPS API origin before building; set `API_SERVER_URL` to an API origin reachable by the Next.js server for metadata rendering. For a same-origin deployment, leave `NEXT_PUBLIC_API_URL` empty and set `API_SERVER_URL` to enable the built-in `/api/*` rewrite. Do not use a private/internal URL in `NEXT_PUBLIC_API_URL`. For cross-site frontend/API domains, set `SESSION_COOKIE_SAMESITE=none` (HTTPS is required); prefer frontend and API hostnames under the same registrable domain.
6. Install `server/requirements.txt` on the API host and start the cross-platform service with `python serve.py start` from the `server` directory (or `npm start --prefix server`). Deploy both services behind HTTPS. Configure the API host/platform's health probes to use `GET /health/live` for process liveness and `GET /health/ready` for MongoDB readiness. If behind a reverse proxy, set Uvicorn's `FORWARDED_ALLOW_IPS` in the process environment to only the proxy IPs; do not trust arbitrary forwarded client IP headers. The backend's built-in rate limiter is process-local, so use a shared gateway/limiter for multi-worker or multi-instance deployments.
7. Build the frontend with its final public API URL, then run `npm run build` and `npm start`. Verify the website, `/admin`, API health endpoints, public reads, and admin login/email verification/reset on the deployed domains.

The Admin Panel currently manages image URLs, not binary uploads. Upload image assets through a persistent object-storage/CDN provider and save the resulting HTTPS URL; no local-disk upload endpoint is exposed. Never rely on ephemeral host filesystems for media. `.env` files are ignored by Git; never commit them.
