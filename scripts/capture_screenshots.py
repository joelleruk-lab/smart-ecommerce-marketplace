"""Capture application screenshots for the report.

Prerequisite: the Django dev server is running on 127.0.0.1:8000 with the demo
data, and Playwright is importable (see scripts/install_playwright.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get('SCREENSHOT_BASE_URL', 'http://127.0.0.1:8000')
OUT = Path(__file__).resolve().parent.parent / 'docs' / 'screenshots'
OUT.mkdir(parents=True, exist_ok=True)

VIEWPORT = {'width': 1440, 'height': 1000}


def settle(page, ms=450):
    page.wait_for_timeout(ms)
    try:
        page.wait_for_load_state('networkidle', timeout=5000)
    except Exception:
        pass


def login(page, identifier, password):
    page.goto(f'{BASE}/login/', wait_until='networkidle')
    page.fill('input[name="username"]', identifier)
    page.fill('input[name="password"]', password)
    page.click('form:has(input[name="password"]) button[type="submit"]')
    page.wait_for_load_state('networkidle')
    settle(page)
    if page.query_selector('.demo-box'):
        print('WARNING: still on the login page for', identifier)


def logout(page):
    page.goto(f'{BASE}/', wait_until='networkidle')
    button = page.query_selector('form[action="/logout/"] button')
    if button:
        button.click()
        page.wait_for_load_state('networkidle')


def shot(page, name, *, full_page=False):
    path = OUT / name
    page.screenshot(path=str(path), full_page=full_page)
    print('saved', path.relative_to(OUT.parent.parent), f'({path.stat().st_size // 1024} KB)')


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(15000)

        # Public storefront
        page.goto(f'{BASE}/', wait_until='networkidle')
        settle(page)
        shot(page, '01-home.png')
        shot(page, '01-home-full.png', full_page=True)

        page.goto(f'{BASE}/shop/?category=food-groceries&min_price=1000&max_price=200000&sort=price_asc', wait_until='networkidle')
        settle(page)
        shot(page, '02-catalogue-filter.png')

        # Customer flow
        login(page, 'amina@example.com', 'Customer#2026')
        page.goto(f'{BASE}/cart/', wait_until='networkidle')
        clear = page.query_selector('form[action="/cart/clear/"] button')
        if clear:
            clear.click()
            page.wait_for_load_state('networkidle')

        page.goto(f'{BASE}/shop/?in_stock=1', wait_until='networkidle')
        add = page.query_selector('form[action^="/cart/add/"] button')
        if add:
            add.click()
            page.wait_for_load_state('networkidle')

        # Product detail
        first_product = page.query_selector('.product-card h3 a')
        if first_product:
            first_product.click()
            page.wait_for_load_state('networkidle')
            settle(page)
            shot(page, '03-product.png')

        page.goto(f'{BASE}/cart/', wait_until='networkidle')
        settle(page)
        shot(page, '04-cart.png')

        page.goto(f'{BASE}/checkout/', wait_until='networkidle')
        settle(page)
        shot(page, '05-checkout.png')

        # Fill checkout if fields are empty and place the order
        order_detail_url = None
        if page.query_selector('input[name="full_name"]'):
            page.fill('input[name="full_name"]', 'Amina Nakato')
            page.fill('input[name="phone_number"]', '+256700200001')
            page.fill('textarea[name="shipping_address"]', '12 Market Road, Nakasero')
            page.fill('input[name="city"]', 'Kampala')
            page.click('.checkout-form button[type="submit"]')
            page.wait_for_load_state('networkidle')
            page.wait_for_url('**/payments/**', timeout=15000)
            settle(page)
            shot(page, '06-payment.png')

            # Pay successfully and capture the paid order
            page.click('button[name="outcome"][value="success"]')
            page.wait_for_load_state('networkidle')
            settle(page)
            order_detail_url = page.url
            shot(page, '07a-order-paid.png')

        # Seller studio
        logout(page)
        login(page, 'greenbasket@example.com', 'Seller#2026')
        page.goto(f'{BASE}/seller/', wait_until='networkidle')
        settle(page)
        shot(page, '08-seller-dashboard.png')
        shot(page, '08-seller-dashboard-full.png', full_page=True)

        # Admin
        logout(page)
        login(page, 'admin@rukomeza.test', 'Admin#2026')
        page.goto(f'{BASE}/dashboard/', wait_until='networkidle')
        settle(page, 900)
        shot(page, '09-admin-dashboard.png')
        page.goto(f'{BASE}/dashboard/reports/', wait_until='networkidle')
        settle(page, 900)
        shot(page, '10-admin-reports.png')
        page.goto(f'{BASE}/dashboard/sellers/', wait_until='networkidle')
        settle(page)
        shot(page, '11-admin-sellers.png')
        page.goto(f'{BASE}/dashboard/orders/', wait_until='networkidle')
        settle(page)
        shot(page, '11b-admin-orders.png')

        # Dispatch and deliver the order created in the customer flow so the
        # tracking screenshot shows the full lifecycle.
        if order_detail_url:
            order_id = order_detail_url.rstrip('/').split('/')[-1]
            page.goto(f'{BASE}/dashboard/orders/{order_id}/', wait_until='networkidle')
            page.select_option('select[name="status"]', 'SHIPPED')
            page.fill('input[name="courier"]', 'Rukomeza Express')
            page.fill('input[name="tracking_number"]', 'RMX-DEMO-0042')
            page.click('form[action$="/status/"] button[type="submit"]')
            page.wait_for_load_state('networkidle')
            page.select_option('select[name="status"]', 'DELIVERED')
            page.click('form[action$="/status/"] button[type="submit"]')
            page.wait_for_load_state('networkidle')
            settle(page)
            shot(page, '11c-admin-order-detail.png')

        # Public API docs
        page.goto(f'{BASE}/api/docs/', wait_until='networkidle')
        settle(page)
        shot(page, '12-api-docs.png')

        # Customer tracking for the delivered order
        if order_detail_url:
            logout(page)
            login(page, 'amina@example.com', 'Customer#2026')
            page.goto(order_detail_url, wait_until='networkidle')
            settle(page)
            shot(page, '07-order-tracking.png')

        context.close()

        # Mobile
        mobile = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=1, is_mobile=True)
        mpage = mobile.new_page()
        mpage.goto(f'{BASE}/', wait_until='networkidle')
        settle(mpage)
        mpage.screenshot(path=str(OUT / '13-mobile.png'), full_page=False)
        print('saved docs/screenshots/13-mobile.png')
        mobile.close()
        browser.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SCREENSHOT FAILURE:', exc, file=sys.stderr)
        raise
