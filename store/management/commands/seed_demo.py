"""Seed the marketplace with a realistic demo dataset.

Usage::

    python manage.py seed_demo          # seed if empty
    python manage.py seed_demo --reset  # wipe marketplace data and reseed
    python manage.py seed_demo --force  # reseed without wiping users

Creates (at least): 7 categories, 9 sellers (8 approved), 30 products with
images, 20 customers, 40 orders, 70+ order items, 30 verified reviews,
payments, shipments, disputes, carts and status history.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
import random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from store.models import (
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
)


User = get_user_model()
RNG = random.Random(2026)

CATEGORIES = [
    ('Food & Groceries', 'food-groceries', '🥬', 'Fresh produce, pantry staples and local food.', '#3f7d4e'),
    ('Electronics & Tech', 'electronics-tech', '💻', 'Phones, audio, computing and accessories.', '#2f5f82'),
    ('Clothing & Shoes', 'clothing-shoes', '👗', 'Everyday fashion, fabrics and footwear.', '#8a4f63'),
    ('Home & Living', 'home-living', '🛋', 'Furniture, decor, kitchen and bedding.', '#8a6a3f'),
    ('Beauty & Fragrance', 'beauty-fragrance', '🧴', 'Skincare, haircare and fragrances.', '#7a557f'),
    ('Hardware & Tools', 'hardware-tools', '🔧', 'Building supplies, tools and garden equipment.', '#6a6250'),
    ('Toys & Leisure', 'toys-leisure', '🧸', 'Toys, games, books and outdoor fun.', '#b07a3c'),
]

SELLERS = [
    {
        'username': 'greenbasket',
        'store_name': 'Green Basket Kampala',
        'email': 'greenbasket@example.com',
        'description': 'Fresh food and pantry staples from Nakasero market growers.',
        'phone': '+256700100001',
        'address': 'Nakasero Market, Kampala',
        'categories': ['food-groceries'],
    },
    {
        'username': 'techhub',
        'store_name': 'TechHub Uganda',
        'email': 'techhub@example.com',
        'description': 'Trusted consumer electronics with a 12-month local warranty.',
        'phone': '+256700100002',
        'address': 'Kampala Road, Plot 24',
        'categories': ['electronics-tech'],
    },
    {
        'username': 'kitenge',
        'store_name': 'Kitenge & Co.',
        'email': 'kitenge@example.com',
        'description': 'Hand-printed kitenge fabrics and modern East African fashion.',
        'phone': '+256700100003',
        'address': 'Buganda Road Crafts Village',
        'categories': ['clothing-shoes'],
    },
    {
        'username': 'homecomfort',
        'store_name': 'Home Comfort Studio',
        'email': 'homecomfort@example.com',
        'description': 'Warm, practical homeware for Kampala apartments.',
        'phone': '+256700100004',
        'address': 'Kololo, Kampala',
        'categories': ['home-living'],
    },
    {
        'username': 'glow',
        'store_name': 'Glow Beauty Bar',
        'email': 'glow@example.com',
        'description': 'Dermatologist-friendly skincare and locally made fragrances.',
        'phone': '+256700100005',
        'address': 'Acacia Mall, Kampala',
        'categories': ['beauty-fragrance'],
    },
    {
        'username': 'buildright',
        'store_name': 'BuildRight Hardware',
        'email': 'buildright@example.com',
        'description': 'Contractor-grade tools, plumbing and electrical supplies.',
        'phone': '+256700100006',
        'address': 'Industrial Area, Kampala',
        'categories': ['hardware-tools'],
    },
    {
        'username': 'playtime',
        'store_name': 'PlayTime Toys',
        'email': 'playtime@example.com',
        'description': 'Educational toys, board games and outdoor play equipment.',
        'phone': '+256700100007',
        'address': 'Ntinda Shopping Centre',
        'categories': ['toys-leisure'],
    },
    {
        'username': 'omugga',
        'store_name': 'Omugga Fresh Foods',
        'email': 'omugga@example.com',
        'description': 'Farm-direct eggs, fruit and honey delivered across Kampala.',
        'phone': '+256700100008',
        'address': 'Wakiso, Greater Kampala',
        'categories': ['food-groceries', 'home-living'],
    },
]

PENDING_SELLER = {
    'username': 'kikuubo',
    'store_name': 'Kikuubo Textiles',
    'email': 'kikuubo@example.com',
    'description': 'Wholesale textiles awaiting marketplace approval.',
    'phone': '+256700100009',
    'address': 'Kikuubo Lane, Kampala',
}

CUSTOMERS = [
    ('Amina Nakato', 'amina@example.com', '+256700200001', '12 Market Road', 'Kampala'),
    ('Brian Okello', 'brian@example.com', '+256700200002', '45 Ntinda Road', 'Kampala'),
    ('Cynthia Namuli', 'cynthia@example.com', '+256700200003', '8 Kololo Hill', 'Kampala'),
    ('David Ssemanda', 'david@example.com', '+256700200004', '22 Bukoto Street', 'Kampala'),
    ('Esther Achieng', 'esther@example.com', '+256700200005', '31 Ggaba Road', 'Kampala'),
    ('Farouk Ssentongo', 'farouk@example.com', '+256700200006', '5 Entebbe Road', 'Entebbe'),
    ('Grace Atim', 'grace@example.com', '+256700200007', '19 Makerere Hill', 'Kampala'),
    ('Hassan Mubiru', 'hassan@example.com', '+256700200008', '77 Bwaise', 'Kampala'),
    ('Irene Nansubuga', 'irene@example.com', '+256700200009', '3 Muyenga', 'Kampala'),
    ('Joel Kato', 'joel@example.com', '+256700200010', '14 Kira Road', 'Kampala'),
    ('Khadija Nabirye', 'khadija@example.com', '+256700200011', '6 Nsambya', 'Kampala'),
    ('Lydia Auma', 'lydia@example.com', '+256700200012', '28 Bugolobi', 'Kampala'),
    ('Moses Kiggundu', 'moses@example.com', '+256700200013', '9 Najjanankumbi', 'Kampala'),
    ('Nancy Adong', 'nancy@example.com', '+256700200014', '41 Wandegeya', 'Kampala'),
    ('Oscar Byaruhanga', 'oscar@example.com', '+256700200015', '17 Kansanga', 'Kampala'),
    ('Patience Namusoke', 'patience@example.com', '+256700200016', '2 Nakawa', 'Kampala'),
    ('Quinton Lubega', 'quinton@example.com', '+256700200017', '55 Kawempe', 'Kampala'),
    ('Rita Nakimuli', 'rita@example.com', '+256700200018', '12 Rubaga', 'Kampala'),
    ('Samuel Ochieng', 'samuel@example.com', '+256700200019', '90 Nansana', 'Kampala'),
    ('Tracy Namayanja', 'tracy@example.com', '+256700200020', '4 Munyonyo', 'Kampala'),
]

PRODUCTS = [
    # (name, category slug, seller username, price, stock, description)
    ('Fresh Nakasero Tomatoes (1kg)', 'food-groceries', 'greenbasket', 4500, 60, 'Vine-ripened tomatoes picked the same morning from Nakasero growers.'),
    ('Matooke Bunch — Medium', 'food-groceries', 'greenbasket', 18000, 40, 'Sweet matooke bunch, ideal for a family meal.'),
    ('Ugandan Robusta Coffee Beans (500g)', 'food-groceries', 'omugga', 24000, 35, 'Medium roast robusta from Mount Elgon, ground to order.'),
    ('Wild Forest Honey (750ml)', 'food-groceries', 'omugga', 32000, 28, 'Raw, unheated honey harvested by cooperatives in Wakiso.'),
    ('Free-Range Eggs (Tray of 30)', 'food-groceries', 'omugga', 16000, 45, 'Farm-fresh eggs collected daily, packed in recycled trays.'),
    ('Redmi Note 13 — 128GB', 'electronics-tech', 'techhub', 720000, 12, 'Dual-SIM smartphone with a 108MP camera and 5,000mAh battery.'),
    ('Anker Soundcore Bluetooth Speaker', 'electronics-tech', 'techhub', 185000, 18, 'Portable waterproof speaker with 24-hour playback.'),
    ('HP 15 Laptop — Core i5, 16GB RAM', 'electronics-tech', 'techhub', 2450000, 6, 'Business laptop with SSD storage, warranty and Windows pre-installed.'),
    ('USB-C Fast Charger 65W', 'electronics-tech', 'techhub', 85000, 50, 'GaN charger that powers laptops, tablets and phones.'),
    ('Solar Power Bank 20,000mAh', 'electronics-tech', 'techhub', 145000, 22, 'Charge phones during load-shedding with a built-in solar panel.'),
    ('Kitenge Print Dress — Medium', 'clothing-shoes', 'kitenge', 95000, 15, 'Hand-tailored cotton dress with an adjustable waist tie.'),
    ('Ankara Fabric — 6 Yards', 'clothing-shoes', 'kitenge', 68000, 25, 'Colour-fast wax print fabric sold in a full six-yard piece.'),
    ('Leather Sandals — Size 42', 'clothing-shoes', 'kitenge', 82000, 10, 'Locally tanned leather sandals with a cushioned sole.'),
    ('Woven Market Tote', 'clothing-shoes', 'kitenge', 45000, 30, 'Sturdy raffia tote hand-woven by a women\'s cooperative.'),
    ('Cotton Bedding Set — Queen', 'home-living', 'homecomfort', 165000, 14, '400-thread-count cotton duvet cover with two pillowcases.'),
    ('Rattan Floor Lamp', 'home-living', 'homecomfort', 135000, 9, 'Warm ambient lamp with a hand-woven rattan shade.'),
    ('Ceramic Dinner Set — 16 Pieces', 'home-living', 'homecomfort', 210000, 7, 'Stoneware dinner set, dishwasher and microwave safe.'),
    ('Non-stick Cookware Set — 5 Pieces', 'home-living', 'homecomfort', 175000, 11, 'Induction-ready pots and pans with heat-resistant handles.'),
    ('Shea Butter Body Cream (250ml)', 'beauty-fragrance', 'glow', 28000, 40, 'Unrefined shea butter blended with vitamin E for dry skin.'),
    ('Hibiscus Face Serum (30ml)', 'beauty-fragrance', 'glow', 42000, 26, 'Lightweight serum with hibiscus extract and niacinamide.'),
    ('Vanilla & Amber Eau de Parfum', 'beauty-fragrance', 'glow', 120000, 16, 'Long-wearing local fragrance with warm vanilla and amber notes.'),
    ('Cordless Drill Kit — 18V', 'hardware-tools', 'buildright', 260000, 8, 'Two-battery cordless drill with 25-piece bit set and case.'),
    ('Heavy Duty Toolbox — 22"', 'hardware-tools', 'buildright', 98000, 13, 'Powder-coated steel toolbox with a lockable latch.'),
    ('Garden Hose Reel — 20m', 'hardware-tools', 'buildright', 120000, 9, 'UV-resistant hose with a wall-mounted winding reel.'),
    ('LED Security Floodlight 50W', 'hardware-tools', 'buildright', 75000, 20, 'Motion-sensor floodlight with a weatherproof housing.'),
    ('Wooden Building Blocks — 100 Pieces', 'toys-leisure', 'playtime', 55000, 24, 'Smooth, non-toxic wooden blocks in a cotton storage bag.'),
    ('Family Board Game Bundle', 'toys-leisure', 'playtime', 72000, 18, 'Three classic strategy games for family game nights.'),
    ('Kids Mountain Bike — 20"', 'toys-leisure', 'playtime', 420000, 5, 'Six-speed bike with a lightweight frame and safety brakes.'),
    ('Outdoor Picnic Blanket', 'toys-leisure', 'playtime', 48000, 21, 'Water-resistant padded blanket that folds into a carry strap.'),
    ('Gourmet Gift Hamper', 'food-groceries', 'greenbasket', 145000, 6, 'Coffee, honey, fruit and chocolate curated in a reusable basket.'),
]

REVIEW_COMMENTS = [
    'Exactly as described and delivered faster than expected.',
    'Great quality for the price — I will order again.',
    'The seller packed everything carefully. Very happy.',
    'Works perfectly and the instructions were clear.',
    'Lovely finish and the colour matches the photos.',
    'Good value, though delivery took a day longer than planned.',
    'My family loves it. Genuine local quality.',
    'Solid product. Customer support answered my question quickly.',
    'Would recommend to anyone shopping around Kampala.',
    'Better than the imported version I used before.',
]

STATUS_PLAN = (
    ['PENDING'] * 7
    + ['PAID'] * 12
    + ['SHIPPED'] * 8
    + ['DELIVERED'] * 10
    + ['CANCELLED'] * 3
)


class Command(BaseCommand):
    help = 'Seed categories, sellers, products, customers, orders, reviews and reports data.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete existing marketplace data first.')
        parser.add_argument('--force', action='store_true', help='Reseed even when products already exist.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self._wipe()
        elif Product.objects.exists() and not options['force']:
            self.stdout.write(self.style.WARNING('Data already present. Use --reset or --force to reseed.'))
            return

        admin = self._create_admin()
        categories = self._create_categories()
        sellers = self._create_sellers(categories)
        products = self._create_products(sellers, categories)
        customers = self._create_customers()
        orders = self._create_orders(products, customers)
        self._create_reviews(orders)
        self._create_disputes(orders, customers)
        self._create_carts(products, customers)

        self.stdout.write(self.style.SUCCESS(
            'Seed complete: '
            f'{Category.objects.count()} categories, '
            f'{SellerProfile.objects.count()} sellers, '
            f'{Product.objects.count()} products, '
            f'{User.objects.filter(role="CUSTOMER").count()} customers, '
            f'{Order.objects.count()} orders, '
            f'{OrderItem.objects.count()} order items, '
            f'{Review.objects.count()} reviews.'
        ))
        self.stdout.write(f'Admin: {admin.username} / Admin#2026')
        self.stdout.write('Customer: amina@example.com / Customer#2026')
        self.stdout.write('Seller: greenbasket@example.com / Seller#2026')

    # ------------------------------------------------------------------
    def _wipe(self):
        self.stdout.write('Wiping marketplace data...')
        Dispute.objects.all().delete()
        Shipment.objects.all().delete()
        OrderStatusEvent.objects.all().delete()
        Payment.objects.all().delete()
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Review.objects.all().delete()
        CartItem.objects.all().delete()
        Cart.objects.all().delete()
        ApiToken.objects.all().delete()
        ProductImage.objects.all().delete()
        Inventory.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        SellerProfile.objects.all().delete()
        CustomerProfile.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    def _create_admin(self):
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@rukomeza.test',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'Platform',
                'last_name': 'Admin',
            },
        )
        if created:
            admin.set_password('Admin#2026')
            admin.save()
        else:
            admin.role = 'ADMIN'
            admin.is_staff = True
            admin.is_superuser = True
            admin.save(update_fields=['role', 'is_staff', 'is_superuser'])
        return admin

    def _create_categories(self):
        categories = {}
        for name, slug, icon, description, color in CATEGORIES:
            category, _ = Category.objects.update_or_create(
                slug=slug,
                defaults={'name': name, 'icon': icon, 'description': description, 'is_active': True},
            )
            categories[slug] = category
            setattr(category, 'seed_color', color)
        return categories

    def _create_sellers(self, categories):
        sellers = {}
        for index, data in enumerate(SELLERS):
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'role': 'SELLER',
                    'first_name': data['store_name'].split()[0],
                    'last_name': 'Seller',
                    'phone_number': data['phone'],
                },
            )
            if created:
                user.set_password('Seller#2026')
                user.save()
            seller, _ = SellerProfile.objects.update_or_create(
                user=user,
                defaults={
                    'store_name': data['store_name'],
                    'store_description': data['description'],
                    'phone_number': data['phone'],
                    'address': data['address'],
                    'is_approved': True,
                    'is_suspended': False,
                    'approved_at': timezone.now() - timedelta(days=120 - index),
                },
            )
            sellers[data['username']] = seller

        pending_user, created = User.objects.get_or_create(
            username=PENDING_SELLER['username'],
            defaults={
                'email': PENDING_SELLER['email'],
                'role': 'SELLER',
                'phone_number': PENDING_SELLER['phone'],
            },
        )
        if created:
            pending_user.set_password('Seller#2026')
            pending_user.save()
        SellerProfile.objects.update_or_create(
            user=pending_user,
            defaults={
                'store_name': PENDING_SELLER['store_name'],
                'store_description': PENDING_SELLER['description'],
                'phone_number': PENDING_SELLER['phone'],
                'address': PENDING_SELLER['address'],
                'is_approved': False,
                'is_suspended': False,
            },
        )
        return sellers

    def _create_products(self, sellers, categories):
        products = []
        image_dir = Path(settings.BASE_DIR) / 'web' / 'images' / 'seed'
        image_dir.mkdir(parents=True, exist_ok=True)
        for index, (name, category_slug, seller_key, price, stock, description) in enumerate(PRODUCTS, start=1):
            category = categories[category_slug]
            product, _ = Product.objects.update_or_create(
                name=name,
                defaults={
                    'seller': sellers[seller_key],
                    'category': category,
                    'description': description,
                    'price': Decimal(price),
                    'low_stock_threshold': 5,
                    'is_active': True,
                },
            )
            Inventory.objects.update_or_create(product=product, defaults={'stock_quantity': stock})
            image_path = image_dir / f'product-{index:02d}.svg'
            if not image_path.exists():
                image_path.write_text(
                    self._svg(name, category.name, getattr(category, 'seed_color', '#245c46'), index),
                    encoding='utf-8',
                )
            ProductImage.objects.update_or_create(
                product=product,
                is_primary=True,
                defaults={
                    'external_url': f'/static/images/seed/product-{index:02d}.svg',
                    'alt_text': name,
                    'sort_order': 0,
                },
            )
            products.append(product)
        return products

    @staticmethod
    def _svg(name: str, category: str, color: str, index: int) -> str:
        initials = ''.join(word[0] for word in name.split()[:2]).upper()
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600" role="img" aria-label="{escape(name)}">
  <defs>
    <linearGradient id="g{index}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{color}" stop-opacity="0.92"/>
      <stop offset="100%" stop-color="#1d2925" stop-opacity="0.96"/>
    </linearGradient>
  </defs>
  <rect width="600" height="600" fill="url(#g{index})"/>
  <circle cx="500" cy="90" r="170" fill="#ffffff" fill-opacity="0.07"/>
  <circle cx="80" cy="540" r="210" fill="#ffffff" fill-opacity="0.05"/>
  <text x="52" y="88" fill="#d7ecb0" font-family="Arial, sans-serif" font-size="20" letter-spacing="4">{escape(category.upper())}</text>
  <text x="52" y="300" fill="#ffffff" font-family="Georgia, serif" font-size="150" font-weight="700">{escape(initials)}</text>
  <text x="52" y="370" fill="#f4f7ee" font-family="Arial, sans-serif" font-size="30">{escape(name[:36])}</text>
  <text x="52" y="540" fill="#d7ecb0" font-family="Arial, sans-serif" font-size="18" letter-spacing="3">RUKOMEZA MARKET</text>
</svg>
'''

    def _create_customers(self):
        customers = []
        for name, email, phone, address, city in CUSTOMERS:
            first, last = name.split(' ', 1)
            user, created = User.objects.get_or_create(
                username=email.split('@')[0],
                defaults={
                    'email': email,
                    'first_name': first,
                    'last_name': last,
                    'role': 'CUSTOMER',
                    'phone_number': phone,
                },
            )
            if created:
                user.set_password('Customer#2026')
                user.save()
            CustomerProfile.objects.update_or_create(
                user=user,
                defaults={'shipping_address': address, 'city': city, 'country': 'Uganda'},
            )
            customers.append(user)
        return customers

    def _create_orders(self, products, customers):
        now = timezone.now()
        original_stock = {product.pk: product.inventory.stock_quantity for product in products}
        # Start with a buffer so every planned order can be created, then write
        # back a realistic remaining stock.
        stock = {product.pk: original_stock[product.pk] + 500 for product in products}
        sold = {product.pk: 0 for product in products}
        statuses = list(STATUS_PLAN)
        RNG.shuffle(statuses)
        orders = []

        for index, status in enumerate(statuses):
            customer = customers[index % len(customers)]
            placed_at = now - timedelta(days=RNG.randint(1, 150), hours=RNG.randint(0, 20), minutes=RNG.randint(0, 59))
            line_count = RNG.choice([1, 2, 2, 2, 3])
            chosen = RNG.sample(products, line_count)
            items = []
            subtotal = Decimal('0.00')
            for product in chosen:
                quantity = RNG.choice([1, 1, 1, 2, 3])
                if stock[product.pk] < quantity:
                    continue
                stock[product.pk] -= quantity
                if status != 'CANCELLED':
                    sold[product.pk] += quantity
                line_total = product.price * quantity
                subtotal += line_total
                items.append((product, quantity))
            if not items:
                continue

            order = Order.objects.create(
                customer=customer,
                status=status,
                subtotal=subtotal,
                shipping_fee=Decimal('0.00'),
                total_amount=subtotal,
                shipping_full_name=customer.get_full_name() or customer.username,
                shipping_phone=customer.phone_number,
                shipping_address=getattr(customer, 'customer_profile', None).shipping_address if hasattr(customer, 'customer_profile') else 'Kampala',
                shipping_city=getattr(customer, 'customer_profile', None).city if hasattr(customer, 'customer_profile') else 'Kampala',
                created_at=placed_at,
            )
            Order.objects.filter(pk=order.pk).update(created_at=placed_at, updated_at=placed_at)

            for product, quantity in items:
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    seller=product.seller,
                    product_name_snapshot=product.name,
                    sku_snapshot=product.sku,
                    seller_name_snapshot=product.seller.store_name,
                    quantity=quantity,
                    unit_price_snapshot=product.price,
                )

            paid_at = placed_at + timedelta(minutes=RNG.randint(3, 45)) if status in ('PAID', 'SHIPPED', 'DELIVERED') else None
            if status == 'PENDING':
                payment_status = 'PENDING'
            elif status == 'CANCELLED':
                payment_status = 'FAILED'
            else:
                payment_status = 'PAID'
            payment = Payment.objects.create(
                order=order,
                gateway='MOCK',
                transaction_ref=f'PAY-SEED{index:04d}{RNG.randint(1000, 9999)}',
                provider_reference=f'MOCK-SEED-{index:04d}',
                amount=subtotal,
                status=payment_status,
                attempts=1 if payment_status != 'PENDING' else 0,
                paid_at=paid_at if payment_status == 'PAID' else None,
                failure_reason='Simulated card decline during seeding.' if payment_status == 'FAILED' else '',
                raw_response={'gateway': 'MOCK', 'seeded': True, 'test_mode': True},
                created_at=placed_at,
            )
            Payment.objects.filter(pk=payment.pk).update(created_at=placed_at, updated_at=placed_at)

            events = [('', 'PENDING', placed_at, 'Order placed by customer.')]
            if status in ('PAID', 'SHIPPED', 'DELIVERED'):
                events.append(('PENDING', 'PAID', paid_at, 'Mock gateway charge succeeded.'))
            if status in ('SHIPPED', 'DELIVERED'):
                shipped_at = paid_at + timedelta(hours=RNG.randint(6, 48))
                events.append(('PAID', 'SHIPPED', shipped_at, 'Handed to Rukomeza Express.'))
                Shipment.objects.create(
                    order=order,
                    courier='Rukomeza Express',
                    tracking_number=f'RMX-{index:04d}-{RNG.randint(100, 999)}',
                    status='DELIVERED' if status == 'DELIVERED' else 'DISPATCHED',
                    shipped_at=shipped_at,
                    delivered_at=shipped_at + timedelta(hours=RNG.randint(4, 30)) if status == 'DELIVERED' else None,
                )
            if status == 'DELIVERED':
                delivered_at = shipped_at + timedelta(hours=RNG.randint(4, 30))
                events.append(('SHIPPED', 'DELIVERED', delivered_at, 'Delivered and signed for.'))
            if status == 'CANCELLED':
                cancelled_at = placed_at + timedelta(hours=RNG.randint(2, 24))
                events.append(('PENDING', 'CANCELLED', cancelled_at, 'Cancelled before dispatch; stock restored.'))

            for from_status, to_status, happened_at, note in events:
                event = OrderStatusEvent.objects.create(
                    order=order,
                    from_status=from_status,
                    to_status=to_status,
                    note=note,
                    changed_by=order.customer,
                )
                OrderStatusEvent.objects.filter(pk=event.pk).update(created_at=happened_at)
            order.refresh_from_db()
            orders.append(order)

        # Persist a realistic remaining stock (original minus sold, never
        # negative) and force a few low-stock alerts for the dashboard.
        for product in products:
            remaining = max(0, original_stock[product.pk] - sold[product.pk])
            Inventory.objects.filter(product=product).update(stock_quantity=remaining)
        for product in products[:6]:
            Inventory.objects.filter(product=product).update(stock_quantity=RNG.randint(1, 4))
        return orders

    def _create_reviews(self, orders):
        candidates = {}
        for order in orders:
            if order.status not in ('PAID', 'SHIPPED', 'DELIVERED'):
                continue
            for item in order.items.select_related('product'):
                if item.product_id:
                    candidates.setdefault(item.product_id, []).append((order.customer, item))
        pairs = []
        for product_id, entries in candidates.items():
            RNG.shuffle(entries)
            for customer, item in entries[:2]:
                if all(customer.pk != existing[0].pk or product_id != existing[1] for existing in pairs):
                    pairs.append((customer, product_id, item))
        RNG.shuffle(pairs)
        for customer, product_id, item in pairs[:30]:
            Review.objects.get_or_create(
                customer=customer,
                product_id=product_id,
                defaults={
                    'order_item': item,
                    'rating': RNG.choices([3, 4, 5, 5], weights=[1, 3, 4, 2])[0],
                    'comment': RNG.choice(REVIEW_COMMENTS),
                    'is_verified_purchase': True,
                },
            )

    def _create_disputes(self, orders, customers):
        eligible = [order for order in orders if order.status in ('PAID', 'SHIPPED', 'DELIVERED')][:3]
        reasons = ['DAMAGED', 'NOT_RECEIVED', 'WRONG_ITEM']
        for order, reason in zip(eligible, reasons):
            Dispute.objects.get_or_create(
                order=order,
                defaults={
                    'raised_by': order.customer,
                    'reason': reason,
                    'description': 'Ordered item did not match the listing; please review the order and advise.',
                    'status': 'OPEN',
                },
            )

    def _create_carts(self, products, customers):
        available = [product for product in products if getattr(product, 'inventory', None) and product.inventory.stock_quantity >= 1]
        for customer in customers[:5]:
            cart, _ = Cart.objects.get_or_create(user=customer)
            for product in RNG.sample(available, min(RNG.randint(1, 3), len(available))):
                max_quantity = min(2, product.inventory.stock_quantity)
                CartItem.objects.get_or_create(
                    cart=cart,
                    product=product,
                    defaults={'quantity': RNG.randint(1, max_quantity)},
                )
