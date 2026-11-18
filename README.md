# Rukomeza Market

A complete multi-vendor e-commerce marketplace built with **Django 6.1**,
**PostgreSQL/SQLite**, server-rendered templates and a documented **JSON REST API**.
Customers browse and buy from independent sellers, sellers manage their own
catalogue and stock, and administrators oversee sellers, orders, disputes and
reports.

The project was built for the *Smart E-Commerce Marketplace* assignment and
covers the whole order lifecycle — Pending → Paid → Shipped → Delivered /
Cancelled — with concurrency-safe inventory, immutable price snapshots and a
working mock payment flow.

**Source code:** <https://github.com/joelleruk-lab/smart-ecommerce-marketplace>
**One-click deploy:** <https://render.com/deploy?repo=https://github.com/joelleruk-lab/smart-ecommerce-marketplace>

---

## Feature summary

### Customers
- Register/login with hashed passwords (PBKDF2) and role-aware sessions.
- Browse and search by keyword, category, price range, stock and sort order.
- Product detail with images, description, price, live stock, seller and reviews.
- Persistent cart (guest session cart merges into the account on login).
- Checkout with server-side price recalculation and stock checks.
- Mock payment page with success **and** failure simulation.
- Order history, order tracking timeline, cancellation before dispatch and
  disputes.
- Reviews restricted to customers with a paid/shipped/delivered order item.

### Sellers
- Seller application reviewed by an administrator.
- Seller studio with revenue/stock stats and low-stock alerts.
- Create, edit, deactivate and restock **only their own** listings.
- See orders that contain their products (and only their line items).

### Administrators
- Dashboard with KPI cards and Chart.js revenue/seller charts.
- Manage accounts (activate, deactivate, block).
- Approve, suspend, reinstate or reject sellers.
- Create/edit/delete categories (delete blocked while products exist).
- Manage the order lifecycle (dispatch with courier/tracking, deliver, cancel).
- Resolve disputes with a recorded decision.
- Reports: sales per seller, revenue per period, best sellers, low stock,
  revenue by category — with charts, tables and CSV-friendly data via the API.

### Engineering
- 3NF schema with 17 tables, database check/unique constraints and indexes.
- Atomic checkout: `SELECT ... FOR UPDATE` **plus** a conditional
  `UPDATE ... WHERE stock >= qty`, so overselling is impossible even on SQLite.
- Price, product name, SKU and seller snapshots on every order line.
- Controlled order-status state machine with audit events.
- Opaque bearer tokens for the API, stored as SHA-256 hashes.
- Role-based access control at view, API and object level.
- 58 automated tests, including a threaded overselling test.

---

## Stack

| Layer | Choice |
|---|---|
| Back-end | Python 3.13/3.14, Django 6.1 |
| Database | PostgreSQL in production, SQLite locally |
| Front-end | Django templates, custom responsive CSS, vanilla JS, Chart.js |
| API | JSON REST under `/api/v1/`, OpenAPI 3.1 spec |
| Auth | Sessions for HTML, hashed bearer tokens for the API |
| Payments | Documented mock gateway (success/failure) with signed webhook |
| Deployment | Render blueprint, Gunicorn, WhiteNoise, Docker, Neon-ready |

---

## Quick start

### Windows — double-click

After the one-time setup below, just double-click **`run_local.bat`**. It
migrates, seeds the demo data, starts the server and opens
<http://127.0.0.1:8000/>.

### Manual setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (optional locally; defaults use SQLite)
copy .env.example .env      # Windows
# cp .env.example .env      # Linux/macOS

# 4. Migrate and seed the demo marketplace
python manage.py migrate
python manage.py seed_demo

# 5. Run
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. A detailed French guide is available in
[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

### Demo accounts (created by `seed_demo`)

| Role | Login | Password |
|---|---|---|
| Administrator | `admin` or `admin@rukomeza.test` | `Admin#2026` |
| Customer | `amina@example.com` | `Customer#2026` |
| Seller | `greenbasket@example.com` | `Seller#2026` |
| Pending seller (for approval demo) | `kikuubo@example.com` | `Seller#2026` |

Change these passwords before using the project outside marking.

### Seed data

`python manage.py seed_demo` creates (idempotently):

- 7 categories
- 9 sellers (8 approved + 1 pending application)
- 30 products with generated CDN-style SVG images
- 20 customers
- 40 orders across all five statuses
- 81 order items with price snapshots
- 30 verified reviews
- payments, shipments, status history, 3 disputes, carts and low-stock alerts

Use `--reset` to wipe marketplace data and reseed, or `--force` to reseed without
deleting users.

---

## Tests

```bash
# Fast local run (uses MD5 hasher for speed only)
FAST_TESTS=1 python manage.py test store

# Production-hash run
python manage.py test store
```

The suite covers schema constraints, authentication/RBAC, catalogue filters,
cart limits, checkout, price snapshots, cancellation, payments, verified reviews,
seller ownership, admin lifecycle/reports, the API and a threaded concurrency
test that proves only 5 of 10 simultaneous buyers can purchase 5 units.

---

## Project layout

```
marketplace_project/     Django settings, URLs, WSGI
store/
  models.py              17-table 3NF schema + constraints
  services/              cart, checkout, orders, payments, catalogue, reports
  api.py                 JSON REST endpoints
  api_auth.py            bearer-token auth + HMAC webhook verification
  views.py               storefront, seller studio, admin dashboard
  forms.py               validation
  permissions.py         role decorators
  tests.py               58 automated tests
  templates/store/       all pages
web/                     CSS, JS, images (incl. generated product art)
docs/                    ERD, report, OpenAPI, Postman, deployment, payments
scripts/                 ERD/Postman generators, smoke tests
```

## Key URLs

| URL | Purpose |
|---|---|
| `/` | Storefront / catalogue |
| `/products/<id>/` | Product detail, reviews |
| `/cart/`, `/checkout/` | Cart and checkout |
| `/payments/<order_id>/` | Mock payment page |
| `/account/`, `/orders/<id>/` | Order history and tracking |
| `/seller/` | Seller studio |
| `/dashboard/` | Admin dashboard |
| `/dashboard/reports/` | Charts and reports |
| `/admin/` | Django admin (secondary) |
| `/api/v1/...` | JSON API |
| `/api/docs/` | Human-readable API documentation |
| `/api/openapi.yaml` | OpenAPI 3.1 specification |
| `/healthz` | Deployment health check |

## Documentation

- [Database design and ERD](docs/ERD.md) · [ERD image](docs/erd.png)
- [Project report](docs/PROJECT_REPORT.md) · [DOCX version](docs/PROJECT_REPORT.docx)
- [API specification](docs/openapi.yaml) · [Postman collection](docs/postman_collection.json)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Payment / mock gateway guide](docs/PAYMENTS.md)
- [API docs page](http://127.0.0.1:8000/api/docs/) when running

## Security notes

- Passwords use Django's PBKDF2 hasher; API tokens are stored as SHA-256 hashes.
- All state-changing HTML forms use CSRF tokens; API mutations require bearer
  tokens and are CSRF-exempt only because they do not use cookies.
- Object-level checks prevent sellers from reading or editing other sellers'
  products and orders.
- Secrets are read from environment variables. `.env` is git-ignored; only
  `.env.example` is committed.
- Production settings enable secure cookies, HSTS, HTTPS redirect and nosniff;
  set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` and
  `DATABASE_URL` in the hosting dashboard.

## Known scope boundaries

- The payment integration is a documented mock gateway (allowed by the brief).
  `docs/PAYMENTS.md` explains how to swap in Stripe/Paystack/Flutterwave test keys.
- Media files use local storage by default; `ProductImage.external_url` supports
  Cloudinary/R2 URLs, and a Render disk can persist uploads.
- Multi-vendor orders are shipped as one fulfilment; a production system might
  split shipments per seller.
- Email is sent to the console backend; configure SMTP for production.
