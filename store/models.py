"""Database model for the Rukomeza Market multi-vendor marketplace.

The schema is normalised to third normal form (3NF). Every table stores only
facts about its own entity; derived values (line totals, average ratings,
order totals at reporting time) are computed rather than duplicated, except
for the deliberately denormalised *snapshot* columns on ``OrderItem`` that
preserve the price and product identity at the moment of purchase.

Integrity is enforced at three levels:

* ``CheckConstraint`` / ``UniqueConstraint`` in the database,
* ``clean()`` validation in the model layer,
* service-layer transactions (see ``store/services``).
"""

from decimal import Decimal
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2

ORDER_STATUS_PENDING = 'PENDING'
ORDER_STATUS_PAID = 'PAID'
ORDER_STATUS_SHIPPED = 'SHIPPED'
ORDER_STATUS_DELIVERED = 'DELIVERED'
ORDER_STATUS_CANCELLED = 'CANCELLED'

ORDER_STATUSES = (
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_CANCELLED,
)

#: The only order-status transitions the platform accepts.  Delivered and
#: cancelled orders are terminal states.
ORDER_STATUS_TRANSITIONS = {
    ORDER_STATUS_PENDING: (ORDER_STATUS_PAID, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_PAID: (ORDER_STATUS_SHIPPED, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_SHIPPED: (ORDER_STATUS_DELIVERED,),
    ORDER_STATUS_DELIVERED: (),
    ORDER_STATUS_CANCELLED: (),
}

PAYMENT_STATUSES = (
    ('PENDING', 'Pending'),
    ('PAID', 'Paid'),
    ('FAILED', 'Failed'),
    ('CANCELLED', 'Cancelled'),
    ('REFUNDED', 'Refunded'),
)

SELLER_STATUS = (
    ('PENDING', 'Pending review'),
    ('APPROVED', 'Approved'),
    ('SUSPENDED', 'Suspended'),
)


def generate_order_reference():
    """Human-readable, collision-resistant order reference."""
    return 'RM-' + uuid.uuid4().hex[:10].upper()


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class User(AbstractUser):
    """Single authentication table for all actors (customers/sellers/admins).

    Roles are stored once here and *not* duplicated on ``CustomerProfile`` or
    ``SellerProfile``; those tables hold only role-specific attributes.  This
    keeps the schema in 3NF and avoids the update anomaly of a role stored in
    more than one place.
    """

    ROLE_CUSTOMER = 'CUSTOMER'
    ROLE_SELLER = 'SELLER'
    ROLE_ADMIN = 'ADMIN'
    ROLE_CHOICES = (
        (ROLE_CUSTOMER, 'Customer'),
        (ROLE_SELLER, 'Seller'),
        (ROLE_ADMIN, 'Administrator'),
    )

    email = models.EmailField('email address', unique=True, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    phone_number = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    is_blocked = models.BooleanField(
        default=False,
        help_text='Blocked accounts cannot sign in or place orders.',
    )

    REQUIRED_FIELDS = ['email']

    class Meta:
        ordering = ('username',)

    def save(self, *args, **kwargs):
        # NULL (not '') lets several users exist without an email while the
        # column stays unique for real addresses.
        if not self.email:
            self.email = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    @property
    def is_customer(self):
        return self.role == self.ROLE_CUSTOMER

    @property
    def is_seller(self):
        return self.role == self.ROLE_SELLER

    @property
    def is_platform_admin(self):
        return self.role == self.ROLE_ADMIN or self.is_staff or self.is_superuser

    @property
    def display_name(self):
        return self.get_full_name() or self.username


class CustomerProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    shipping_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, default='Kampala')
    country = models.CharField(max_length=100, default='Uganda')

    def __str__(self):
        return f'Customer profile: {self.user.username}'


class SellerProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seller_profile')
    store_name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    store_description = models.TextField(blank=True)
    store_logo = models.ImageField(upload_to='store_logos/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_approved = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    approved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('store_name',)

    def __str__(self):
        return self.store_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.store_name)[:120] or 'store'
            slug = base
            counter = 2
            while SellerProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{counter}'
                counter += 1
            self.slug = slug
        if self.is_approved and self.approved_at is None:
            self.approved_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def status(self):
        if self.is_suspended:
            return 'SUSPENDED'
        if self.is_approved:
            return 'APPROVED'
        return 'PENDING'

    @property
    def is_open_for_business(self):
        return self.is_approved and not self.is_suspended


class Category(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    icon = models.CharField(max_length=16, blank=True, help_text='Emoji/icon shown in the storefront.')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Product(TimeStampedModel):
    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    sku = models.CharField(max_length=32, unique=True, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField()
    price = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ('-created_at', 'name')
        indexes = [
            models.Index(fields=['category', 'price'], name='product_cat_price_idx'),
            models.Index(fields=['price'], name='product_price_idx'),
            models.Index(fields=['seller', 'is_active'], name='product_seller_active_idx'),
            models.Index(fields=['name'], name='product_name_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name='product_price_positive'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('product_detail', args=[self.pk])

    @property
    def primary_image(self):
        image = self.images.filter(is_primary=True).first() or self.images.first()
        if image is None and self.image:
            return None
        return image

    @property
    def display_image_url(self):
        primary = self.primary_image
        if primary and primary.external_url:
            return primary.external_url
        if primary and primary.image:
            return primary.image.url
        if self.image:
            return self.image.url
        return ''

    @property
    def average_rating(self):
        value = self.reviews.aggregate(models.Avg('rating'))['rating__avg']
        return round(value, 1) if value else None

    @property
    def review_count(self):
        return self.reviews.count()

    def clean(self):
        if self.category_id and not self.category.is_active:
            raise ValidationError({'category': 'The selected category is inactive.'})


class ProductImage(TimeStampedModel):
    """One row per product image (repeating group removed => 1NF)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    external_url = models.URLField(blank=True, help_text='CDN/object-storage URL (e.g. Cloudinary, R2).')
    alt_text = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['product'],
                condition=Q(is_primary=True),
                name='one_primary_image_per_product',
            ),
            models.CheckConstraint(
                condition=Q(image__isnull=False) | ~Q(external_url=''),
                name='product_image_has_source',
            ),
        ]

    def __str__(self):
        return f'Image for {self.product.name}'


class Inventory(TimeStampedModel):
    """Current stock for a product.  Kept separate because stock changes far
    more often than the catalogue row and is the row we lock during checkout.
    """

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory')
    stock_quantity = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Units physically available. Never negative.',
    )

    class Meta:
        verbose_name_plural = 'inventory'
        constraints = [
            models.CheckConstraint(condition=Q(stock_quantity__gte=0), name='inventory_stock_non_negative'),
        ]
        indexes = [models.Index(fields=['stock_quantity'], name='inventory_stock_idx')]

    def __str__(self):
        return f'{self.product.name}: {self.stock_quantity}'

    @property
    def is_low(self):
        return self.stock_quantity <= self.product.low_stock_threshold


class Cart(TimeStampedModel):
    """A cart belongs either to a registered user or to an anonymous session."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart',
        blank=True,
        null=True,
    )
    session_key = models.CharField(max_length=64, unique=True, blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False) | Q(session_key__isnull=False),
                name='cart_has_owner',
            ),
        ]

    def __str__(self):
        return f'Cart #{self.pk}'

    @property
    def item_count(self):
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), Decimal('0.00'))


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cart', 'product'], name='unique_cart_product'),
            models.CheckConstraint(
                condition=Q(quantity__gte=1) & Q(quantity__lte=99),
                name='cart_item_quantity_between_1_and_99',
            ),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product.name}'

    @property
    def line_total(self):
        return self.product.price * self.quantity


class Order(TimeStampedModel):
    reference = models.CharField(max_length=20, unique=True, default=generate_order_reference, editable=False)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(max_length=20, choices=(
        (ORDER_STATUS_PENDING, 'Pending'),
        (ORDER_STATUS_PAID, 'Paid'),
        (ORDER_STATUS_SHIPPED, 'Shipped'),
        (ORDER_STATUS_DELIVERED, 'Delivered'),
        (ORDER_STATUS_CANCELLED, 'Cancelled'),
    ), default=ORDER_STATUS_PENDING, db_index=True)
    subtotal = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=Decimal('0.00'))
    shipping_fee = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=Decimal('0.00'))
    shipping_full_name = models.CharField(max_length=150, blank=True)
    shipping_phone = models.CharField(max_length=20, blank=True)
    shipping_address = models.TextField(blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    shipped_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=['customer', 'status', '-created_at'], name='order_customer_status_idx'),
            models.Index(fields=['status', '-created_at'], name='order_status_created_idx'),
            models.Index(fields=['-created_at'], name='order_created_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=ORDER_STATUSES),
                name='order_status_valid',
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0) & Q(subtotal__gte=0) & Q(shipping_fee__gte=0),
                name='order_amounts_non_negative',
            ),
        ]

    def __str__(self):
        return f'Order {self.reference}'

    def get_absolute_url(self):
        return reverse('order_detail', args=[self.pk])

    @property
    def can_be_cancelled(self):
        return self.status in (ORDER_STATUS_PENDING, ORDER_STATUS_PAID)

    @property
    def is_paid(self):
        return self.status in (ORDER_STATUS_PAID, ORDER_STATUS_SHIPPED, ORDER_STATUS_DELIVERED)

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    def allowed_next_statuses(self):
        return ORDER_STATUS_TRANSITIONS.get(self.status, ())

    def clean(self):
        if self.status not in ORDER_STATUSES:
            raise ValidationError({'status': 'Unknown order status.'})
        if self.total_amount < self.subtotal + self.shipping_fee:
            raise ValidationError({'total_amount': 'Total must cover subtotal and shipping.'})

    def transition_to(self, new_status, *, changed_by=None, note=''):
        """Validate and persist a lifecycle transition.

        Callers should use ``store.services.orders.transition_order`` which also
        performs side effects (stock restoration, timestamps) inside a
        transaction.
        """
        if new_status not in ORDER_STATUS_TRANSITIONS.get(self.status, ()):
            raise ValidationError(
                f'Invalid order transition: {self.status} -> {new_status}.'
            )
        previous = self.status
        self.status = new_status
        now = timezone.now()
        if new_status == ORDER_STATUS_PAID:
            self.paid_at = now
        elif new_status == ORDER_STATUS_SHIPPED:
            self.shipped_at = now
        elif new_status == ORDER_STATUS_DELIVERED:
            self.delivered_at = now
        elif new_status == ORDER_STATUS_CANCELLED:
            self.cancelled_at = now
        self.save(update_fields=['status', 'paid_at', 'shipped_at', 'delivered_at', 'cancelled_at', 'updated_at'])
        OrderStatusEvent.objects.create(
            order=self,
            from_status=previous,
            to_status=new_status,
            note=note,
            changed_by=changed_by,
        )
        return self


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_events')
    from_status = models.CharField(max_length=20, choices=Order._meta.get_field('status').choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Order._meta.get_field('status').choices)
    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='order_status_changes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'pk')
        indexes = [models.Index(fields=['order', 'created_at'], name='status_event_order_idx')]

    def __str__(self):
        return f'{self.order.reference}: {self.from_status} -> {self.to_status}'


class OrderItem(models.Model):
    """A purchased line.

    ``unit_price_snapshot`` and the name/SKU snapshots are intentionally
    denormalised: they are *historical facts* about the purchase, not copies of
    current product data.  Editing the product later must not rewrite the past.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, blank=True, null=True, related_name='order_items')
    seller = models.ForeignKey(SellerProfile, on_delete=models.SET_NULL, blank=True, null=True, related_name='order_items')
    product_name_snapshot = models.CharField(max_length=200)
    sku_snapshot = models.CharField(max_length=32, blank=True)
    seller_name_snapshot = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price_snapshot = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)

    class Meta:
        ordering = ('pk',)
        indexes = [
            models.Index(fields=['order'], name='order_item_order_idx'),
            models.Index(fields=['product'], name='order_item_product_idx'),
            models.Index(fields=['seller'], name='order_item_seller_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['order', 'product'], name='unique_order_product'),
            models.CheckConstraint(condition=Q(quantity__gt=0), name='order_item_quantity_positive'),
            models.CheckConstraint(condition=Q(unit_price_snapshot__gte=0), name='order_item_price_non_negative'),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product_name_snapshot}'

    @property
    def line_total(self):
        return self.unit_price_snapshot * self.quantity


class Payment(TimeStampedModel):
    class Gateway(models.TextChoices):
        MOCK = 'MOCK', 'Mock gateway (test mode)'
        STRIPE = 'STRIPE', 'Stripe (test mode)'
        PAYSTACK = 'PAYSTACK', 'Paystack (test mode)'
        FLUTTERWAVE = 'FLUTTERWAVE', 'Flutterwave (test mode)'

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    gateway = models.CharField(max_length=20, choices=Gateway.choices, default=Gateway.MOCK)
    transaction_ref = models.CharField(max_length=64, unique=True)
    provider_reference = models.CharField(max_length=128, blank=True)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    currency = models.CharField(max_length=8, default='UGX')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUSES, default='PENDING', db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    failure_reason = models.CharField(max_length=255, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name='payment_amount_non_negative'),
        ]

    def __str__(self):
        return f'{self.transaction_ref} ({self.status})'

    @property
    def is_successful(self):
        return self.status == 'PAID'


class Shipment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Preparing'
        DISPATCHED = 'DISPATCHED', 'Dispatched'
        IN_TRANSIT = 'IN_TRANSIT', 'In transit'
        DELIVERED = 'DELIVERED', 'Delivered'
        FAILED = 'FAILED', 'Failed'

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='shipment')
    courier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    shipped_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f'Shipment for {self.order.reference} ({self.status})'


class Review(TimeStampedModel):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='reviews',
        help_text='The purchased line that proves this is a verified review.',
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    is_verified_purchase = models.BooleanField(default=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=['customer', 'product'], name='one_review_per_customer_product'),
            models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name='review_rating_1_to_5'),
        ]
        indexes = [models.Index(fields=['product', '-created_at'], name='review_product_idx')]

    def __str__(self):
        return f'{self.customer.username} on {self.product.name}: {self.rating}/5'

    def clean(self):
        if self.customer_id and not self.customer.is_customer:
            raise ValidationError('Only customer accounts can review products.')


class Dispute(TimeStampedModel):
    class Reason(models.TextChoices):
        NOT_RECEIVED = 'NOT_RECEIVED', 'Item not received'
        DAMAGED = 'DAMAGED', 'Item damaged'
        WRONG_ITEM = 'WRONG_ITEM', 'Wrong item delivered'
        REFUND = 'REFUND', 'Refund requested'
        OTHER = 'OTHER', 'Other'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under review'
        RESOLVED = 'RESOLVED', 'Resolved'
        REJECTED = 'REJECTED', 'Rejected'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='disputes')
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='disputes')
    reason = models.CharField(max_length=20, choices=Reason.choices)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='resolved_disputes',
    )
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=['order'],
                condition=Q(status__in=('OPEN', 'UNDER_REVIEW')),
                name='one_open_dispute_per_order',
            ),
        ]

    def __str__(self):
        return f'Dispute on {self.order.reference} ({self.status})'


class ApiToken(models.Model):
    """Opaque bearer token for the JSON API.

    Only the SHA-256 hash is persisted, so a database leak does not expose
    usable API credentials.  Tokens can be revoked per device.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    revoked = models.BooleanField(default=False)

    def __str__(self):
        return f'API token for {self.user.username}'
