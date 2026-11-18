from django.test import Client

from store.models import Order, Product, User

client = Client()

for url in ['/', '/shop/', '/shop/?q=coffee&min_price=1000&max_price=100000&sort=rating', '/about/', '/contact/',
            '/login/', '/register/', '/cart/', '/api/docs/', '/healthz', '/api/v1/products', '/api/v1/categories']:
    response = client.get(url)
    print('ANON', url, response.status_code, response.get('Content-Type', '')[:30])

product = Product.objects.first()
print('PRODUCT', client.get(f'/products/{product.pk}/').status_code)
response = client.post(f'/cart/add/{product.pk}/', {'quantity': 2})
print('ADD CART', response.status_code, response.url)
print('CART', client.get('/cart/').status_code)
response = client.get('/checkout/')
print('CHECKOUT anon', response.status_code, response.url)

customer = User.objects.get(username='amina')
client.force_login(customer)
for url in ['/account/', '/checkout/', '/orders/']:
    response = client.get(url)
    print('CUSTOMER', url, response.status_code)

order = Order.objects.filter(customer=customer).first()
if order:
    for url in [f'/orders/{order.pk}/', f'/payments/{order.pk}/']:
        print('CUSTOMER', url, client.get(url).status_code)
print('CUSTOMER seller page', client.get('/seller/').status_code)

seller = User.objects.get(username='greenbasket')
client.force_login(seller)
for url in ['/seller/', '/seller/orders/']:
    response = client.get(url)
    print('SELLER', url, response.status_code)

admin = User.objects.get(username='admin')
client.force_login(admin)
for url in ['/dashboard/', '/dashboard/reports/', '/dashboard/users/', '/dashboard/sellers/', '/dashboard/categories/',
            '/dashboard/orders/', '/dashboard/disputes/']:
    response = client.get(url)
    print('ADMIN', url, response.status_code)

if order:
    for url in [f'/dashboard/orders/{order.pk}/']:
        print('ADMIN', url, client.get(url).status_code)
