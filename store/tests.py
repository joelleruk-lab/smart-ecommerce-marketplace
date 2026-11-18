"""Automated tests for the Rukomeza marketplace.

Run with::

    python manage.py test store

Covers the database constraints, authentication/authorisation, catalogue
filters, cart limits, atomic checkout, overselling under concurrency, payments,
verified reviews, seller ownership, admin lifecycle/reports and the JSON API.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hmac
import hashlib
import json
import threading
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    ApiToken,
    Cart,
    CartItem,
    Category,
    CustomerProfile,
    Dispute,
    Inventory,
    Order,
    OrderItem,
    OrderStatusEvent,
    Payment,
    Product,
    Review,
    SellerProfile,
)
from .services import reports
from .services.cart import add_item, cart_total, get_cart
from .services.checkout import CheckoutError, create_order
from .services.orders import OrderError, cancel_order, transition_order
from .services.payments import PaymentError, process_mock_payment


User = get_user_model()


def make_user(username, role='CUSTOMER', email=None, password='TestPass#2026'):
    return User.objects.create_user(
        username=username,
        email=email or f'{username}@example.com',
        password=password,
        role=role,
    )


def make_seller(username='seller', store='Test Store', approved=True):
    user = make_user(username, role='SELLER')
    profile = SellerProfile.objects.create(
        user=user,
        store_name=store,
        is_approved=approved,
        store_description='A test storefront.',
    )
    return user, profile


def make_product(seller, category, name='Test Phone', price='1000.00', stock=5, active=True):
    product = Product.objects.create(
        seller=seller,
        category=category,
        name=name,
        description='A reliable test product with enough description.',
        price=Decimal(price),
        is_active=active,
    )
    Inventory.objects.create(product=product, stock_quantity=stock)
    return product


def add_to_cart_via_http(client, product, quantity=1):
    return client.post(
        reverse('add_to_cart', args=(product.pk,)),
        {'quantity': str(quantity)},
        HTTP_REFERER='/shop/',
    )


def make_order(customer, product, quantity=1, status='PAID', payment_status=None, gateway='MOCK'):
    order = Order.objects.create(
        customer=customer,
        status=status,
        subtotal=product.price * quantity,
        total_amount=product.price * quantity,
        shipping_full_name=customer.get_full_name() or customer.username,
        shipping_phone='+256700000000',
        shipping_address='12 Test Road',
        shipping_city='Kampala',
    )
    item = OrderItem.objects.create(
        order=order,
        product=product,
        seller=product.seller,
        product_name_snapshot=product.name,
        sku_snapshot=product.sku,
        seller_name_snapshot=product.seller.store_name,
        quantity=quantity,
        unit_price_snapshot=product.price,
    )
    payment = Payment.objects.create(
        order=order,
        gateway=gateway,
        transaction_ref=f'PAY-TEST-{order.pk}-{timezone.now().timestamp()}',
        amount=order.total_amount,
        status=payment_status or ('PAID' if status in ('PAID', 'SHIPPED', 'DELIVERED') else 'PENDING'),
        paid_at=timezone.now() if status in ('PAID', 'SHIPPED', 'DELIVERED') else None,
    )
    OrderStatusEvent.objects.create(order=order, from_status='', to_status='PENDING', note='Order placed.', changed_by=customer)
    return order, item, payment


class MarketplaceBaseTest(TestCase):
    def setUp(self):
        self.seller_user, self.seller = make_seller('seller1', 'Green Basket')
        self.category = Category.objects.create(name='Electronics', slug='electronics', icon='💻')
        self.product = make_product(self.seller, self.category, name='Smart Speaker', price='50000.00', stock=5)
        self.customer = make_user('buyer')
        self.admin = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='AdminPass#2026',
            role='ADMIN',
        )


# ---------------------------------------------------------------------------
# Section A: schema, constraints, seed data
# ---------------------------------------------------------------------------
class SchemaConstraintTests(MarketplaceBaseTest):
    def test_negative_stock_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Inventory.objects.filter(pk=self.product.inventory.pk).update(stock_quantity=-1)

    def test_product_price_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(price=Decimal('0.00'))

    def test_order_status_is_constrained(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.create(customer=self.customer, status='REFUNDED', total_amount=Decimal('1.00'))

    def test_review_rating_must_be_between_one_and_five(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(customer=self.customer, product=self.product, rating=6, comment='Too high')

    def test_only_one_primary_image_per_product(self):
        from .models import ProductImage

        ProductImage.objects.create(product=self.product, external_url='https://example.com/a.jpg', is_primary=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductImage.objects.create(product=self.product, external_url='https://example.com/b.jpg', is_primary=True)

    def test_order_line_price_snapshot_survives_product_price_change(self):
        order, item, _ = make_order(self.customer, self.product, quantity=2)
        old_total = order.total_amount
        self.product.price = Decimal('75000.00')
        self.product.save()
        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.unit_price_snapshot, Decimal('50000.00'))
        self.assertEqual(order.total_amount, old_total)

    def test_price_snapshot_line_total_is_derived_not_stored(self):
        _, item, _ = make_order(self.customer, self.product, quantity=3)
        self.assertEqual(item.line_total, Decimal('150000.00'))

    def test_order_transition_rejects_illegal_jumps(self):
        order, _, _ = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        with self.assertRaises(OrderError):
            transition_order(order, 'DELIVERED', by=self.admin)

    def test_lifecycle_path_pending_paid_shipped_delivered(self):
        order, _, _ = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        process_mock_payment(order, outcome='success', by=self.customer)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAID')
        transition_order(order, 'SHIPPED', by=self.admin, courier='Express', tracking_number='TRK-1')
        order.refresh_from_db()
        self.assertEqual(order.status, 'SHIPPED')
        self.assertEqual(order.shipment.tracking_number, 'TRK-1')
        transition_order(order, 'DELIVERED', by=self.admin)
        order.refresh_from_db()
        self.assertEqual(order.status, 'DELIVERED')
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(OrderStatusEvent.objects.filter(order=order).count(), 4)


class SeedDataTests(TestCase):
    def test_seed_command_meets_minimum_counts(self):
        call_command('seed_demo', '--reset', verbosity=0)
        self.assertGreaterEqual(Category.objects.count(), 5)
        self.assertGreaterEqual(SellerProfile.objects.count(), 8)
        self.assertGreaterEqual(Product.objects.count(), 30)
        self.assertGreaterEqual(User.objects.filter(role='CUSTOMER').count(), 20)
        self.assertGreaterEqual(Order.objects.count(), 40)
        self.assertGreaterEqual(OrderItem.objects.count(), 60)
        self.assertGreaterEqual(Review.objects.count(), 30)
        self.assertTrue(Payment.objects.filter(status='PAID').exists())
        self.assertTrue(Order.objects.filter(status='DELIVERED').exists())
        self.assertTrue(Inventory.objects.filter(stock_quantity__lte=5).exists())


# ---------------------------------------------------------------------------
# Section C: authentication & authorisation
# ---------------------------------------------------------------------------
class AuthenticationTests(MarketplaceBaseTest):
    def test_registration_hashes_password_and_creates_profile(self):
        response = self.client.post(reverse('register'), {
            'username': 'newcustomer',
            'first_name': 'New',
            'last_name': 'Customer',
            'email': 'new@example.com',
            'phone_number': '+256700111111',
            'role': 'CUSTOMER',
            'store_name': '',
            'store_description': '',
            'password1': 'StrongPass#2026',
            'password2': 'StrongPass#2026',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newcustomer')
        self.assertTrue(user.check_password('StrongPass#2026'))
        self.assertNotEqual(user.password, 'StrongPass#2026')
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())

    def test_login_with_email_works(self):
        response = self.client.post(reverse('login'), {
            'username': 'buyer@example.com',
            'password': 'TestPass#2026',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.customer.pk)

    def test_blocked_user_cannot_sign_in(self):
        self.customer.is_blocked = True
        self.customer.save()
        response = self.client.post(reverse('login'), {
            'username': 'buyer',
            'password': 'TestPass#2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_customer_cannot_open_seller_or_admin_area(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('seller_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 403)

    def test_seller_cannot_open_admin_area(self):
        self.client.force_login(self.seller_user)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('seller_dashboard')).status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse('account'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_seller_registration_creates_unapproved_store(self):
        response = self.client.post(reverse('register'), {
            'username': 'newstore',
            'first_name': 'New',
            'last_name': 'Store',
            'email': 'newstore@example.com',
            'phone_number': '+256700222222',
            'role': 'SELLER',
            'store_name': 'New Store',
            'store_description': 'Handmade goods.',
            'password1': 'StrongPass#2026',
            'password2': 'StrongPass#2026',
        })
        self.assertEqual(response.status_code, 302)
        seller = SellerProfile.objects.get(store_name='New Store')
        self.assertFalse(seller.is_approved)


# ---------------------------------------------------------------------------
# Section B/D: catalogue, cart, checkout
# ---------------------------------------------------------------------------
class CatalogueTests(MarketplaceBaseTest):
    def test_keyword_category_and_price_filters(self):
        food = Category.objects.create(name='Food', slug='food')
        coffee = make_product(self.seller, food, name='Arabica Coffee', price='20000.00', stock=10)
        cheap = make_product(self.seller, self.category, name='Cheap Cable', price='500.00', stock=10)
        response = self.client.get(reverse('shop'), {'q': 'coffee'})
        self.assertContains(response, 'Arabica Coffee')
        self.assertNotContains(response, 'Cheap Cable')
        response = self.client.get(reverse('shop'), {'category': food.slug})
        self.assertContains(response, 'Arabica Coffee')
        self.assertNotContains(response, 'Smart Speaker')
        response = self.client.get(reverse('shop'), {'min_price': '1000', 'max_price': '60000'})
        self.assertContains(response, 'Smart Speaker')
        self.assertContains(response, 'Arabica Coffee')
        self.assertNotContains(response, 'Cheap Cable')
        self.assertEqual(coffee.category, food)

    def test_unapproved_seller_products_are_hidden(self):
        pending_user, pending = make_seller('pending', 'Pending Store', approved=False)
        hidden = make_product(pending, self.category, name='Hidden Gadget', stock=4)
        response = self.client.get(reverse('shop'), {'q': 'hidden'})
        self.assertNotContains(response, hidden.name)
        self.assertEqual(self.client.get(reverse('product_detail', args=(hidden.pk,))).status_code, 404)

    def test_inactive_products_are_hidden(self):
        inactive = make_product(self.seller, self.category, name='Old Model', active=False)
        self.assertEqual(self.client.get(reverse('product_detail', args=(inactive.pk,))).status_code, 404)


class CartTests(MarketplaceBaseTest):
    def test_add_to_cart_respects_stock(self):
        response = add_to_cart_via_http(self.client, self.product, 6)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CartItem.objects.exists())

    def test_cart_line_limit_is_enforced(self):
        Inventory.objects.filter(product=self.product).update(stock_quantity=200)
        add_to_cart_via_http(self.client, self.product, 99)
        add_to_cart_via_http(self.client, self.product, 1)
        cart = Cart.objects.first()
        self.assertEqual(cart.items.get().quantity, 99)

    def test_update_and_remove_lines(self):
        add_to_cart_via_http(self.client, self.product, 2)
        self.client.post(reverse('update_cart', args=(self.product.pk,)), {'quantity': '3'})
        self.assertEqual(CartItem.objects.get().quantity, 3)
        self.client.post(reverse('update_cart', args=(self.product.pk,)), {'quantity': '0'})
        self.assertFalse(CartItem.objects.exists())

    def test_guest_cart_merges_on_login(self):
        add_to_cart_via_http(self.client, self.product, 2)
        response = self.client.post(reverse('login'), {
            'username': 'buyer@example.com',
            'password': 'TestPass#2026',
        })
        self.assertEqual(response.status_code, 302)
        cart = Cart.objects.get(user=self.customer)
        self.assertEqual(cart.items.get(product=self.product).quantity, 2)


class CheckoutTests(MarketplaceBaseTest):
    def _cart_with(self, quantity=2):
        self.client.force_login(self.customer)
        add_to_cart_via_http(self.client, self.product, quantity)

    def _checkout(self):
        return self.client.post(reverse('checkout'), {
            'full_name': 'Buyer One',
            'phone_number': '+256700000000',
            'shipping_address': '12 Market Road',
            'city': 'Kampala',
        })

    def test_checkout_creates_order_snapshot_and_decrements_stock(self):
        self._cart_with(2)
        response = self._checkout()
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(order.total_amount, Decimal('100000.00'))
        item = order.items.get()
        self.assertEqual(item.unit_price_snapshot, Decimal('50000.00'))
        self.assertEqual(item.seller_name_snapshot, 'Green Basket')
        self.assertEqual(order.payment.status, 'PENDING')
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 3)
        self.assertFalse(CartItem.objects.filter(cart__user=self.customer).exists())
        self.assertTrue(OrderStatusEvent.objects.filter(order=order, to_status='PENDING').exists())

    def test_checkout_with_stale_quantity_creates_nothing(self):
        self._cart_with(1)
        CartItem.objects.update(quantity=6)
        response = self._checkout()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('cart')))
        self.assertFalse(Order.objects.filter(customer=self.customer).exists())
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 5)

    def test_checkout_uses_current_price_not_cached_price(self):
        self._cart_with(1)
        self.product.price = Decimal('65000.00')
        self.product.save()
        self._checkout()
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.total_amount, Decimal('65000.00'))
        self.assertEqual(order.items.get().unit_price_snapshot, Decimal('65000.00'))

    def test_cancel_restores_stock_and_refunds_payment(self):
        self._cart_with(2)
        self._checkout()
        order = Order.objects.get(customer=self.customer)
        process_mock_payment(order, outcome='success', by=self.customer)
        response = self.client.post(reverse('order_cancel', args=(order.pk,)), {'reason': 'Changed my mind'})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')
        self.assertEqual(order.payment.status, 'REFUNDED')
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 5)

    def test_cannot_cancel_delivered_order(self):
        order, _, _ = make_order(self.customer, self.product, status='DELIVERED')
        self.client.force_login(self.customer)
        self.client.post(reverse('order_cancel', args=(order.pk,)))
        order.refresh_from_db()
        self.assertEqual(order.status, 'DELIVERED')

    def test_cart_total_matches_prices(self):
        cart = Cart.objects.create(user=self.customer)
        add_item(cart, self.product, 3)
        self.assertEqual(cart_total(cart), Decimal('150000.00'))


# ---------------------------------------------------------------------------
# Section B: payments and verified reviews
# ---------------------------------------------------------------------------
class PaymentTests(MarketplaceBaseTest):
    def test_successful_mock_payment_marks_order_paid(self):
        order, _, payment = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        result = process_mock_payment(order, outcome='success', by=self.customer)
        order.refresh_from_db()
        self.assertEqual(result.status, 'PAID')
        self.assertEqual(order.status, 'PAID')
        self.assertIsNotNone(order.paid_at)
        self.assertEqual(result.attempts, 1)

    def test_failed_payment_stays_pending_and_can_retry(self):
        order, _, payment = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        process_mock_payment(order, outcome='failure', by=self.customer)
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(payment.status, 'FAILED')
        self.assertIn('declined', payment.failure_reason)
        process_mock_payment(order, outcome='success', by=self.customer)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAID')

    def test_payment_is_idempotent(self):
        order, _, payment = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        process_mock_payment(order, outcome='success', by=self.customer)
        process_mock_payment(order, outcome='success', by=self.customer)
        self.assertEqual(OrderStatusEvent.objects.filter(order=order, to_status='PAID').count(), 1)
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)

    def test_cannot_pay_cancelled_order(self):
        order, _, _ = make_order(self.customer, self.product, status='CANCELLED', payment_status='CANCELLED')
        with self.assertRaises(PaymentError):
            process_mock_payment(order, outcome='success', by=self.customer)

    def test_payment_page_renders_and_processes(self):
        order, _, _ = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('payment_page', args=(order.pk,))).status_code, 200)
        self.client.post(reverse('payment_page', args=(order.pk,)), {'outcome': 'success'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAID')


class ReviewTests(MarketplaceBaseTest):
    def test_non_buyer_cannot_review(self):
        self.client.force_login(self.customer)
        self.client.post(reverse('product_detail', args=(self.product.pk,)), {'rating': 5, 'comment': 'Great!'})
        self.assertFalse(Review.objects.exists())

    def test_verified_buyer_can_review_once(self):
        order, item, _ = make_order(self.customer, self.product, status='DELIVERED')
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse('product_detail', args=(self.product.pk,)),
            {'rating': 5, 'comment': 'Excellent speaker.'},
        )
        self.assertEqual(response.status_code, 302)
        review = Review.objects.get()
        self.assertEqual(review.rating, 5)
        self.assertTrue(review.is_verified_purchase)
        self.assertEqual(review.order_item, item)
        self.client.post(
            reverse('product_detail', args=(self.product.pk,)),
            {'rating': 1, 'comment': 'Changed my mind.'},
        )
        self.assertEqual(Review.objects.count(), 1)


# ---------------------------------------------------------------------------
# Section C/B: seller ownership and admin operations
# ---------------------------------------------------------------------------
class SellerTests(MarketplaceBaseTest):
    def test_approved_seller_can_publish_product_with_inventory(self):
        self.client.force_login(self.seller_user)
        response = self.client.post(reverse('seller_product_create'), {
            'name': 'Handwoven Basket',
            'category': self.category.pk,
            'description': 'A strong handwoven basket made in Kampala.',
            'price': '18000.00',
            'stock_quantity': '4',
            'low_stock_threshold': '2',
            'is_active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name='Handwoven Basket')
        self.assertEqual(product.seller, self.seller)
        self.assertEqual(product.inventory.stock_quantity, 4)

    def test_unapproved_seller_cannot_publish(self):
        user, seller = make_seller('unapproved', 'Waiting Store', approved=False)
        self.client.force_login(user)
        self.client.post(reverse('seller_product_create'), {
            'name': 'Not Allowed',
            'category': self.category.pk,
            'description': 'This listing should not be created.',
            'price': '1000.00',
            'stock_quantity': '1',
        })
        self.assertFalse(Product.objects.filter(name='Not Allowed').exists())

    def test_seller_cannot_edit_another_sellers_product(self):
        other_user, other = make_seller('other', 'Other Store')
        self.client.force_login(other_user)
        response = self.client.get(reverse('seller_product_edit', args=(self.product.pk,)))
        self.assertEqual(response.status_code, 404)

    def test_seller_can_set_stock_and_deactivate(self):
        self.client.force_login(self.seller_user)
        self.client.post(reverse('seller_stock_update', args=(self.product.pk,)), {'stock_quantity': '42'})
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 42)
        self.client.post(reverse('seller_product_toggle', args=(self.product.pk,)))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_seller_sees_only_orders_with_own_items(self):
        other_user, other_seller = make_seller('other2', 'Other Store 2')
        other_product = make_product(other_seller, self.category, name='Other Product', price='2000.00')
        own_order, _, _ = make_order(self.customer, self.product)
        other_order, _, _ = make_order(self.customer, other_product)
        self.client.force_login(self.seller_user)
        response = self.client.get(reverse('seller_orders'))
        self.assertContains(response, own_order.reference)
        self.assertNotContains(response, other_order.reference)


class AdminTests(MarketplaceBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_admin_can_approve_pending_seller(self):
        user, seller = make_seller('waiting', 'Waiting Store', approved=False)
        response = self.client.post(reverse('admin_seller_action', args=(seller.pk,)), {'action': 'approve'})
        self.assertEqual(response.status_code, 302)
        seller.refresh_from_db()
        self.assertTrue(seller.is_approved)

    def test_admin_can_dispatch_and_deliver_paid_order(self):
        order, _, _ = make_order(self.customer, self.product, status='PAID')
        self.client.post(
            reverse('admin_order_status', args=(order.pk,)),
            {'status': 'SHIPPED', 'courier': 'Express', 'tracking_number': 'TRK-9'},
        )
        order.refresh_from_db()
        self.assertEqual(order.status, 'SHIPPED')
        self.client.post(reverse('admin_order_status', args=(order.pk,)), {'status': 'DELIVERED'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'DELIVERED')

    def test_admin_cannot_skip_lifecycle(self):
        order, _, _ = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        self.client.post(reverse('admin_order_status', args=(order.pk,)), {'status': 'DELIVERED'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'PENDING')

    def test_reports_are_correct(self):
        make_order(self.customer, self.product, quantity=2, status='PAID')
        cancelled, _, _ = make_order(self.customer, self.product, quantity=5, status='CANCELLED', payment_status='CANCELLED')
        sales = reports.sales_per_seller()
        self.assertEqual(sales[0]['store_name'], 'Green Basket')
        self.assertEqual(sales[0]['units'], 2)
        self.assertEqual(sales[0]['revenue'], Decimal('100000.00'))
        best = reports.best_sellers(5)
        self.assertEqual(best[0]['units'], 2)
        low = reports.low_stock()
        self.assertEqual(low[0]['stock'], 5)
        summary = reports.summary()
        self.assertEqual(summary['revenue'], Decimal('100000.00'))
        self.assertEqual(summary['all_orders'], 2)
        self.assertTrue(cancelled.pk)

    def test_admin_resolves_dispute(self):
        order, _, _ = make_order(self.customer, self.product, status='DELIVERED')
        dispute = Dispute.objects.create(
            order=order,
            raised_by=self.customer,
            reason='DAMAGED',
            description='The item arrived damaged in transit.',
        )
        response = self.client.post(
            reverse('admin_dispute_resolve', args=(dispute.pk,)),
            {'status': 'RESOLVED', 'resolution_note': 'Refund issued.'},
        )
        self.assertEqual(response.status_code, 302)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'RESOLVED')
        self.assertEqual(dispute.resolved_by, self.admin)


# ---------------------------------------------------------------------------
# Section B: JSON API
# ---------------------------------------------------------------------------
class ApiTests(MarketplaceBaseTest):
    def login(self, identifier='buyer', password='TestPass#2026'):
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({'username': identifier, 'password': password}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        return response.json()['data']['token']

    def auth(self, token):
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def test_api_requires_bearer_token(self):
        response = self.client.get('/api/v1/cart')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'unauthorized')

    def test_register_and_login_return_tokens(self):
        response = self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({
                'username': 'apiuser',
                'email': 'apiuser@example.com',
                'password1': 'StrongPass#2026',
                'password2': 'StrongPass#2026',
                'first_name': 'Api',
                'last_name': 'User',
                'role': 'CUSTOMER',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()['data']
        self.assertEqual(payload['user']['role'], 'CUSTOMER')
        self.assertTrue(ApiToken.objects.filter(user__username='apiuser').exists())
        token = self.login('apiuser@example.com', 'StrongPass#2026')
        me = self.client.get('/api/v1/auth/me', **self.auth(token))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()['data']['user']['username'], 'apiuser')

    def test_api_product_filters_and_pagination(self):
        response = self.client.get('/api/v1/products', {'q': 'smart', 'min_price': '1000', 'max_price': '60000'})
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['results'][0]['name'], 'Smart Speaker')
        self.assertEqual(data['results'][0]['price'], '50000.00')

    def test_api_cart_checkout_payment_and_tracking(self):
        token = self.login()
        response = self.client.post(
            '/api/v1/cart/items',
            data=json.dumps({'product_id': self.product.pk, 'quantity': 2}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            '/api/v1/orders',
            data=json.dumps({
                'full_name': 'Buyer One',
                'phone': '+256700000000',
                'address': '12 Market Road',
                'city': 'Kampala',
                'gateway': 'MOCK',
            }),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 201)
        order = response.json()['data']
        self.assertEqual(order['status'], 'PENDING')
        self.assertEqual(order['total'], '100000.00')
        response = self.client.post(
            f"/api/v1/payments/{order['id']}/pay",
            data=json.dumps({'outcome': 'success'}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['order_status'], 'PAID')
        tracking = self.client.get(f"/api/v1/orders/{order['id']}/tracking", **self.auth(token))
        self.assertEqual(tracking.status_code, 200)
        self.assertGreaterEqual(len(tracking.json()['data']['timeline']), 2)
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 3)

    def test_api_cart_rejects_excess_quantity(self):
        token = self.login()
        response = self.client.post(
            '/api/v1/cart/items',
            data=json.dumps({'product_id': self.product.pk, 'quantity': 99}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'insufficient_stock')

    def test_api_seller_cannot_modify_other_listing(self):
        token = self.login('seller1', 'TestPass#2026')
        other_user, other_seller = make_seller('apiother', 'API Other Store')
        other_product = make_product(other_seller, self.category, name='Foreign Product')
        response = self.client.patch(
            f'/api/v1/seller/products/{other_product.pk}',
            data=json.dumps({'price': '1.00'}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 404)

    def test_api_verified_review_only(self):
        token = self.login()
        response = self.client.post(
            f'/api/v1/products/{self.product.pk}/reviews/create',
            data=json.dumps({'rating': 5, 'comment': 'Not bought yet.'}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'verified_purchase_required')
        make_order(self.customer, self.product, status='DELIVERED')
        response = self.client.post(
            f'/api/v1/products/{self.product.pk}/reviews/create',
            data=json.dumps({'rating': 5, 'comment': 'Bought and loved it.'}),
            content_type='application/json',
            **self.auth(token),
        )
        self.assertEqual(response.status_code, 201)

    def test_api_admin_reports_require_admin(self):
        customer_token = self.login()
        response = self.client.get('/api/v1/admin/reports/summary', **self.auth(customer_token))
        self.assertEqual(response.status_code, 403)
        admin_token = self.login('admin', 'AdminPass#2026')
        response = self.client.get('/api/v1/admin/reports/summary', **self.auth(admin_token))
        self.assertEqual(response.status_code, 200)
        self.assertIn('revenue', response.json()['data'])

    def test_api_webhook_signature_is_verified(self):
        order, _, payment = make_order(self.customer, self.product, status='PENDING', payment_status='PENDING')
        body = json.dumps({'reference': payment.transaction_ref, 'outcome': 'success'}).encode()
        response = self.client.post('/api/v1/payments/webhook/mock', data=body, content_type='application/json')
        self.assertEqual(response.status_code, 401)
        signature = hmac.new(
            settings.MOCK_GATEWAY_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        response = self.client.post(
            '/api/v1/payments/webhook/mock',
            data=body,
            content_type='application/json',
            HTTP_X_MOCK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'PAID')

    def test_api_404_is_json(self):
        response = self.client.get('/api/v1/products/999999')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response['Content-Type'].startswith('application/json'))


# ---------------------------------------------------------------------------
# Section B: concurrency / overselling
# ---------------------------------------------------------------------------
class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.seller_user, self.seller = make_seller('conc-seller', 'Concurrency Store')
        self.category = Category.objects.create(name='Concurrency', slug='concurrency')
        self.product = make_product(self.seller, self.category, name='Last Ticket', price='1000.00', stock=5)
        self.buyers = []
        for index in range(10):
            buyer = make_user(f'concbuyer{index}', email=f'concbuyer{index}@example.com')
            cart = Cart.objects.create(user=buyer)
            CartItem.objects.create(cart=cart, product=self.product, quantity=1)
            self.buyers.append(buyer)

    def _buy(self, buyer):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            for attempt in range(5):
                try:
                    cart = Cart.objects.get(user=buyer)
                    create_order(
                        user=buyer,
                        cart=cart,
                        full_name=buyer.get_full_name() or buyer.username,
                        phone='+256700000000',
                        address='12 Race Road',
                        city='Kampala',
                    )
                    return True
                except CheckoutError:
                    return False
                except OperationalError:
                    time.sleep(0.15 * (attempt + 1))
            return False
        finally:
            close_old_connections()

    def test_concurrent_checkouts_cannot_oversell(self):
        global barrier
        barrier = threading.Barrier(len(self.buyers))
        with ThreadPoolExecutor(max_workers=len(self.buyers)) as executor:
            results = list(executor.map(self._buy, self.buyers))
        self.assertEqual(sum(results), 5, 'exactly five units may be sold')
        self.assertEqual(Order.objects.count(), 5)
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 0)
        self.assertEqual(OrderItem.objects.count(), 5)
