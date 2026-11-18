# Screenshots

## Application screenshots (included)

These were captured from the running application with the seeded demo data using
Playwright + Chrome (1440 × 1000 desktop, 390 × 844 mobile).

| File | View |
|---|---|
| `01-home.png` | Storefront hero and departments |
| `01-home-full.png` | Full storefront page |
| `02-catalogue-filter.png` | Catalogue filtered by department and price |
| `03-product.png` | Product detail with stock, seller and reviews |
| `04-cart.png` | Basket with quantity controls |
| `05-checkout.png` | Delivery form and recalculated total |
| `06-payment.png` | Mock gateway, test mode |
| `07a-order-paid.png` | Order immediately after payment |
| `07-order-tracking.png` | Delivered order timeline, payment and shipment |
| `08-seller-dashboard.png` | Seller studio KPIs and catalogue |
| `08-seller-dashboard-full.png` | Full seller studio page |
| `09-admin-dashboard.png` | Admin KPIs and Chart.js reports |
| `10-admin-reports.png` | Revenue, category and seller reports |
| `11-admin-sellers.png` | Seller approval queue |
| `11b-admin-orders.png` | Admin order queue |
| `11c-admin-order-detail.png` | Admin order lifecycle controls |
| `12-api-docs.png` | Human-readable API documentation |
| `13-mobile.png` | Responsive mobile storefront |

## Hosting evidence (add after deployment)

These cannot be produced without the hosting account that owns the deployment.
Capture them after following `docs/DEPLOYMENT.md`, then update
`docs/PROJECT_REPORT.md` §11.2 and regenerate the DOCX.

| File to add | What to capture |
|---|---|
| `20-live-home.png` | Live HTTPS URL in the browser address bar on the storefront |
| `21-render-service.png` | Render web service page showing **Live**, the public URL and latest deploy |
| `22-render-deploy-log.png` | Deploy log showing `collectstatic`, `migrate` and `seed_demo` |
| `23-render-env.png` | Environment variables page with secret values hidden |
| `24-render-database.png` | PostgreSQL instance page (available, connected) |
| `25-healthz.png` | `/healthz` JSON response with `"database": true` |
| `26-github-repo.png` | Repository root proving no `.env` is committed |

The report's §11.3 and `docs/DEPLOYMENT.md` contain the exact steps.
