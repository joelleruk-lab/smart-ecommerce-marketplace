import json
import hmac
import hashlib

from django.conf import settings
from django.test import Client

from store.models import Product, User


client = Client()


def call(method, url, payload=None, token=None, **extra):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
    body = json.dumps(payload) if payload is not None else None
    response = getattr(client, method)(url, data=body, content_type='application/json', **headers, **extra)
    try:
        data = response.json()
    except Exception:
        data = response.content[:200]
    print(method.upper(), url, response.status_code, str(data)[:180])
    return response, data


_, login = call('post', '/api/v1/auth/login', {'username': 'amina@example.com', 'password': 'Customer#2026'})
token = login['data']['token']

call('get', '/api/v1/auth/me', token=token)
call('get', '/api/v1/products?q=coffee&min_price=1000&max_price=100000&sort=price_asc', )
call('get', '/api/v1/categories')

product = Product.objects.filter(is_active=True).first()
call('post', '/api/v1/cart/items', {'product_id': product.pk, 'quantity': 1}, token=token)
call('get', '/api/v1/cart', token=token)

_, order = call('post', '/api/v1/orders', {
    'full_name': 'Amina Nakato',
    'phone': '+256700200001',
    'address': '12 Market Road',
    'city': 'Kampala',
    'gateway': 'MOCK',
}, token=token)
order_id = order['data']['id']
call('get', f'/api/v1/orders/{order_id}/tracking', token=token)
call('post', f'/api/v1/payments/{order_id}/pay', {'outcome': 'success'}, token=token)
call('get', f'/api/v1/orders/{order_id}', token=token)

_, seller_login = call('post', '/api/v1/auth/login', {'username': 'greenbasket', 'password': 'Seller#2026'})
seller_token = seller_login['data']['token']
call('get', '/api/v1/seller/summary', token=seller_token)
call('get', '/api/v1/seller/orders', token=seller_token)
call('get', '/api/v1/seller/products', token=seller_token)

_, admin_login = call('post', '/api/v1/auth/login', {'username': 'admin', 'password': 'Admin#2026'})
admin_token = admin_login['data']['token']
for url in ['summary', 'sales-per-seller', 'revenue?period=month', 'best-sellers', 'low-stock']:
    call('get', f'/api/v1/admin/reports/{url}', token=admin_token)
call('get', '/api/v1/admin/users?role=CUSTOMER', token=admin_token)
call('get', '/api/v1/admin/sellers?status=PENDING', token=admin_token)
call('get', '/api/v1/admin/disputes', token=admin_token)

# Webhook signature test
from store.models import Payment
payment = Payment.objects.filter(status='PENDING').first()
body = json.dumps({'reference': payment.transaction_ref, 'outcome': 'success'}).encode()
signature = hmac.new(settings.MOCK_GATEWAY_SECRET.encode(), body, hashlib.sha256).hexdigest()
response = client.post('/api/v1/payments/webhook/mock', data=body, content_type='application/json',
                       HTTP_X_MOCK_SIGNATURE=signature)
print('POST webhook/mock', response.status_code, response.json())
