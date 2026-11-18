"""Generate docs/postman_collection.json from a compact endpoint description."""

import json
from pathlib import Path

BASE = '{{baseUrl}}'
DOCS = Path(__file__).resolve().parent.parent / 'docs'


def req(name, method, path, body=None, query=None, auth=True, description='', tests=None):
    url = {
        'raw': f'{BASE}{path}' + (('?' + '&'.join(f'{k}={v}' for k, v in query.items())) if query else ''),
        'host': ['{{baseUrl}}'],
        'path': [p for p in path.strip('/').split('/') if p],
    }
    if query:
        url['query'] = [{'key': k, 'value': str(v)} for k, v in query.items()]
    item = {
        'name': name,
        'request': {
            'method': method,
            'header': [{'key': 'Content-Type', 'value': 'application/json'}] if body is not None else [],
            'url': url,
            'description': description,
        },
        'response': [],
    }
    if auth:
        item['request']['auth'] = {'type': 'bearer', 'bearer': [{'key': 'token', 'value': '{{token}}', 'type': 'string'}]}
    if body is not None:
        item['request']['body'] = {'mode': 'raw', 'raw': json.dumps(body, indent=2), 'options': {'raw': {'language': 'json'}}}
    if tests:
        item['event'] = [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests}}]
    return item


collection = {
    'info': {
        'name': 'Rukomeza Market API',
        'description': (
            'Multi-vendor marketplace API. Log in first; the login request stores the bearer token '
            'in the collection variable {{token}} automatically. Replace {{baseUrl}} with your live URL.'
        ),
        'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
    },
    'variable': [
        {'key': 'baseUrl', 'value': 'http://127.0.0.1:8000'},
        {'key': 'token', 'value': ''},
        {'key': 'productId', 'value': '1'},
        {'key': 'orderId', 'value': '1'},
        {'key': 'sellerId', 'value': '1'},
        {'key': 'categoryId', 'value': '1'},
        {'key': 'disputeId', 'value': '1'},
        {'key': 'userId', 'value': '1'},
    ],
    'item': [
        {
            'name': '01 · Authentication',
            'item': [
                req('Login (saves token)', 'POST', '/api/v1/auth/login', {'username': 'amina@example.com', 'password': 'Customer#2026'}, auth=False,
                    description='Log in with username or email. The test script stores data.token.',
                    tests=[
                        "const body = pm.response.json();",
                        "if (body.data && body.data.token) { pm.collectionVariables.set('token', body.data.token); }",
                        "pm.test('login succeeded', () => pm.response.to.have.status(200));",
                    ]),
                req('Register customer', 'POST', '/api/v1/auth/register', {
                    'username': 'newcustomer', 'email': 'newcustomer@example.com',
                    'password1': 'StrongPass#2026', 'password2': 'StrongPass#2026',
                    'first_name': 'New', 'last_name': 'Customer', 'role': 'CUSTOMER',
                }, auth=False),
                req('Current user', 'GET', '/api/v1/auth/me'),
                req('Logout (revoke token)', 'POST', '/api/v1/auth/logout'),
            ],
        },
        {
            'name': '02 · Catalogue',
            'item': [
                req('Search products', 'GET', '/api/v1/products',
                    query={'q': 'coffee', 'category': 'food-groceries', 'min_price': '1000', 'max_price': '100000', 'sort': 'price_asc', 'in_stock': 'true'},
                    auth=False),
                req('Product detail', 'GET', '/api/v1/products/{{productId}}', auth=False),
                req('Product reviews', 'GET', '/api/v1/products/{{productId}}/reviews', auth=False),
                req('Create verified review', 'POST', '/api/v1/products/{{productId}}/reviews/create', {'rating': 5, 'comment': 'Exactly as described.'}),
                req('Categories', 'GET', '/api/v1/categories', auth=False),
            ],
        },
        {
            'name': '03 · Cart',
            'item': [
                req('Get cart', 'GET', '/api/v1/cart'),
                req('Add item', 'POST', '/api/v1/cart/items', {'product_id': 1, 'quantity': 2}),
                req('Update quantity', 'PATCH', '/api/v1/cart/items/{{productId}}', {'quantity': 3}),
                req('Remove item', 'DELETE', '/api/v1/cart/items/{{productId}}'),
                req('Clear cart', 'DELETE', '/api/v1/cart/clear'),
            ],
        },
        {
            'name': '04 · Orders',
            'item': [
                req('Place order (atomic checkout)', 'POST', '/api/v1/orders', {
                    'full_name': 'Amina Nakato', 'phone': '+256700200001',
                    'address': '12 Market Road', 'city': 'Kampala', 'gateway': 'MOCK',
                }, tests=[
                    "const body = pm.response.json();",
                    "if (body.data && body.data.id) { pm.collectionVariables.set('orderId', body.data.id); }",
                    "pm.test('order created', () => pm.response.to.have.status(201));",
                ]),
                req('List my orders', 'GET', '/api/v1/orders', query={'status': 'PAID'}),
                req('Order detail', 'GET', '/api/v1/orders/{{orderId}}'),
                req('Order tracking', 'GET', '/api/v1/orders/{{orderId}}/tracking'),
                req('Cancel order', 'POST', '/api/v1/orders/{{orderId}}/cancel', {'reason': 'Changed my mind'}),
                req('Open dispute', 'POST', '/api/v1/orders/{{orderId}}/disputes', {'reason': 'DAMAGED', 'description': 'The package arrived damaged.'}),
            ],
        },
        {
            'name': '05 · Payments (mock gateway)',
            'item': [
                req('Payment status', 'GET', '/api/v1/payments/{{orderId}}'),
                req('Simulate successful payment', 'POST', '/api/v1/payments/{{orderId}}/pay', {'outcome': 'success'}),
                req('Simulate failed payment', 'POST', '/api/v1/payments/{{orderId}}/pay', {'outcome': 'failure'}),
                req('Signed webhook (needs HMAC header)', 'POST', '/api/v1/payments/webhook/mock',
                    {'reference': 'PAY-REPLACE-ME', 'outcome': 'success'}, auth=False,
                    description='Header X-Mock-Signature must be HMAC-SHA256(MOCK_GATEWAY_SECRET, raw body) in hex.'),
            ],
        },
        {
            'name': '06 · Seller',
            'item': [
                req('Seller summary', 'GET', '/api/v1/seller/summary'),
                req('My products', 'GET', '/api/v1/seller/products'),
                req('Create product', 'POST', '/api/v1/seller/products/create', {
                    'name': 'Handwoven Basket', 'description': 'A strong handwoven basket from Kampala.',
                    'price': '18000.00', 'category_id': 1, 'stock_quantity': 10,
                }),
                req('Edit product', 'PATCH', '/api/v1/seller/products/{{productId}}', {'price': '19000.00'}),
                req('Update stock', 'PATCH', '/api/v1/seller/inventory/{{productId}}', {'delta': 5}),
                req('Deactivate product', 'DELETE', '/api/v1/seller/products/{{productId}}'),
                req('Seller orders', 'GET', '/api/v1/seller/orders'),
            ],
        },
        {
            'name': '07 · Admin',
            'item': [
                req('Users', 'GET', '/api/v1/admin/users', query={'role': 'CUSTOMER'}),
                req('Block/unblock user', 'PATCH', '/api/v1/admin/users/{{userId}}', {'is_blocked': True}),
                req('Sellers', 'GET', '/api/v1/admin/sellers', query={'status': 'PENDING'}),
                req('Approve seller', 'POST', '/api/v1/admin/sellers/{{sellerId}}/action', {'action': 'approve'}),
                req('Create category', 'POST', '/api/v1/admin/categories', {'name': 'Garden & Outdoor', 'icon': '🌿'}),
                req('Edit category', 'PATCH', '/api/v1/admin/categories/{{categoryId}}', {'is_active': False}),
                req('All orders', 'GET', '/api/v1/admin/orders', query={'status': 'PAID'}),
                req('Dispatch order', 'POST', '/api/v1/admin/orders/{{orderId}}/status', {'status': 'SHIPPED', 'courier': 'Rukomeza Express', 'tracking_number': 'RMX-123'}),
                req('Disputes', 'GET', '/api/v1/admin/disputes', query={'status': 'OPEN'}),
                req('Resolve dispute', 'PATCH', '/api/v1/admin/disputes/{{disputeId}}', {'status': 'RESOLVED', 'resolution_note': 'Refund issued.'}),
            ],
        },
        {
            'name': '08 · Reports',
            'item': [
                req('Summary', 'GET', '/api/v1/admin/reports/summary'),
                req('Sales per seller', 'GET', '/api/v1/admin/reports/sales-per-seller'),
                req('Revenue per period', 'GET', '/api/v1/admin/reports/revenue', query={'period': 'month'}),
                req('Best sellers', 'GET', '/api/v1/admin/reports/best-sellers', query={'limit': 10}),
                req('Low stock', 'GET', '/api/v1/admin/reports/low-stock'),
                req('Health check', 'GET', '/healthz', auth=False),
            ],
        },
    ],
}

DOCS.mkdir(parents=True, exist_ok=True)
target = DOCS / 'postman_collection.json'
target.write_text(json.dumps(collection, indent=2), encoding='utf-8')
print(f'Wrote {target} ({target.stat().st_size} bytes)')
