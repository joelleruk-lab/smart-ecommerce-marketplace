"""Server-rendered storefront, seller studio and administrator dashboard."""

from __future__ import annotations

from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    CategoryForm,
    CheckoutForm,
    DisputeForm,
    LoginForm,
    ProductForm,
    RegistrationForm,
    ReviewForm,
    StockForm,
)
from .models import (
    Category,
    CustomerProfile,
    Dispute,
    Inventory,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductImage,
    Review,
    SellerProfile,
)
from .permissions import admin_required, is_admin, role_required, seller_required
from .services import catalogue, reports
from .services.cart import (
    CartError,
    add_item,
    cart_items,
    cart_total,
    clear as clear_cart,
    get_cart,
    merge_session_cart_into_user,
    remove_item,
    update_item,
)
from .services.checkout import CheckoutError, cart_has_stock_conflict, create_order
from .services.orders import OrderError, cancel_order, transition_order
from .services.payments import PaymentError, process_mock_payment


PAGE_SIZE = 12


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _catalogue_queryset(request):
    return catalogue.filter_products(
        q=request.GET.get('q', ''),
        category=request.GET.get('category', ''),
        min_price=request.GET.get('min_price'),
        max_price=request.GET.get('max_price'),
        seller=request.GET.get('seller', ''),
        sort=request.GET.get('sort', 'newest'),
        in_stock_only=request.GET.get('in_stock', '').lower() in ('1', 'on', 'true'),
    )


def _categories():
    return (
        Category.objects.filter(is_active=True)
        .annotate(
            product_count=Count(
                'products',
                filter=Q(
                    products__is_active=True,
                    products__seller__is_approved=True,
                    products__seller__is_suspended=False,
                ),
                distinct=True,
            )
        )
        .order_by('name')
    )


def _catalogue_context(request):
    products = _catalogue_queryset(request).prefetch_related('images')
    paginator = Paginator(products, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    selected_category = request.GET.get('category', '').strip()
    return {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': _categories(),
        'query': request.GET.get('q', '').strip(),
        'selected_category': selected_category,
        'selected_category_obj': Category.objects.filter(slug=selected_category).first() if selected_category else None,
        'min_price': request.GET.get('min_price', ''),
        'max_price': request.GET.get('max_price', ''),
        'selected_sort': request.GET.get('sort', 'newest'),
        'in_stock_only': request.GET.get('in_stock', '') in ('1', 'on', 'true'),
        'total_results': paginator.count,
    }


def _visible_order_or_404(request, order_id):
    order = (
        Order.objects.select_related('customer')
        .prefetch_related('items__product', 'items__seller', 'status_events', 'disputes')
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        raise Http404('Order not found.')
    if is_admin(request.user) or order.customer_id == request.user.pk:
        return order
    seller = getattr(request.user, 'seller_profile', None)
    if seller is not None and order.items.filter(seller=seller).exists():
        return order
    raise Http404('Order not found.')


def _order_timeline(order):
    steps = [
        ('PENDING', 'Order placed', order.created_at),
        ('PAID', 'Payment confirmed', order.paid_at),
        ('SHIPPED', 'Shipped', order.shipped_at),
        ('DELIVERED', 'Delivered', order.delivered_at),
    ]
    if order.status == 'CANCELLED':
        return [{'key': 'PENDING', 'label': 'Order placed', 'date': order.created_at, 'done': True, 'current': False, 'state': 'done'},
                {'key': 'CANCELLED', 'label': 'Cancelled', 'date': order.cancelled_at, 'done': True, 'current': True, 'state': 'cancelled'}]
    order_index = {'PENDING': 0, 'PAID': 1, 'SHIPPED': 2, 'DELIVERED': 3}.get(order.status, 0)
    rows = []
    for index, (key, label, date) in enumerate(steps):
        rows.append({
            'key': key,
            'label': label,
            'date': date,
            'done': index <= order_index,
            'current': index == order_index,
            'state': 'done' if index < order_index else ('current' if index == order_index else 'upcoming'),
        })
    return rows


def _monthly_series():
    rows = reports.revenue_per_period('month')
    labels = []
    values = []
    for row in rows:
        if not row['period']:
            continue
        labels.append(row['period'][:7])
        values.append(float(row['revenue']))
    return labels, values


# ---------------------------------------------------------------------------
# Public storefront
# ---------------------------------------------------------------------------
def home(request):
    return render(request, 'store/home.html', _catalogue_context(request))


def shop(request):
    return render(request, 'store/home.html', _catalogue_context(request))


def about(request):
    return render(request, 'store/about.html', {'categories': _categories()})


def contact(request):
    return render(request, 'store/contact.html')


@require_http_methods(['GET', 'POST'])
def product_detail(request, product_id):
    product = get_object_or_404(
        catalogue.available_products().prefetch_related('images'),
        pk=product_id,
    )
    verified_items = (
        OrderItem.objects.filter(
            product=product,
            order__customer=request.user,
            order__status__in=('PAID', 'SHIPPED', 'DELIVERED'),
        )
        if request.user.is_authenticated
        else OrderItem.objects.none()
    )
    order_item = verified_items.select_related('order').order_by('-order__created_at').first()
    already_reviewed = (
        request.user.is_authenticated
        and Review.objects.filter(customer=request.user, product=product).exists()
    )
    can_review = bool(order_item) and not already_reviewed
    review_form = ReviewForm()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if order_item is None:
            messages.error(request, 'Only verified buyers can review this product.')
            return redirect('product_detail', product_id=product.pk)
        if already_reviewed:
            messages.error(request, 'You have already reviewed this product.')
            return redirect('product_detail', product_id=product.pk)
        review_form = ReviewForm(request.POST)
        if review_form.is_valid():
            review = review_form.save(commit=False)
            review.customer = request.user
            review.product = product
            review.order_item = order_item
            review.is_verified_purchase = True
            review.save()
            messages.success(request, 'Thank you — your verified review is live.')
            return redirect('product_detail', product_id=product.pk)

    return render(request, 'store/product_detail.html', {
        'product': product,
        'reviews': product.reviews.select_related('customer').order_by('-created_at'),
        'can_review': can_review,
        'already_reviewed': already_reviewed,
        'review_form': review_form,
        'related': catalogue.available_products()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .prefetch_related('images')[:4],
    })


# ---------------------------------------------------------------------------
# Cart and checkout
# ---------------------------------------------------------------------------
def _return_to_referrer(request, fallback='home'):
    referrer = request.META.get('HTTP_REFERER', '')
    if referrer and referrer.startswith(request.build_absolute_uri('/')):
        return redirect(referrer)
    return redirect(fallback)


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if not product.seller.is_open_for_business:
        messages.error(request, 'This store is not currently accepting orders.')
        return _return_to_referrer(request, 'shop')
    try:
        quantity = int(request.POST.get('quantity', '1'))
    except (TypeError, ValueError):
        messages.error(request, 'Enter a valid quantity.')
        return _return_to_referrer(request, 'shop')
    cart = get_cart(request, create=True)
    try:
        add_item(cart, product, quantity)
    except CartError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f'{product.name} added to your basket.')
    return _return_to_referrer(request, 'shop')


@require_POST
def update_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    cart = get_cart(request)
    if cart is None:
        messages.info(request, 'Your basket is empty.')
        return redirect('cart')
    try:
        quantity = int(request.POST.get('quantity', '1'))
    except (TypeError, ValueError):
        messages.error(request, 'Enter a valid quantity.')
        return redirect('cart')
    try:
        update_item(cart, product, quantity)
    except CartError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'Basket updated.' if quantity > 0 else f'{product.name} removed.')
    return redirect('cart')


@require_POST
def remove_from_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    cart = get_cart(request)
    if cart and remove_item(cart, product):
        messages.info(request, f'{product.name} removed from your basket.')
    return redirect('cart')


@require_POST
def clear_cart_view(request):
    cart = get_cart(request)
    if cart:
        clear_cart(cart)
    messages.info(request, 'Basket emptied.')
    return redirect('cart')


def cart_view(request):
    cart = get_cart(request)
    items = cart_items(cart)
    return render(request, 'store/cart.html', {
        'items': items,
        'total': cart_total(cart),
        'has_stock_issues': cart_has_stock_conflict(cart) if cart else False,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def checkout(request):
    cart = get_cart(request)
    if cart is None or not cart.items.exists():
        messages.info(request, 'Your basket is empty.')
        return redirect('shop')
    items = cart_items(cart)
    subtotal = cart_total(cart)
    shipping_fee = Decimal(str(getattr(settings, 'SHIPPING_FEE', '0')))
    total = subtotal + shipping_fee
    profile = getattr(request.user, 'customer_profile', None)
    initial = {
        'full_name': request.user.get_full_name() or request.user.username,
        'phone_number': request.user.phone_number or '',
        'shipping_address': profile.shipping_address if profile else '',
        'city': profile.city if profile and profile.city else 'Kampala',
    }
    form = CheckoutForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            result = create_order(
                user=request.user,
                cart=cart,
                full_name=form.cleaned_data['full_name'],
                phone=form.cleaned_data['phone_number'],
                address=form.cleaned_data['shipping_address'],
                city=form.cleaned_data['city'],
                expected_total=total,
            )
        except CheckoutError as exc:
            messages.error(request, exc.message)
            return redirect('cart')
        CustomerProfile.objects.update_or_create(
            user=request.user,
            defaults={
                'shipping_address': form.cleaned_data['shipping_address'],
                'city': form.cleaned_data['city'],
                'country': 'Uganda',
            },
        )
        if request.user.phone_number != form.cleaned_data['phone_number']:
            request.user.phone_number = form.cleaned_data['phone_number']
            request.user.save(update_fields=['phone_number'])
        messages.success(request, f'Order {result.order.reference} created. Complete payment to confirm it.')
        return redirect('payment_page', order_id=result.order.pk)
    return render(request, 'store/checkout.html', {
        'items': items,
        'subtotal': subtotal,
        'shipping_fee': shipping_fee,
        'total': total,
        'form': form,
        'has_stock_issues': cart_has_stock_conflict(cart),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def payment_page(request, order_id):
    order = get_object_or_404(Order.objects.select_related('customer'), pk=order_id)
    if order.customer_id != request.user.pk and not is_admin(request.user):
        raise Http404('Order not found.')
    if request.method == 'POST':
        outcome = 'success' if request.POST.get('outcome') == 'success' else 'failure'
        try:
            process_mock_payment(order, outcome=outcome, by=request.user)
        except PaymentError as exc:
            messages.error(request, exc.message)
        else:
            if outcome == 'success':
                messages.success(request, 'Payment approved in test mode. Your order is now paid.')
            else:
                messages.error(request, 'The mock gateway declined the payment. You can try again.')
        return redirect('order_detail', order_id=order.pk)
    return render(request, 'store/payment.html', {
        'order': order,
        'payment': getattr(order, 'payment', None),
        'items': order.items.all(),
        'settings_gateway': 'MOCK',
        'is_paid': order.status != 'PENDING',
    })


# ---------------------------------------------------------------------------
# Customer account
# ---------------------------------------------------------------------------
@login_required
def account(request):
    orders = (
        Order.objects.filter(customer=request.user)
        .prefetch_related('items', 'status_events')
        .order_by('-created_at')
    )
    return render(request, 'store/account.html', {
        'orders': orders,
        'disputes': request.user.disputes.select_related('order').order_by('-created_at')[:5],
    })


@login_required
def order_detail(request, order_id):
    order = _visible_order_or_404(request, order_id)
    seller = getattr(request.user, 'seller_profile', None)
    is_seller_view = bool(seller and order.customer_id != request.user.pk)
    items = order.items.all()
    if is_seller_view:
        items = [item for item in items if item.seller_id == seller.pk]
    open_dispute = order.disputes.filter(status__in=('OPEN', 'UNDER_REVIEW')).first()
    can_dispute = (
        order.customer_id == request.user.pk
        and order.status in ('PAID', 'SHIPPED', 'DELIVERED')
        and open_dispute is None
    )
    return render(request, 'store/order_detail.html', {
        'order': order,
        'items': items,
        'payment': getattr(order, 'payment', None),
        'shipment': getattr(order, 'shipment', None),
        'timeline': _order_timeline(order),
        'status_events': order.status_events.all(),
        'disputes': order.disputes.all(),
        'open_dispute': open_dispute,
        'can_dispute': can_dispute,
        'dispute_form': DisputeForm(),
        'is_seller_view': is_seller_view,
        'can_review': order.status in ('PAID', 'SHIPPED', 'DELIVERED') and order.customer_id == request.user.pk,
    })


@login_required
@require_POST
def order_cancel(request, order_id):
    order = _visible_order_or_404(request, order_id)
    if order.customer_id != request.user.pk:
        raise Http404('Order not found.')
    try:
        cancel_order(order, by=request.user, reason=request.POST.get('reason', 'Cancelled by customer'))
    except OrderError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'Order cancelled and stock returned to the seller.')
    return redirect('order_detail', order_id=order.pk)


@login_required
@require_POST
def order_dispute(request, order_id):
    order = _visible_order_or_404(request, order_id)
    if order.customer_id != request.user.pk:
        raise Http404('Order not found.')
    form = DisputeForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please choose a reason and describe the problem in at least 10 characters.')
        return redirect('order_detail', order_id=order.pk)
    if Dispute.objects.filter(order=order, status__in=('OPEN', 'UNDER_REVIEW')).exists():
        messages.error(request, 'There is already an open dispute for this order.')
        return redirect('order_detail', order_id=order.pk)
    Dispute.objects.create(
        order=order,
        raised_by=request.user,
        reason=form.cleaned_data['reason'],
        description=form.cleaned_data['description'],
    )
    messages.success(request, 'Your dispute has been opened. An administrator will review it.')
    return redirect('order_detail', order_id=order.pk)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('account')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            if user.role == 'SELLER':
                SellerProfile.objects.create(
                    user=user,
                    store_name=form.cleaned_data['store_name'],
                    store_description=form.cleaned_data.get('store_description', ''),
                    phone_number=form.cleaned_data.get('phone_number', ''),
                )
            else:
                CustomerProfile.objects.get_or_create(user=user)
        merge_session_cart_into_user(request, user)
        auth_login(request, user)
        if user.role == 'SELLER':
            messages.success(request, 'Seller application received. You can list products once approved.')
        else:
            messages.success(request, 'Welcome to Rukomeza Market!')
        return redirect('account')
    return render(request, 'store/register.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('account')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if user.is_blocked:
            messages.error(request, 'This account has been blocked. Please contact support.')
            return render(request, 'store/login.html', {'form': form})
        merge_session_cart_into_user(request, user)
        auth_login(request, user)
        messages.success(request, f'Welcome back, {user.display_name}.')
        next_url = request.GET.get('next') or request.POST.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect('account')
    return render(request, 'store/login.html', {'form': form})


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.info(request, 'You have been signed out.')
    return redirect('home')


# ---------------------------------------------------------------------------
# Seller studio
# ---------------------------------------------------------------------------
@seller_required
def seller_dashboard(request):
    seller = getattr(request.user, 'seller_profile', None)
    if seller is None:
        messages.error(request, 'No store is linked to this account.')
        return redirect('account')
    products = (
        Product.objects.filter(seller=seller)
        .select_related('category')
        .prefetch_related('images')
        .annotate(stock_quantity=F('inventory__stock_quantity'))
        .order_by('-created_at')
    )
    orders = (
        Order.objects.filter(items__seller=seller)
        .distinct()
        .select_related('customer')
        .prefetch_related('items')
        .order_by('-created_at')[:8]
    )
    summary = reports.seller_summary(seller)
    return render(request, 'store/seller_dashboard.html', {
        'seller': seller,
        'products': products,
        'orders': orders,
        'summary': summary,
        'form': ProductForm(),
        'low_stock': [row for row in reports.low_stock(limit=100) if row['seller'] == seller.store_name],
    })


@seller_required
@require_POST
def seller_product_create(request):
    seller = getattr(request.user, 'seller_profile', None)
    if seller is None:
        raise Http404('Seller profile missing.')
    if not seller.is_open_for_business:
        messages.error(request, 'Your store must be approved before listing products.')
        return redirect('seller_dashboard')
    form = ProductForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Please correct the product form errors.')
        products = (
            Product.objects.filter(seller=seller)
            .select_related('category')
            .annotate(stock_quantity=F('inventory__stock_quantity'))
            .order_by('-created_at')
        )
        return render(request, 'store/seller_dashboard.html', {
            'seller': seller,
            'products': products,
            'orders': Order.objects.filter(items__seller=seller).distinct()[:8],
            'summary': reports.seller_summary(seller),
            'form': form,
            'low_stock': reports.low_stock(limit=100),
        })
    with transaction.atomic():
        product = form.save(commit=False)
        product.seller = seller
        product.save()
        Inventory.objects.update_or_create(
            product=product,
            defaults={'stock_quantity': form.cleaned_data['stock_quantity']},
        )
        image_url = form.cleaned_data.get('image_url', '').strip()
        if image_url:
            ProductImage.objects.create(
                product=product,
                external_url=image_url,
                alt_text=product.name,
                is_primary=True,
            )
        elif product.image:
            ProductImage.objects.create(
                product=product,
                image=product.image,
                alt_text=product.name,
                is_primary=True,
            )
    messages.success(request, f'{product.name} is now live in your store.')
    return redirect('seller_dashboard')


@seller_required
@require_http_methods(['GET', 'POST'])
def seller_product_edit(request, product_id):
    seller = getattr(request.user, 'seller_profile', None)
    product = get_object_or_404(Product, pk=product_id, seller=seller)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            Inventory.objects.update_or_create(
                product=product,
                defaults={'stock_quantity': form.cleaned_data['stock_quantity']},
            )
            image_url = form.cleaned_data.get('image_url', '').strip()
            if image_url:
                ProductImage.objects.update_or_create(
                    product=product,
                    is_primary=True,
                    defaults={'external_url': image_url, 'alt_text': product.name},
                )
        messages.success(request, 'Product updated.')
        return redirect('seller_dashboard')
    return render(request, 'store/seller_product_form.html', {'form': form, 'product': product, 'seller': seller})


@seller_required
@require_POST
def seller_product_toggle(request, product_id):
    seller = getattr(request.user, 'seller_profile', None)
    product = get_object_or_404(Product, pk=product_id, seller=seller)
    product.is_active = not product.is_active
    product.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'{product.name} is now {"active" if product.is_active else "inactive"}.')
    return redirect('seller_dashboard')


@seller_required
@require_POST
def seller_stock_update(request, product_id):
    seller = getattr(request.user, 'seller_profile', None)
    product = get_object_or_404(Product, pk=product_id, seller=seller)
    form = StockForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter a valid stock level (0 or more).')
        return redirect('seller_dashboard')
    with transaction.atomic():
        inventory = Inventory.objects.select_for_update().filter(product=product).first()
        if inventory is None:
            inventory = Inventory.objects.create(product=product, stock_quantity=form.cleaned_data['stock_quantity'])
        else:
            inventory.stock_quantity = form.cleaned_data['stock_quantity']
            inventory.save(update_fields=['stock_quantity', 'updated_at'])
    messages.success(request, f'Stock for {product.name} set to {inventory.stock_quantity}.')
    return redirect('seller_dashboard')


@seller_required
def seller_orders(request):
    seller = getattr(request.user, 'seller_profile', None)
    orders = (
        Order.objects.filter(items__seller=seller)
        .distinct()
        .select_related('customer')
        .prefetch_related('items', 'status_events')
        .order_by('-created_at')
    )
    status_filter = request.GET.get('status', '').upper()
    if status_filter in dict(Order._meta.get_field('status').choices):
        orders = orders.filter(status=status_filter)
    return render(request, 'store/seller_orders.html', {
        'seller': seller,
        'orders': orders,
        'selected_status': status_filter,
    })


# ---------------------------------------------------------------------------
# Administrator dashboard
# ---------------------------------------------------------------------------
@admin_required
def admin_dashboard(request):
    revenue_labels, revenue_values = _monthly_series()
    summary = reports.summary()
    seller_rows = reports.sales_per_seller()[:6]
    return render(request, 'store/admin_dashboard.html', {
        'summary': summary,
        'revenue_labels': revenue_labels,
        'revenue_values': revenue_values,
        'seller_labels': [row['store_name'] for row in seller_rows],
        'seller_values': [float(row['revenue']) for row in seller_rows],
        'sales_per_seller': seller_rows,
        'best_sellers': reports.best_sellers(6),
        'low_stock': reports.low_stock(6),
        'pending_sellers': SellerProfile.objects.filter(is_approved=False, is_suspended=False).select_related('user')[:5],
        'open_disputes': Dispute.objects.filter(status__in=('OPEN', 'UNDER_REVIEW')).select_related('order', 'raised_by')[:5],
        'recent_orders': reports.recent_orders(6),
        'new_orders': Order.objects.filter(status='PAID').count(),
    })


@admin_required
def admin_users(request):
    users = get_user_model().objects.all()
    role = request.GET.get('role', '').upper()
    if role in dict(get_user_model().ROLE_CHOICES):
        users = users.filter(role=role)
    q = request.GET.get('q', '').strip()
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q))
    return render(request, 'store/admin_users.html', {
        'users': users.order_by('username'),
        'selected_role': role,
        'q': q,
    })


@admin_required
@require_POST
def admin_user_action(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk:
        messages.error(request, 'You cannot change your own access here.')
        return redirect('admin_users')
    action = request.POST.get('action')
    if action == 'toggle_active':
        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        messages.success(request, f'{target.username} is now {"active" if target.is_active else "deactivated"}.')
    elif action == 'toggle_blocked':
        target.is_blocked = not target.is_blocked
        target.save(update_fields=['is_blocked'])
        messages.success(request, f'{target.username} is now {"blocked" if target.is_blocked else "unblocked"}.')
    else:
        messages.error(request, 'Unknown action.')
    return redirect('admin_users')


@admin_required
def admin_sellers(request):
    sellers = SellerProfile.objects.select_related('user').order_by('-created_at')
    status = request.GET.get('status', '').upper()
    if status == 'PENDING':
        sellers = sellers.filter(is_approved=False, is_suspended=False)
    elif status == 'APPROVED':
        sellers = sellers.filter(is_approved=True, is_suspended=False)
    elif status == 'SUSPENDED':
        sellers = sellers.filter(is_suspended=True)
    return render(request, 'store/admin_sellers.html', {'sellers': sellers, 'selected_status': status})


@admin_required
@require_POST
def admin_seller_action(request, seller_id):
    seller = get_object_or_404(SellerProfile.objects.select_related('user'), pk=seller_id)
    action = request.POST.get('action')
    if action == 'approve':
        seller.is_approved = True
        seller.is_suspended = False
        seller.approved_at = seller.approved_at or timezone.now()
        if not seller.user.is_staff and not seller.user.is_superuser:
            seller.user.role = 'SELLER'
            seller.user.save(update_fields=['role'])
        messages.success(request, f'{seller.store_name} approved.')
    elif action == 'suspend':
        seller.is_suspended = True
        messages.warning(request, f'{seller.store_name} suspended. Its listings are hidden.')
    elif action == 'reinstate':
        if not seller.is_approved:
            messages.error(request, 'Approve this seller before reinstating.')
        else:
            seller.is_suspended = False
            messages.success(request, f'{seller.store_name} reinstated.')
    elif action == 'reject':
        seller.is_approved = False
        seller.is_suspended = True
        messages.warning(request, f'{seller.store_name} rejected.')
    else:
        messages.error(request, 'Unknown seller action.')
    seller.save()
    return redirect('admin_sellers')


@admin_required
@require_http_methods(['GET', 'POST'])
def admin_categories(request):
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Category created.')
        return redirect('admin_categories')
    categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
    return render(request, 'store/admin_categories.html', {'categories': categories, 'form': form})


@admin_required
@require_POST
def admin_category_edit(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    form = CategoryForm(request.POST, instance=category)
    if form.is_valid():
        form.save()
        messages.success(request, 'Category updated.')
    else:
        messages.error(request, 'Category could not be updated.')
    return redirect('admin_categories')


@admin_required
@require_POST
def admin_category_delete(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    if category.products.exists():
        messages.error(request, 'Move or delete this category\'s products first.')
    else:
        category.delete()
        messages.success(request, 'Category deleted.')
    return redirect('admin_categories')


@admin_required
def admin_orders(request):
    orders = (
        Order.objects.select_related('customer')
        .prefetch_related('items', 'status_events')
        .order_by('-created_at')
    )
    status = request.GET.get('status', '').upper()
    if status in dict(Order._meta.get_field('status').choices):
        orders = orders.filter(status=status)
    q = request.GET.get('q', '').strip()
    if q:
        orders = orders.filter(Q(reference__icontains=q) | Q(customer__username__icontains=q))
    return render(request, 'store/admin_orders.html', {
        'orders': orders,
        'selected_status': status,
        'q': q,
    })


@admin_required
def admin_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('customer').prefetch_related('items', 'status_events', 'disputes'),
        pk=order_id,
    )
    return render(request, 'store/admin_order_detail.html', {
        'order': order,
        'payment': getattr(order, 'payment', None),
        'shipment': getattr(order, 'shipment', None),
        'timeline': _order_timeline(order),
        'status_events': order.status_events.all(),
        'next_statuses': order.allowed_next_statuses(),
    })


@admin_required
@require_POST
def admin_order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    target = request.POST.get('status', '').upper()
    try:
        transition_order(
            order,
            target,
            by=request.user,
            note=request.POST.get('note', 'Updated by administrator'),
            courier=request.POST.get('courier', ''),
            tracking_number=request.POST.get('tracking_number', ''),
        )
    except OrderError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f'Order {order.reference} is now {target.title()}.')
    return redirect('admin_order_detail', order_id=order.pk)


@admin_required
def admin_disputes(request):
    disputes = Dispute.objects.select_related('order', 'raised_by').order_by('-created_at')
    status = request.GET.get('status', '').upper()
    if status in dict(Dispute.Status.choices):
        disputes = disputes.filter(status=status)
    return render(request, 'store/admin_disputes.html', {'disputes': disputes, 'selected_status': status})


@admin_required
@require_POST
def admin_dispute_resolve(request, dispute_id):
    dispute = get_object_or_404(Dispute, pk=dispute_id)
    status = request.POST.get('status', '').upper()
    note = request.POST.get('resolution_note', '').strip()
    if status not in dict(Dispute.Status.choices):
        messages.error(request, 'Invalid dispute status.')
    elif status in ('RESOLVED', 'REJECTED') and not note:
        messages.error(request, 'Add a resolution note before closing the dispute.')
    else:
        dispute.status = status
        dispute.resolution_note = note
        if status in ('RESOLVED', 'REJECTED'):
            dispute.resolved_by = request.user
            dispute.resolved_at = timezone.now()
        dispute.save()
        messages.success(request, 'Dispute updated.')
    return redirect('admin_disputes')


@admin_required
def admin_reports(request):
    revenue_labels, revenue_values = _monthly_series()
    period = request.GET.get('period', 'month').lower()
    if period not in ('day', 'week', 'month', 'year'):
        period = 'month'
    category_rows = reports.sales_per_category()
    return render(request, 'store/admin_reports.html', {
        'summary': reports.summary(),
        'revenue_labels': revenue_labels,
        'revenue_values': revenue_values,
        'category_labels': [row['category'] for row in category_rows],
        'category_values': [float(row['revenue']) for row in category_rows],
        'revenue_rows': reports.revenue_per_period(period),
        'sales_per_seller': reports.sales_per_seller(),
        'best_sellers': reports.best_sellers(10),
        'low_stock': reports.low_stock(50),
        'category_sales': reports.sales_per_category(),
        'period': period,
    })


# ---------------------------------------------------------------------------
# Operational endpoints
# ---------------------------------------------------------------------------
def healthz(request):
    database_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:  # pragma: no cover - only on infrastructure failure
        database_ok = False
    return JsonResponse(
        {
            'status': 'ok' if database_ok else 'degraded',
            'database': database_ok,
            'time': timezone.now().isoformat(),
            'version': getattr(settings, 'APP_VERSION', '1.0.0'),
            'debug': settings.DEBUG,
        },
        status=200 if database_ok else 503,
    )


def openapi_spec(request):
    path = settings.BASE_DIR / 'docs' / 'openapi.yaml'
    if not path.exists():
        raise Http404('OpenAPI specification not found.')
    return FileResponse(path.open('rb'), content_type='application/yaml')


def api_docs(request):
    return render(request, 'store/api_docs.html')
