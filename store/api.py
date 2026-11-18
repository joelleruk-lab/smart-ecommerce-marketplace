"""REST API (JSON over HTTPS) for the Rukomeza marketplace.

Authentication: opaque bearer tokens (``Authorization: Bearer <token>``).
All money values are serialised as decimal strings.  See ``docs/openapi.yaml``
for the full contract.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .api_auth import (
    api_login_required,
    api_role_required,
    error_response,
    issue_token,
    json_body,
    ok,
    verify_webhook_signature,
)
from .api_serializers import (
    cart_payload,
    category_payload,
    money,
    order_payload,
    paginated,
    payment_payload,
    product_payload,
    review_payload,
    seller_payload,
    user_payload,
)
from .forms import RegistrationForm
from .models import (
    Cart,
    Category,
    Dispute,
    Inventory,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductImage,
    Review,
    SellerProfile,
    Shipment,
)
from .services import catalogue, reports
from .services.cart import CartError, add_item, clear as clear_cart, remove_item, update_item
from .services.checkout import CheckoutError, create_order
from .services.orders import OrderError, cancel_order, transition_order
from .services.payments import PaymentError, process_mock_payment


User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _page_params(request, default_size: int = 12, max_size: int = 60):
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.GET.get('page_size', default_size))
    except (TypeError, ValueError):
        page_size = default_size
    page_size = min(max(page_size, 1), max_size)
    return page, page_size


def _paginate(queryset, page: int, page_size: int, serializer, *, extra=None):
    total = queryset.count()
    start = (page - 1) * page_size
    rows = [serializer(obj) for obj in queryset[start:start + page_size]]
    return ok(paginated(rows, page=page, page_size=page_size, total=total, **(extra or {})))


def _user_cart(user, *, create: bool = False):
    cart = Cart.objects.filter(user=user).first()
    if cart is None and create:
        cart = Cart.objects.create(user=user)
    return cart


def _cart_owner_cart(request, *, create: bool = False):
    return _user_cart(request.api_user, create=create)


def _int_field(payload, key, *, minimum=None, maximum=None):
    if key not in payload:
        raise ValueError(f'"{key}" is required.')
    try:
        value = int(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f'"{key}" must be an integer.') from exc
    if minimum is not None and value < minimum:
        raise ValueError(f'"{key}" must be at least {minimum}.')
    if maximum is not None and value > maximum:
        raise ValueError(f'"{key}" must be at most {maximum}.')
    return value


def _decimal_field(payload, key, *, minimum=Decimal('0.01')):
    value = payload.get(key)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'"{key}" must be a number.') from exc
    if parsed < minimum:
        raise ValueError(f'"{key}" must be at least {minimum}.')
    return parsed


def _get_product(product_id):
    product = (
        catalogue.available_products()
        .prefetch_related('images')
        .filter(pk=product_id)
        .first()
    )
    if product is None:
        raise Http404('Product not found.')
    return product


def _get_order_for(user, order_id: int, *, detail=True):
    order = (
        Order.objects.select_related('customer')
        .prefetch_related('items', 'status_events', 'disputes')
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        raise Http404('Order not found.')
    seller_id = None
    if user.role == 'ADMIN' or user.is_staff:
        pass
    elif order.customer_id == user.pk:
        pass
    elif user.role == 'SELLER':
        seller = getattr(user, 'seller_profile', None)
        if seller is None or not order.items.filter(seller=seller).exists():
            raise Http404('Order not found.')
        seller_id = seller.pk
    else:
        raise Http404('Order not found.')
    return order, seller_id


def _api_error(exc, *, status=400):
    return error_response(str(exc), getattr(exc, 'code', 'error'), status)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def register(request):
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    form = RegistrationForm(payload)
    if not form.is_valid():
        return error_response('Registration failed.', 'validation_error', 400, form.errors.get_json_data())
    with transaction.atomic():
        user = form.save()
        if user.role == 'SELLER':
            SellerProfile.objects.create(
                user=user,
                store_name=form.cleaned_data['store_name'],
                store_description=form.cleaned_data.get('store_description', ''),
            )
        else:
            from .models import CustomerProfile

            CustomerProfile.objects.get_or_create(user=user)
    token = issue_token(user, label='api-register')
    return ok({'user': user_payload(user), 'token': token, 'token_type': 'Bearer'}, status=201)


@csrf_exempt
@require_POST
def login(request):
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    identifier = str(payload.get('username') or payload.get('email') or '').strip()
    password = str(payload.get('password') or '')
    if not identifier or not password:
        return error_response('Username/email and password are required.', 'validation_error', 400)
    match = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).first()
    user = authenticate(request, username=match.username, password=password) if match else None
    if user is None:
        return error_response('Invalid credentials.', 'invalid_credentials', 401)
    if user.is_blocked:
        return error_response('This account has been blocked. Contact support.', 'account_blocked', 403)
    token = issue_token(user, label='api-login')
    return ok({'user': user_payload(user), 'token': token, 'token_type': 'Bearer'})


@csrf_exempt
@require_POST
@api_login_required
def logout(request):
    if request.api_token:
        request.api_token.revoked = True
        request.api_token.save(update_fields=['revoked'])
    return ok({'message': 'Token revoked.'})


@require_GET
@api_login_required
def me(request):
    user = request.api_user
    seller = getattr(user, 'seller_profile', None)
    return ok({
        'user': user_payload(user),
        'seller_profile': seller_payload(seller) if seller else None,
    })


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@require_GET
def product_list(request):
    qs = catalogue.filter_products(
        q=request.GET.get('q', ''),
        category=request.GET.get('category', ''),
        min_price=request.GET.get('min_price'),
        max_price=request.GET.get('max_price'),
        seller=request.GET.get('seller', ''),
        sort=request.GET.get('sort', 'newest'),
        in_stock_only=request.GET.get('in_stock', '').lower() in ('1', 'true', 'yes'),
    )
    if 'rating_average' not in qs.query.annotations:
        qs = qs.annotate(
            rating_average=Avg('reviews__rating'),
            reviews_total=Count('reviews', distinct=True),
        )
    qs = qs.prefetch_related('images')
    page, page_size = _page_params(request)
    return _paginate(qs, page, page_size, lambda product: product_payload(product), extra={'sort': request.GET.get('sort', 'newest')})


@require_GET
def product_detail(request, product_id: int):
    product = _get_product(product_id)
    reviews = product.reviews.select_related('customer').order_by('-created_at')[:20]
    payload = product_payload(product, detail=True)
    payload['recent_reviews'] = [review_payload(review) for review in reviews]
    return ok(payload)


@require_GET
def product_reviews(request, product_id: int):
    product = get_object_or_404(Product, pk=product_id)
    qs = product.reviews.select_related('customer').order_by('-created_at')
    page, page_size = _page_params(request)
    total = qs.count()
    start = (page - 1) * page_size
    rows = [review_payload(review) for review in qs[start:start + page_size]]
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


@csrf_exempt
@require_POST
@api_role_required('CUSTOMER')
def create_review(request, product_id: int):
    product = get_object_or_404(Product, pk=product_id)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    try:
        rating = _int_field(payload, 'rating', minimum=1, maximum=5)
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    comment = str(payload.get('comment') or '').strip()
    if not comment:
        return error_response('A review comment is required.', 'validation_error', 400)
    if len(comment) > 2000:
        return error_response('Reviews must be 2000 characters or fewer.', 'validation_error', 400)
    order_item = (
        OrderItem.objects.filter(
            product=product,
            order__customer=request.api_user,
            order__status__in=('PAID', 'SHIPPED', 'DELIVERED'),
        )
        .select_related('order')
        .order_by('-order__created_at')
        .first()
    )
    if order_item is None:
        return error_response(
            'Only customers who have paid for this product can review it.',
            'verified_purchase_required',
            403,
        )
    if Review.objects.filter(customer=request.api_user, product=product).exists():
        return error_response('You have already reviewed this product.', 'duplicate_review', 409)
    review = Review.objects.create(
        customer=request.api_user,
        product=product,
        order_item=order_item,
        rating=rating,
        comment=comment,
        is_verified_purchase=True,
    )
    return ok(review_payload(review), status=201)


@require_GET
def category_list(request):
    categories = (
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
    return ok([category_payload(category) for category in categories])


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
@require_GET
@api_login_required
def cart_detail(request):
    return ok(cart_payload(_cart_owner_cart(request)))


@csrf_exempt
@require_POST
@api_login_required
def cart_add(request):
    try:
        payload = json_body(request)
        product_id = _int_field(payload, 'product_id', minimum=1)
        quantity = _int_field(payload, 'quantity', minimum=1, maximum=99)
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    product = Product.objects.filter(pk=product_id, is_active=True).select_related('seller').first()
    if product is None or not product.seller.is_open_for_business:
        return error_response('Product is not available.', 'product_unavailable', 404)
    cart = _cart_owner_cart(request, create=True)
    try:
        add_item(cart, product, quantity)
    except CartError as exc:
        return error_response(exc.message, exc.code, 409)
    return ok(cart_payload(cart), status=201)


@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
@api_login_required
def cart_item(request, product_id: int):
    cart = _cart_owner_cart(request)
    if cart is None:
        return error_response('Cart is empty.', 'empty_cart', 404)
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return error_response('Product not found.', 'not_found', 404)
    if request.method == 'DELETE':
        if not remove_item(cart, product):
            return error_response('Product is not in the cart.', 'not_in_cart', 404)
        return ok(cart_payload(cart))
    try:
        payload = json_body(request)
        quantity = _int_field(payload, 'quantity', minimum=0, maximum=99)
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    try:
        update_item(cart, product, quantity)
    except CartError as exc:
        return error_response(exc.message, exc.code, 409)
    return ok(cart_payload(cart))


@csrf_exempt
@require_http_methods(['DELETE'])
@api_login_required
def cart_clear(request):
    cart = _cart_owner_cart(request)
    if cart:
        clear_cart(cart)
    return ok(cart_payload(cart))


# ---------------------------------------------------------------------------
# Orders & payment
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@api_role_required('CUSTOMER')
def order_create(request):
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    cart = _cart_owner_cart(request)
    if cart is None or not cart.items.exists():
        return error_response('Your cart is empty.', 'empty_cart', 400)
    required = ('full_name', 'phone', 'address', 'city')
    missing = [field for field in required if not str(payload.get(field, '')).strip()]
    if missing:
        return error_response('Missing delivery fields.', 'validation_error', 400, {'missing': missing})
    gateway = str(payload.get('gateway') or 'MOCK').upper()
    if gateway != Payment.Gateway.MOCK:
        return error_response(
            'Only the documented mock gateway is enabled in this deployment.',
            'gateway_not_configured',
            400,
        )
    try:
        result = create_order(
            user=request.api_user,
            cart=cart,
            full_name=payload['full_name'],
            phone=payload['phone'],
            address=payload['address'],
            city=payload['city'],
            gateway=gateway,
            expected_total=payload.get('expected_total'),
        )
    except CheckoutError as exc:
        return error_response(exc.message, exc.code, 409, exc.details)
    order = (
        Order.objects.select_related('customer')
        .prefetch_related('items', 'status_events', 'disputes')
        .get(pk=result.order.pk)
    )
    return ok(order_payload(order, detail=True), status=201)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def orders_collection(request):
    """GET lists orders; POST creates one from the caller's cart."""
    if request.method == 'GET':
        return order_list(request)
    return order_create(request)


@require_GET
@api_login_required
def order_list(request):
    user = request.api_user
    qs = Order.objects.select_related('customer').prefetch_related('items', 'status_events', 'disputes')
    if user.role == 'ADMIN' or user.is_staff:
        pass
    elif user.role == 'SELLER':
        seller = getattr(user, 'seller_profile', None)
        qs = qs.filter(items__seller=seller).distinct() if seller else qs.none()
    else:
        qs = qs.filter(customer=user)
    status_filter = request.GET.get('status', '').upper()
    if status_filter in dict(Order._meta.get_field('status').choices):
        qs = qs.filter(status=status_filter)
    qs = qs.order_by('-created_at')
    page, page_size = _page_params(request, default_size=20)
    total = qs.count()
    start = (page - 1) * page_size
    rows = []
    seller_id = getattr(getattr(user, 'seller_profile', None), 'pk', None)
    for order in qs[start:start + page_size]:
        rows.append(order_payload(order, seller_id=seller_id if user.role == 'SELLER' else None))
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


@require_GET
@api_login_required
def order_detail(request, order_id: int):
    order, seller_id = _get_order_for(request.api_user, order_id)
    return ok(order_payload(order, detail=True, seller_id=seller_id))


@csrf_exempt
@require_POST
@api_login_required
def order_cancel(request, order_id: int):
    order, seller_id = _get_order_for(request.api_user, order_id)
    if request.api_user.role == 'SELLER':
        return error_response('Sellers cannot cancel customer orders.', 'forbidden', 403)
    try:
        payload = json_body(request)
    except ValueError:
        payload = {}
    reason = str(payload.get('reason') or 'Cancelled by customer').strip()[:255]
    try:
        cancel_order(order, by=request.api_user, reason=reason)
    except OrderError as exc:
        return error_response(exc.message, exc.code, 409)
    order.refresh_from_db()
    return ok(order_payload(order, detail=True))


@require_GET
@api_login_required
def order_tracking(request, order_id: int):
    order, _ = _get_order_for(request.api_user, order_id)
    shipment = getattr(order, 'shipment', None)
    return ok({
        'order_id': order.pk,
        'reference': order.reference,
        'status': order.status,
        'status_display': order.get_status_display(),
        'timeline': [
            {
                'from': event.from_status,
                'to': event.to_status,
                'note': event.note,
                'at': event.created_at.isoformat(),
            }
            for event in order.status_events.all()
        ],
        'shipment': {
            'courier': shipment.courier,
            'tracking_number': shipment.tracking_number,
            'status': shipment.status,
            'shipped_at': shipment.shipped_at.isoformat() if shipment.shipped_at else None,
            'delivered_at': shipment.delivered_at.isoformat() if shipment.delivered_at else None,
        } if shipment else None,
    })


@csrf_exempt
@require_POST
@api_role_required('CUSTOMER')
def order_dispute(request, order_id: int):
    order, _ = _get_order_for(request.api_user, order_id)
    if order.customer_id != request.api_user.pk:
        return error_response('You can only dispute your own orders.', 'forbidden', 403)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    reason = str(payload.get('reason') or '').upper()
    if reason not in dict(Dispute.Reason.choices):
        return error_response('Choose a valid dispute reason.', 'validation_error', 400)
    description = str(payload.get('description') or '').strip()
    if len(description) < 10:
        return error_response('Describe the problem in at least 10 characters.', 'validation_error', 400)
    if Dispute.objects.filter(order=order, status__in=('OPEN', 'UNDER_REVIEW')).exists():
        return error_response('There is already an open dispute for this order.', 'duplicate_dispute', 409)
    dispute = Dispute.objects.create(
        order=order,
        raised_by=request.api_user,
        reason=reason,
        description=description,
    )
    return ok(
        {
            'id': dispute.pk,
            'order_id': order.pk,
            'reason': dispute.reason,
            'status': dispute.status,
            'description': dispute.description,
            'created_at': dispute.created_at.isoformat(),
        },
        status=201,
    )


@csrf_exempt
@require_POST
@api_login_required
def payment_pay(request, order_id: int):
    order, _ = _get_order_for(request.api_user, order_id)
    if request.api_user.role == 'SELLER':
        return error_response('Sellers cannot pay customer orders.', 'forbidden', 403)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    outcome = str(payload.get('outcome') or 'success').lower()
    try:
        payment = process_mock_payment(order, outcome=outcome, by=request.api_user)
    except PaymentError as exc:
        return error_response(exc.message, exc.code, 409)
    order.refresh_from_db()
    return ok({
        'payment': payment_payload(payment),
        'order_status': order.status,
        'order_id': order.pk,
    })


@require_GET
@api_login_required
def payment_detail(request, order_id: int):
    order, _ = _get_order_for(request.api_user, order_id)
    if request.api_user.role == 'SELLER':
        return error_response('Sellers cannot view customer payment details.', 'forbidden', 403)
    return ok({
        'order_id': order.pk,
        'order_status': order.status,
        'payment': payment_payload(getattr(order, 'payment', None)),
    })


@csrf_exempt
@require_POST
def payment_webhook(request):
    """Mock gateway callback.

    Production gateways post an event signed with a shared secret.  The mock
    mirrors that: ``X-Mock-Signature: HMAC_SHA256(MOCK_GATEWAY_SECRET, body)``.
    """
    if not verify_webhook_signature(request):
        return error_response('Invalid webhook signature.', 'invalid_signature', 401)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    reference = str(payload.get('reference') or '').strip()
    outcome = str(payload.get('outcome') or 'success').lower()
    payment = Payment.objects.filter(transaction_ref=reference).select_related('order').first()
    if payment is None:
        return error_response('Unknown payment reference.', 'not_found', 404)
    try:
        updated = process_mock_payment(payment.order, outcome=outcome)
    except PaymentError as exc:
        return error_response(exc.message, exc.code, 409)
    return ok({'reference': reference, 'status': updated.status, 'order_id': updated.order_id})


# ---------------------------------------------------------------------------
# Seller endpoints
# ---------------------------------------------------------------------------
def _seller_or_404(user) -> SellerProfile:
    seller = getattr(user, 'seller_profile', None)
    if seller is None:
        raise Http404('Seller profile not found.')
    return seller


@require_GET
@api_role_required('SELLER')
def seller_summary(request):
    seller = _seller_or_404(request.api_user)
    return ok({'seller': seller_payload(seller), 'summary': reports.seller_summary(seller)})


@require_GET
@api_role_required('SELLER')
def seller_products(request):
    seller = _seller_or_404(request.api_user)
    qs = (
        seller.products.select_related('category', 'seller')
        .prefetch_related('images')
        .annotate(stock_quantity=F('inventory__stock_quantity'))
        .order_by('-created_at')
    )
    page, page_size = _page_params(request, default_size=20)
    return _paginate(qs, page, page_size, lambda product: product_payload(product))


@csrf_exempt
@require_POST
@api_role_required('SELLER')
def seller_product_create(request):
    seller = _seller_or_404(request.api_user)
    if not seller.is_open_for_business:
        return error_response('Your store must be approved before you can list products.', 'store_not_approved', 403)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    try:
        name = str(payload.get('name') or '').strip()
        description = str(payload.get('description') or '').strip()
        if len(name) < 3:
            raise ValueError('"name" must be at least 3 characters.')
        if len(description) < 10:
            raise ValueError('"description" must be at least 10 characters.')
        price = _decimal_field(payload, 'price')
        category_id = _int_field(payload, 'category_id', minimum=1)
        stock = _int_field(payload, 'stock_quantity', minimum=0, maximum=1_000_000)
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    category = Category.objects.filter(pk=category_id, is_active=True).first()
    if category is None:
        return error_response('Category not found.', 'not_found', 404)
    image_url = str(payload.get('image_url') or '').strip()
    with transaction.atomic():
        product = Product.objects.create(
            seller=seller,
            category=category,
            name=name,
            description=description,
            price=price,
            low_stock_threshold=int(payload.get('low_stock_threshold') or 5),
        )
        Inventory.objects.create(product=product, stock_quantity=stock)
        if image_url:
            ProductImage.objects.create(
                product=product,
                external_url=image_url,
                alt_text=name,
                is_primary=True,
            )
    return ok(product_payload(product, detail=True), status=201)


@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
@api_role_required('SELLER')
def seller_product_detail(request, product_id: int):
    seller = _seller_or_404(request.api_user)
    product = get_object_or_404(Product, pk=product_id, seller=seller)
    if request.method == 'DELETE':
        product.is_active = False
        product.save(update_fields=['is_active', 'updated_at'])
        return ok({'id': product.pk, 'is_active': False, 'message': 'Listing deactivated.'})
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    try:
        if 'name' in payload:
            name = str(payload['name']).strip()
            if len(name) < 3:
                raise ValueError('"name" must be at least 3 characters.')
            product.name = name
        if 'description' in payload:
            description = str(payload['description']).strip()
            if len(description) < 10:
                raise ValueError('"description" must be at least 10 characters.')
            product.description = description
        if 'price' in payload:
            product.price = _decimal_field(payload, 'price')
        if 'category_id' in payload:
            category = Category.objects.filter(pk=_int_field(payload, 'category_id', minimum=1), is_active=True).first()
            if category is None:
                raise ValueError('Category not found.')
            product.category = category
        if 'is_active' in payload:
            product.is_active = bool(payload['is_active'])
        if 'low_stock_threshold' in payload:
            product.low_stock_threshold = _int_field(payload, 'low_stock_threshold', minimum=0, maximum=10_000)
        if 'stock_quantity' in payload:
            stock = _int_field(payload, 'stock_quantity', minimum=0, maximum=1_000_000)
            Inventory.objects.update_or_create(product=product, defaults={'stock_quantity': stock})
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    product.save()
    return ok(product_payload(product, detail=True))


@csrf_exempt
@require_http_methods(['PATCH'])
@api_role_required('SELLER')
def seller_inventory(request, product_id: int):
    seller = _seller_or_404(request.api_user)
    product = get_object_or_404(Product, pk=product_id, seller=seller)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    inventory = Inventory.objects.filter(product=product).first()
    if inventory is None:
        return error_response('This product has no inventory record.', 'not_found', 404)
    try:
        with transaction.atomic():
            inventory = Inventory.objects.select_for_update().get(pk=inventory.pk)
            if 'stock_quantity' in payload:
                new_value = _int_field(payload, 'stock_quantity', minimum=0, maximum=1_000_000)
            elif 'delta' in payload:
                new_value = inventory.stock_quantity + _int_field(payload, 'delta', minimum=-1_000_000, maximum=1_000_000)
                if new_value < 0:
                    raise ValueError('Stock cannot become negative.')
            else:
                raise ValueError('Provide "stock_quantity" or "delta".')
            Inventory.objects.filter(pk=inventory.pk).update(stock_quantity=new_value)
    except ValueError as exc:
        return error_response(str(exc), 'validation_error', 400)
    return ok({'product_id': product.pk, 'stock_quantity': new_value})


@require_GET
@api_role_required('SELLER')
def seller_orders(request):
    seller = _seller_or_404(request.api_user)
    qs = (
        Order.objects.filter(items__seller=seller)
        .select_related('customer')
        .prefetch_related('items', 'status_events', 'disputes')
        .distinct()
        .order_by('-created_at')
    )
    status_filter = request.GET.get('status', '').upper()
    if status_filter in dict(Order._meta.get_field('status').choices):
        qs = qs.filter(status=status_filter)
    page, page_size = _page_params(request, default_size=20)
    total = qs.count()
    start = (page - 1) * page_size
    rows = [order_payload(order, seller_id=seller.pk) for order in qs[start:start + page_size]]
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


# ---------------------------------------------------------------------------
# Administrator endpoints
# ---------------------------------------------------------------------------
@require_GET
@api_role_required('ADMIN')
def admin_users(request):
    qs = User.objects.all().order_by('username')
    role = request.GET.get('role', '').upper()
    if role in dict(User.ROLE_CHOICES):
        qs = qs.filter(role=role)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
    page, page_size = _page_params(request, default_size=25)
    return _paginate(qs, page, page_size, user_payload)


@csrf_exempt
@require_http_methods(['PATCH'])
@api_role_required('ADMIN')
def admin_user_detail(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    if target.pk == request.api_user.pk:
        return error_response('You cannot modify your own access from this endpoint.', 'forbidden', 403)
    if target.is_superuser:
        return error_response('Superuser access cannot be changed from the API.', 'forbidden', 403)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    if 'is_active' in payload:
        target.is_active = bool(payload['is_active'])
    if 'is_blocked' in payload:
        target.is_blocked = bool(payload['is_blocked'])
    target.save(update_fields=['is_active', 'is_blocked'])
    return ok(user_payload(target))


@require_GET
@api_role_required('ADMIN')
def admin_sellers(request):
    qs = SellerProfile.objects.select_related('user').order_by('store_name')
    status_filter = request.GET.get('status', '').upper()
    if status_filter == 'PENDING':
        qs = qs.filter(is_approved=False, is_suspended=False)
    elif status_filter == 'APPROVED':
        qs = qs.filter(is_approved=True, is_suspended=False)
    elif status_filter == 'SUSPENDED':
        qs = qs.filter(is_suspended=True)
    page, page_size = _page_params(request, default_size=25)
    total = qs.count()
    start = (page - 1) * page_size
    rows = []
    for seller in qs[start:start + page_size]:
        payload = seller_payload(seller)
        payload['user'] = user_payload(seller.user)
        payload['products'] = seller.products.count()
        rows.append(payload)
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


@csrf_exempt
@require_POST
@api_role_required('ADMIN')
def admin_seller_action(request, seller_id: int):
    seller = get_object_or_404(SellerProfile.objects.select_related('user'), pk=seller_id)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    action = str(payload.get('action') or '').lower()
    if action == 'approve':
        seller.is_approved = True
        seller.is_suspended = False
        seller.approved_at = seller.approved_at or timezone.now()
        if not seller.user.is_staff and not seller.user.is_superuser:
            seller.user.role = 'SELLER'
            seller.user.save(update_fields=['role'])
    elif action == 'suspend':
        seller.is_suspended = True
    elif action == 'reinstate':
        if not seller.is_approved:
            return error_response('Approve the seller before reinstating the store.', 'invalid_action', 409)
        seller.is_suspended = False
    elif action == 'reject':
        seller.is_approved = False
        seller.is_suspended = True
    else:
        return error_response('Action must be approve, suspend, reinstate or reject.', 'invalid_action', 400)
    seller.save()
    return ok(seller_payload(seller))


@csrf_exempt
@require_http_methods(['GET', 'POST'])
@api_role_required('ADMIN')
def admin_categories(request):
    if request.method == 'GET':
        categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
        return ok([category_payload(category) for category in categories])
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    name = str(payload.get('name') or '').strip()
    if len(name) < 2:
        return error_response('Category name is required.', 'validation_error', 400)
    if Category.objects.filter(name__iexact=name).exists():
        return error_response('A category with this name already exists.', 'duplicate_category', 409)
    category = Category.objects.create(
        name=name,
        icon=str(payload.get('icon') or '')[:16],
        description=str(payload.get('description') or ''),
        is_active=bool(payload.get('is_active', True)),
    )
    return ok(category_payload(category), status=201)


@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
@api_role_required('ADMIN')
def admin_category_detail(request, category_id: int):
    category = get_object_or_404(Category, pk=category_id)
    if request.method == 'DELETE':
        if category.products.exists():
            return error_response(
                'Move or delete this category\'s products before deleting it.',
                'category_in_use',
                409,
            )
        category.delete()
        return ok({'id': category_id, 'deleted': True})
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    if 'name' in payload:
        name = str(payload['name']).strip()
        if len(name) < 2:
            return error_response('Category name is required.', 'validation_error', 400)
        category.name = name
    if 'icon' in payload:
        category.icon = str(payload['icon'])[:16]
    if 'description' in payload:
        category.description = str(payload['description'])
    if 'is_active' in payload:
        category.is_active = bool(payload['is_active'])
    category.save()
    return ok(category_payload(category))


@require_GET
@api_role_required('ADMIN')
def admin_orders(request):
    qs = Order.objects.select_related('customer').prefetch_related('items', 'status_events', 'disputes').order_by('-created_at')
    status_filter = request.GET.get('status', '').upper()
    if status_filter in dict(Order._meta.get_field('status').choices):
        qs = qs.filter(status=status_filter)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(customer__username__icontains=q))
    page, page_size = _page_params(request, default_size=25)
    total = qs.count()
    start = (page - 1) * page_size
    rows = [order_payload(order) for order in qs[start:start + page_size]]
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


@csrf_exempt
@require_POST
@api_role_required('ADMIN')
def admin_order_status(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    target = str(payload.get('status') or '').upper()
    note = str(payload.get('note') or 'Updated by administrator')[:255]
    try:
        transition_order(
            order,
            target,
            by=request.api_user,
            note=note,
            courier=str(payload.get('courier') or ''),
            tracking_number=str(payload.get('tracking_number') or ''),
        )
    except OrderError as exc:
        return error_response(exc.message, exc.code, 409)
    order.refresh_from_db()
    return ok(order_payload(order, detail=True))


@require_GET
@api_role_required('ADMIN')
def admin_disputes(request):
    qs = Dispute.objects.select_related('order', 'raised_by').order_by('-created_at')
    status_filter = request.GET.get('status', '').upper()
    if status_filter in dict(Dispute.Status.choices):
        qs = qs.filter(status=status_filter)
    page, page_size = _page_params(request, default_size=25)
    total = qs.count()
    start = (page - 1) * page_size
    rows = [
        {
            'id': dispute.pk,
            'order_id': dispute.order_id,
            'order_reference': dispute.order.reference,
            'raised_by': dispute.raised_by.username,
            'reason': dispute.reason,
            'description': dispute.description,
            'status': dispute.status,
            'resolution_note': dispute.resolution_note,
            'created_at': dispute.created_at.isoformat(),
            'resolved_at': dispute.resolved_at.isoformat() if dispute.resolved_at else None,
        }
        for dispute in qs[start:start + page_size]
    ]
    return ok(paginated(rows, page=page, page_size=page_size, total=total))


@csrf_exempt
@require_http_methods(['PATCH'])
@api_role_required('ADMIN')
def admin_dispute_detail(request, dispute_id: int):
    dispute = get_object_or_404(Dispute, pk=dispute_id)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return error_response(str(exc), 'invalid_json', 400)
    status = str(payload.get('status') or '').upper()
    if status not in dict(Dispute.Status.choices):
        return error_response('Invalid dispute status.', 'validation_error', 400)
    note = str(payload.get('resolution_note') or '').strip()
    if status in ('RESOLVED', 'REJECTED') and not note:
        return error_response('A resolution note is required to close a dispute.', 'validation_error', 400)
    dispute.status = status
    dispute.resolution_note = note
    if status in ('RESOLVED', 'REJECTED'):
        dispute.resolved_by = request.api_user
        dispute.resolved_at = timezone.now()
    dispute.save()
    return ok({'id': dispute.pk, 'status': dispute.status, 'resolution_note': dispute.resolution_note})


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _decimal_rows(rows):
    return [
        {key: (money(value) if isinstance(value, Decimal) else value) for key, value in row.items()}
        for row in rows
    ]


@require_GET
@api_role_required('ADMIN')
def report_summary(request):
    result = reports.summary()
    return ok({key: (money(value) if isinstance(value, Decimal) else value) for key, value in result.items()})


@require_GET
@api_role_required('ADMIN')
def report_sales_per_seller(request):
    return ok(_decimal_rows(reports.sales_per_seller()))


@require_GET
@api_role_required('ADMIN')
def report_revenue(request):
    period = request.GET.get('period', 'month').lower()
    if period not in ('day', 'week', 'month', 'year'):
        return error_response('period must be day, week, month or year.', 'validation_error', 400)
    start = parse_date(request.GET.get('from', '')) if request.GET.get('from') else None
    end = parse_date(request.GET.get('to', '')) if request.GET.get('to') else None
    rows = reports.revenue_per_period(period, start=start, end=end)
    return ok(_decimal_rows(rows))


@require_GET
@api_role_required('ADMIN')
def report_best_sellers(request):
    try:
        limit = min(max(int(request.GET.get('limit', 10)), 1), 50)
    except ValueError:
        limit = 10
    return ok(_decimal_rows(reports.best_sellers(limit)))


@require_GET
@api_role_required('ADMIN')
def report_low_stock(request):
    return ok(_decimal_rows(reports.low_stock()))


@require_GET
@api_role_required('ADMIN')
def report_categories(request):
    return ok(_decimal_rows(reports.sales_per_category()))
