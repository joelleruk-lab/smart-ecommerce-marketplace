from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

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
    ProductImage,
    Review,
    SellerProfile,
    Shipment,
    User,
)


class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0
    min_num = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(User)
class MarketplaceUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Marketplace profile', {'fields': ('role', 'phone_number', 'profile_picture', 'is_blocked')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Marketplace profile', {'fields': ('email', 'role', 'phone_number')}),
    )
    list_display = ('username', 'email', 'role', 'is_active', 'is_blocked', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_active', 'is_blocked')
    search_fields = ('username', 'email', 'phone_number')


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'country')
    search_fields = ('user__username', 'user__email')


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ('store_name', 'user', 'is_approved', 'is_suspended', 'approved_at', 'created_at')
    list_filter = ('is_approved', 'is_suspended')
    search_fields = ('store_name', 'user__username', 'user__email')
    prepopulated_fields = {'slug': ('store_name',)}
    actions = ('approve_sellers', 'suspend_sellers')

    @admin.action(description='Approve selected sellers')
    def approve_sellers(self, request, queryset):
        for seller in queryset:
            seller.is_approved = True
            seller.is_suspended = False
            seller.save()
        messages.success(request, f'{queryset.count()} seller(s) approved.')

    @admin.action(description='Suspend selected sellers')
    def suspend_sellers(self, request, queryset):
        updated = queryset.update(is_suspended=True)
        messages.warning(request, f'{updated} seller(s) suspended.')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'is_active', 'product_count')
    list_filter = ('is_active',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Products')
    def product_count(self, category):
        return category.products.count()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'seller', 'category', 'price', 'stock', 'is_active', 'created_at')
    list_filter = ('is_active', 'category', 'seller')
    search_fields = ('name', 'description', 'sku', 'seller__store_name')
    readonly_fields = ('sku', 'created_at', 'updated_at')
    inlines = (InventoryInline, ProductImageInline)

    @admin.display(description='Stock')
    def stock(self, product):
        inventory = getattr(product, 'inventory', None)
        return inventory.stock_quantity if inventory else 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('reference', 'customer', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reference', 'customer__username', 'customer__email')
    readonly_fields = (
        'reference', 'customer', 'status', 'subtotal', 'shipping_fee', 'total_amount',
        'paid_at', 'shipped_at', 'delivered_at', 'cancelled_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'seller', 'product_name_snapshot', 'sku_snapshot', 'seller_name_snapshot', 'quantity', 'unit_price_snapshot')
    can_delete = False


OrderAdmin.inlines = (OrderItemInline,)


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ('order', 'from_status', 'to_status', 'changed_by', 'created_at')
    list_filter = ('to_status',)
    readonly_fields = ('order', 'from_status', 'to_status', 'note', 'changed_by', 'created_at')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_ref', 'order', 'gateway', 'amount', 'status', 'attempts', 'paid_at')
    list_filter = ('status', 'gateway')
    search_fields = ('transaction_ref', 'order__reference')
    readonly_fields = ('order', 'transaction_ref', 'provider_reference', 'amount', 'currency', 'status', 'attempts', 'failure_reason', 'raw_response', 'paid_at', 'created_at')


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('order', 'courier', 'tracking_number', 'status', 'shipped_at', 'delivered_at')
    list_filter = ('status',)
    search_fields = ('order__reference', 'tracking_number')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'customer', 'rating', 'is_verified_purchase', 'created_at')
    list_filter = ('rating', 'is_verified_purchase')
    search_fields = ('product__name', 'customer__username', 'comment')


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('order', 'raised_by', 'reason', 'status', 'created_at', 'resolved_at')
    list_filter = ('status', 'reason')
    search_fields = ('order__reference', 'raised_by__username', 'description')


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'session_key', 'created_at')
    search_fields = ('user__username',)


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'product', 'quantity')
    search_fields = ('product__name',)


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'stock_quantity', 'updated_at')
    search_fields = ('product__name', 'product__sku')
    list_filter = ('stock_quantity',)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'label', 'created_at', 'last_used_at', 'revoked')
    list_filter = ('revoked',)
    search_fields = ('user__username', 'token_hash')
    readonly_fields = ('user', 'token_hash', 'created_at', 'last_used_at')
