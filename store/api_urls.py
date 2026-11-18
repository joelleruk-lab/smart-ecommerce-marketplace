from django.urls import path

from . import api

app_name = 'api'

urlpatterns = [
    # Authentication
    path('auth/register', api.register, name='register'),
    path('auth/login', api.login, name='login'),
    path('auth/logout', api.logout, name='logout'),
    path('auth/me', api.me, name='me'),
    # Catalogue
    path('categories', api.category_list, name='categories'),
    path('products', api.product_list, name='products'),
    path('products/<int:product_id>', api.product_detail, name='product_detail'),
    path('products/<int:product_id>/reviews', api.product_reviews, name='product_reviews'),
    path('products/<int:product_id>/reviews/create', api.create_review, name='create_review'),
    # Cart
    path('cart', api.cart_detail, name='cart'),
    path('cart/clear', api.cart_clear, name='cart_clear'),
    path('cart/items', api.cart_add, name='cart_add'),
    path('cart/items/<int:product_id>', api.cart_item, name='cart_item'),
    # Orders
    path('orders', api.orders_collection, name='order_create'),
    path('orders/list', api.order_list, name='order_list'),
    path('orders/<int:order_id>', api.order_detail, name='order_detail'),
    path('orders/<int:order_id>/cancel', api.order_cancel, name='order_cancel'),
    path('orders/<int:order_id>/tracking', api.order_tracking, name='order_tracking'),
    path('orders/<int:order_id>/disputes', api.order_dispute, name='order_dispute'),
    # Payments
    path('payments/<int:order_id>', api.payment_detail, name='payment_detail'),
    path('payments/<int:order_id>/pay', api.payment_pay, name='payment_pay'),
    path('payments/webhook/mock', api.payment_webhook, name='payment_webhook'),
    # Seller
    path('seller/summary', api.seller_summary, name='seller_summary'),
    path('seller/products', api.seller_products, name='seller_products'),
    path('seller/products/create', api.seller_product_create, name='seller_product_create'),
    path('seller/products/<int:product_id>', api.seller_product_detail, name='seller_product_detail'),
    path('seller/inventory/<int:product_id>', api.seller_inventory, name='seller_inventory'),
    path('seller/orders', api.seller_orders, name='seller_orders'),
    # Administrator
    path('admin/users', api.admin_users, name='admin_users'),
    path('admin/users/<int:user_id>', api.admin_user_detail, name='admin_user_detail'),
    path('admin/sellers', api.admin_sellers, name='admin_sellers'),
    path('admin/sellers/<int:seller_id>/action', api.admin_seller_action, name='admin_seller_action'),
    path('admin/categories', api.admin_categories, name='admin_categories'),
    path('admin/categories/<int:category_id>', api.admin_category_detail, name='admin_category_detail'),
    path('admin/orders', api.admin_orders, name='admin_orders'),
    path('admin/orders/<int:order_id>/status', api.admin_order_status, name='admin_order_status'),
    path('admin/disputes', api.admin_disputes, name='admin_disputes'),
    path('admin/disputes/<int:dispute_id>', api.admin_dispute_detail, name='admin_dispute_detail'),
    path('admin/reports/summary', api.report_summary, name='report_summary'),
    path('admin/reports/sales-per-seller', api.report_sales_per_seller, name='report_sales_per_seller'),
    path('admin/reports/revenue', api.report_revenue, name='report_revenue'),
    path('admin/reports/best-sellers', api.report_best_sellers, name='report_best_sellers'),
    path('admin/reports/low-stock', api.report_low_stock, name='report_low_stock'),
    path('admin/reports/categories', api.report_categories, name='report_categories'),
]
