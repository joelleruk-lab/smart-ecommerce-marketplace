from django.urls import include, path

from . import views

urlpatterns = [
    # Storefront
    path('', views.home, name='home'),
    path('shop/', views.shop, name='shop'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),
    # Cart & checkout
    path('cart/', views.cart_view, name='cart'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:product_id>/', views.update_cart, name='update_cart'),
    path('cart/remove/<int:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/clear/', views.clear_cart_view, name='clear_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('payments/<int:order_id>/', views.payment_page, name='payment_page'),
    # Accounts
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('account/', views.account, name='account'),
    path('orders/', views.account, name='orders'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/<int:order_id>/dispute/', views.order_dispute, name='order_dispute'),
    # Seller studio
    path('seller/', views.seller_dashboard, name='seller_dashboard'),
    path('seller/products/create/', views.seller_product_create, name='seller_product_create'),
    path('seller/products/<int:product_id>/edit/', views.seller_product_edit, name='seller_product_edit'),
    path('seller/products/<int:product_id>/toggle/', views.seller_product_toggle, name='seller_product_toggle'),
    path('seller/products/<int:product_id>/stock/', views.seller_stock_update, name='seller_stock_update'),
    path('seller/orders/', views.seller_orders, name='seller_orders'),
    # Administration dashboard
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/users/', views.admin_users, name='admin_users'),
    path('dashboard/users/<int:user_id>/action/', views.admin_user_action, name='admin_user_action'),
    path('dashboard/sellers/', views.admin_sellers, name='admin_sellers'),
    path('dashboard/sellers/<int:seller_id>/action/', views.admin_seller_action, name='admin_seller_action'),
    path('dashboard/categories/', views.admin_categories, name='admin_categories'),
    path('dashboard/categories/<int:category_id>/edit/', views.admin_category_edit, name='admin_category_edit'),
    path('dashboard/categories/<int:category_id>/delete/', views.admin_category_delete, name='admin_category_delete'),
    path('dashboard/orders/', views.admin_orders, name='admin_orders'),
    path('dashboard/orders/<int:order_id>/', views.admin_order_detail, name='admin_order_detail'),
    path('dashboard/orders/<int:order_id>/status/', views.admin_order_status, name='admin_order_status'),
    path('dashboard/disputes/', views.admin_disputes, name='admin_disputes'),
    path('dashboard/disputes/<int:dispute_id>/resolve/', views.admin_dispute_resolve, name='admin_dispute_resolve'),
    path('dashboard/reports/', views.admin_reports, name='admin_reports'),
    # JSON API & docs
    path('api/v1/', include('store.api_urls')),
    path('api/docs/', views.api_docs, name='api_docs'),
    path('api/openapi.yaml', views.openapi_spec, name='openapi_spec'),
    path('healthz', views.healthz, name='healthz'),
]
