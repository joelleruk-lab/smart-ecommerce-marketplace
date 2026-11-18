"""Generate docs/erd.png (logical ERD) from the marketplace schema.

Uses Pillow only, so it works without Graphviz. Run with:

    python scripts/generate_erd.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'erd.png'

W, H = 2600, 1950
MARGIN = 60
BOX_W = 460
HEADER_H = 52
ROW_H = 34
GAP = 34
COL_X = [MARGIN + index * (BOX_W + GAP) for index in range(5)]
ROW_Y = [220, 660, 1090, 1500]

GREEN = (36, 92, 70)
GREEN_DARK = (22, 61, 48)
INK = (29, 41, 37)
MUTED = (117, 129, 123)
LINE = (218, 221, 210)
PAPER = (251, 250, 246)
WHITE = (255, 255, 255)
LIME = (215, 236, 176)
AMBER = (194, 138, 50)
BLUE = (47, 95, 130)


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


REG = font(r'C:\Windows\Fonts\arial.ttf', 18)
SMALL = font(r'C:\Windows\Fonts\arial.ttf', 16)
BOLD = font(r'C:\Windows\Fonts\arialbd.ttf', 22)
HEAD = font(r'C:\Windows\Fonts\georgiab.ttf', 24)
TITLE = font(r'C:\Windows\Fonts\georgiab.ttf', 52)
SUB = font(r'C:\Windows\Fonts\arial.ttf', 22)
BADGE = font(r'C:\Windows\Fonts\arialbd.ttf', 13)


ENTITIES = {
    'users': {
        'title': 'users',
        'pos': (0, 0),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('username', 'VARCHAR(150)', 'UQ'),
            ('email', 'VARCHAR(254)', 'UQ'),
            ('password', 'VARCHAR(128)', ''),
            ('role', 'VARCHAR(20)', ''),
            ('phone_number', 'VARCHAR(20)', ''),
            ('is_blocked', 'BOOLEAN', ''),
            ('date_joined', 'TIMESTAMP', ''),
        ],
    },
    'customer_profiles': {
        'title': 'customer_profiles',
        'pos': (1, 0),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('user_id', 'BIGINT -> users', 'FK UQ'),
            ('shipping_address', 'TEXT', ''),
            ('city', 'VARCHAR(100)', ''),
            ('country', 'VARCHAR(100)', ''),
        ],
    },
    'seller_profiles': {
        'title': 'seller_profiles',
        'pos': (2, 0),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('user_id', 'BIGINT -> users', 'FK UQ'),
            ('store_name', 'VARCHAR(120)', 'UQ'),
            ('slug', 'SLUG', 'UQ'),
            ('is_approved', 'BOOLEAN', ''),
            ('is_suspended', 'BOOLEAN', ''),
            ('approved_at', 'TIMESTAMP', ''),
        ],
    },
    'api_tokens': {
        'title': 'api_tokens',
        'pos': (3, 0),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('user_id', 'BIGINT -> users', 'FK'),
            ('token_hash', 'CHAR(64)', 'UQ'),
            ('revoked', 'BOOLEAN', ''),
            ('last_used_at', 'TIMESTAMP', ''),
            ('created_at', 'TIMESTAMP', ''),
        ],
    },
    'categories': {
        'title': 'categories',
        'pos': (4, 0),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('name', 'VARCHAR(100)', 'UQ'),
            ('slug', 'SLUG', 'UQ'),
            ('icon', 'VARCHAR(16)', ''),
            ('is_active', 'BOOLEAN', ''),
        ],
    },
    'carts': {
        'title': 'carts',
        'pos': (0, 1),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('user_id', 'BIGINT -> users', 'FK UQ'),
            ('session_key', 'VARCHAR(64)', 'UQ'),
            ('created_at', 'TIMESTAMP', ''),
            ('CHECK', 'user OR session', 'CHK'),
        ],
    },
    'cart_items': {
        'title': 'cart_items',
        'pos': (1, 1),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('cart_id', 'BIGINT -> carts', 'FK'),
            ('product_id', 'BIGINT -> products', 'FK'),
            ('quantity', 'INT 1..99', 'CHK'),
            ('UNIQUE', 'cart + product', 'UQ'),
        ],
    },
    'products': {
        'title': 'products',
        'pos': (2, 1),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('seller_id', 'BIGINT -> sellers', 'FK'),
            ('category_id', 'BIGINT -> categories', 'FK'),
            ('sku', 'VARCHAR(32)', 'UQ'),
            ('name', 'VARCHAR(200)', 'IDX'),
            ('description', 'TEXT', ''),
            ('price', 'DECIMAL(12,2)', 'CHK > 0'),
            ('is_active', 'BOOLEAN', ''),
        ],
    },
    'product_images': {
        'title': 'product_images',
        'pos': (3, 1),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('product_id', 'BIGINT -> products', 'FK'),
            ('image', 'FILE / URL', ''),
            ('external_url', 'VARCHAR(200)', ''),
            ('is_primary', 'BOOLEAN', 'UQ*'),
        ],
    },
    'inventory': {
        'title': 'inventory',
        'pos': (4, 1),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('product_id', 'BIGINT -> products', 'FK UQ'),
            ('stock_quantity', 'INT ≥ 0', 'CHK'),
            ('updated_at', 'TIMESTAMP', ''),
        ],
    },
    'orders': {
        'title': 'orders',
        'pos': (1, 2),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('reference', 'VARCHAR(20)', 'UQ'),
            ('customer_id', 'BIGINT -> users', 'FK'),
            ('status', 'ENUM(5 states)', 'CHK'),
            ('subtotal', 'DECIMAL(12,2)', ''),
            ('shipping_fee', 'DECIMAL(12,2)', ''),
            ('total_amount', 'DECIMAL(12,2)', 'CHK ≥ 0'),
            ('shipping snapshot', 'TEXT', ''),
            ('paid_at / shipped_at', 'TIMESTAMP', ''),
        ],
    },
    'order_items': {
        'title': 'order_items',
        'pos': (2, 2),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('order_id', 'BIGINT -> orders', 'FK'),
            ('product_id', 'BIGINT -> products', 'FK'),
            ('seller_id', 'BIGINT -> sellers', 'FK'),
            ('product_name_snapshot', 'VARCHAR(200)', 'SNAP'),
            ('sku_snapshot', 'VARCHAR(32)', 'SNAP'),
            ('unit_price_snapshot', 'DECIMAL(12,2)', 'SNAP'),
            ('quantity', 'INT > 0', 'CHK'),
            ('UNIQUE', 'order + product', 'UQ'),
        ],
    },
    'payments': {
        'title': 'payments',
        'pos': (3, 2),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('order_id', 'BIGINT -> orders', 'FK UQ'),
            ('transaction_ref', 'VARCHAR(64)', 'UQ'),
            ('gateway', 'ENUM', ''),
            ('amount', 'DECIMAL(12,2)', 'CHK ≥ 0'),
            ('status', 'ENUM(pending/paid/...)', ''),
            ('attempts', 'INT', ''),
            ('paid_at', 'TIMESTAMP', ''),
        ],
    },
    'shipments': {
        'title': 'shipments',
        'pos': (4, 2),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('order_id', 'BIGINT -> orders', 'FK UQ'),
            ('courier', 'VARCHAR(120)', ''),
            ('tracking_number', 'VARCHAR(120)', ''),
            ('status', 'ENUM', ''),
            ('shipped_at', 'TIMESTAMP', ''),
            ('delivered_at', 'TIMESTAMP', ''),
        ],
    },
    'reviews': {
        'title': 'reviews',
        'pos': (1, 3),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('customer_id', 'BIGINT -> users', 'FK'),
            ('product_id', 'BIGINT -> products', 'FK'),
            ('order_item_id', 'BIGINT -> order_items', 'FK'),
            ('rating', 'INT 1..5', 'CHK'),
            ('comment', 'TEXT', ''),
            ('is_verified_purchase', 'BOOLEAN', ''),
            ('UNIQUE', 'customer + product', 'UQ'),
        ],
    },
    'order_status_events': {
        'title': 'order_status_events',
        'pos': (2, 3),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('order_id', 'BIGINT -> orders', 'FK'),
            ('from_status', 'ENUM / blank', ''),
            ('to_status', 'ENUM', ''),
            ('note', 'VARCHAR(255)', ''),
            ('changed_by', 'BIGINT -> users', 'FK'),
            ('created_at', 'TIMESTAMP', 'IDX'),
        ],
    },
    'disputes': {
        'title': 'disputes',
        'pos': (3, 3),
        'fields': [
            ('id', 'BIGINT', 'PK'),
            ('order_id', 'BIGINT -> orders', 'FK'),
            ('raised_by', 'BIGINT -> users', 'FK'),
            ('reason', 'ENUM', ''),
            ('status', 'ENUM', ''),
            ('resolution_note', 'TEXT', ''),
            ('resolved_by', 'BIGINT -> users', 'FK'),
        ],
    },
}

RELATIONS = [
    ('users', 'customer_profiles', '1:1'),
    ('users', 'seller_profiles', '1:1'),
    ('users', 'api_tokens', '1:N'),
    ('users', 'carts', '1:1'),
    ('users', 'orders', '1:N'),
    ('users', 'reviews', '1:N'),
    ('users', 'disputes', '1:N'),
    ('seller_profiles', 'products', '1:N'),
    ('categories', 'products', '1:N'),
    ('carts', 'cart_items', '1:N'),
    ('products', 'cart_items', '1:N'),
    ('products', 'product_images', '1:N'),
    ('products', 'inventory', '1:1'),
    ('orders', 'order_items', '1:N'),
    ('orders', 'payments', '1:1'),
    ('orders', 'shipments', '1:1'),
    ('orders', 'order_status_events', '1:N'),
    ('orders', 'disputes', '1:N'),
    ('products', 'order_items', '1:N'),
    ('order_items', 'reviews', '1:N'),
]


def box_geometry(entity):
    col, row = entity['pos']
    x = COL_X[col]
    y = ROW_Y[row]
    height = HEADER_H + ROW_H * len(entity['fields']) + 12
    return x, y, x + BOX_W, y + height


def anchor(box_a, box_b):
    """Pick facing edge midpoints based on relative position."""
    ax1, ay1, ax2, ay2 = box_geometry(box_a)
    bx1, by1, bx2, by2 = box_geometry(box_b)
    acx, acy = (ax1 + ax2) / 2, (ay1 + ay2) / 2
    bcx, bcy = (bx1 + bx2) / 2, (by1 + by2) / 2
    dx, dy = bcx - acx, bcy - acy
    if abs(dx) >= abs(dy):
        if dx >= 0:
            return (ax2, acy), (bx1, bcy), 'h'
        return (ax1, acy), (bx2, bcy), 'h'
    if dy >= 0:
        return (acx, ay2), (bcx, by1), 'v'
    return (acx, ay1), (bcx, by2), 'v'


def rounded_box(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def main():
    image = Image.new('RGB', (W, H), PAPER)
    draw = ImageDraw.Draw(image)

    draw.text((MARGIN, 55), 'Rukomeza Market - Entity Relationship Diagram', font=TITLE, fill=GREEN_DARK)
    draw.text(
        (MARGIN, 128),
        'Logical schema normalised to 3NF - 17 tables - PK/FK/unique/check constraints - immutable price snapshots on order_items',
        font=SUB,
        fill=MUTED,
    )
    draw.line([(MARGIN, 180), (W - MARGIN, 180)], fill=LINE, width=2)

    # Relationship lines first, so boxes can cover them.
    for source_key, target_key, cardinality in RELATIONS:
        source = ENTITIES[source_key]
        target = ENTITIES[target_key]
        (x1, y1), (x2, y2), direction = anchor(source, target)
        if direction == 'h':
            mid = (x1 + x2) / 2
            points = [(x1, y1), (mid, y1), (mid, y2), (x2, y2)]
        else:
            mid = (y1 + y2) / 2
            points = [(x1, y1), (x1, mid), (x2, mid), (x2, y2)]
        draw.line(points, fill=(150, 165, 152), width=3, joint='curve')
        for point in ((x1, y1), (x2, y2)):
            draw.ellipse([point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7], fill=GREEN)
        label_x = points[1][0] + 10 if direction == 'h' else points[1][0] + 12
        label_y = points[1][1] - 26 if direction == 'h' else points[1][1] + 8
        draw.text((label_x, label_y), cardinality, font=BADGE, fill=(110, 125, 112))

    # Entity boxes.
    for entity in ENTITIES.values():
        x1, y1, x2, y2 = box_geometry(entity)
        draw.rounded_rectangle([x1 + 5, y1 + 6, x2 + 5, y2 + 6], radius=10, fill=(234, 232, 224))
        rounded_box(draw, [x1, y1, x2, y2], 10, WHITE, LINE, 2)
        draw.rounded_rectangle([x1, y1, x2, y1 + HEADER_H], radius=10, fill=GREEN)
        draw.rectangle([x1, y1 + HEADER_H - 12, x2, y1 + HEADER_H], fill=GREEN)
        draw.text((x1 + 18, y1 + 12), entity['title'], font=HEAD, fill=WHITE)
        draw.text((x2 - 96, y1 + 18), 'TABLE', font=BADGE, fill=LIME)

        row_y = y1 + HEADER_H
        for index, (name, field_type, marker) in enumerate(entity['fields']):
            if index % 2 == 0:
                draw.rectangle([x1 + 1, row_y, x2 - 1, row_y + ROW_H], fill=(252, 251, 247))
            draw.line([(x1 + 1, row_y + ROW_H), (x2 - 1, row_y + ROW_H)], fill=(242, 242, 236), width=1)
            color = INK
            if 'PK' in marker:
                color = GREEN_DARK
            elif 'FK' in marker:
                color = BLUE
            draw.text((x1 + 18, row_y + 6), name, font=REG, fill=color)
            draw.text((x1 + 245, row_y + 8), field_type, font=SMALL, fill=MUTED)
            if marker:
                badge_color = LIME if 'PK' in marker else (230, 238, 246) if 'FK' in marker else (244, 237, 221)
                badge_text = LIME if 'PK' in marker else BLUE if 'FK' in marker else AMBER
                text_w = draw.textlength(marker, font=BADGE)
                draw.rounded_rectangle(
                    [x2 - 20 - text_w - 12, row_y + 8, x2 - 16, row_y + 8 + 20],
                    radius=4,
                    fill=(215, 236, 176) if 'PK' in marker else badge_color,
                )
                draw.text((x2 - 18 - text_w - 6, row_y + 10), marker, font=BADGE, fill=GREEN_DARK if 'PK' in marker else badge_text)
            row_y += ROW_H

    # Legend.
    legend_y = H - 130
    draw.line([(MARGIN, legend_y - 22), (W - MARGIN, legend_y - 22)], fill=LINE, width=2)
    draw.text((MARGIN, legend_y), 'Legend', font=BOLD, fill=GREEN_DARK)
    legend = [
        ('PK', 'primary key', LIME, GREEN_DARK),
        ('FK', 'foreign key', (230, 238, 246), BLUE),
        ('UQ', 'unique constraint', (244, 237, 221), AMBER),
        ('CHK', 'database check', (240, 240, 236), INK),
        ('SNAP', 'immutable purchase-time snapshot', (228, 240, 228), GREEN),
    ]
    x = MARGIN + 130
    for label, description, fill, text_fill in legend:
        width = draw.textlength(label, font=BADGE) + 16
        draw.rounded_rectangle([x, legend_y - 2, x + width, legend_y + 22], radius=4, fill=fill)
        draw.text((x + 8, legend_y + 3), label, font=BADGE, fill=text_fill)
        draw.text((x + width + 9, legend_y + 2), description, font=SMALL, fill=MUTED)
        x += width + 9 + draw.textlength(description, font=SMALL) + 44
    draw.text(
        (MARGIN, H - 52),
        'Generated from store/models.py - order_items keeps unit_price_snapshot, product_name_snapshot and sellers so historical orders never change when a product is edited.',
        font=SMALL,
        fill=MUTED,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, 'PNG', optimize=True)
    print(f'Wrote {OUT} ({OUT.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()



