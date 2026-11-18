"""Generate docs/architecture.png (system architecture diagram)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'architecture.png'

W, H = 2000, 1180
PAPER = (251, 250, 246)
GREEN = (36, 92, 70)
GREEN_DARK = (22, 61, 48)
LIME = (215, 236, 176)
INK = (29, 41, 37)
MUTED = (117, 129, 123)
LINE = (218, 221, 210)
WHITE = (255, 255, 255)
BLUE = (47, 95, 130)
AMBER = (194, 138, 50)


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


TITLE = font(r'C:\Windows\Fonts\georgiab.ttf', 44)
HEAD = font(r'C:\Windows\Fonts\georgiab.ttf', 24)
BODY = font(r'C:\Windows\Fonts\arial.ttf', 18)
SMALL = font(r'C:\Windows\Fonts\arial.ttf', 15)
BOLD = font(r'C:\Windows\Fonts\arialbd.ttf', 18)


def box(draw, xy, fill=WHITE, outline=LINE, radius=12, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def label(draw, xy, text, fnt=BODY, fill=INK):
    draw.text(xy, text, font=fnt, fill=fill)


def arrow(draw, start, end, color=GREEN, width=3):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    # simple arrowhead
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 13
    points = [
        (x2, y2),
        (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45)),
        (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45)),
    ]
    draw.polygon(points, fill=color)


image = Image.new('RGB', (W, H), PAPER)
draw = ImageDraw.Draw(image)

draw.text((60, 45), 'Rukomeza Market - system architecture', font=TITLE, fill=GREEN_DARK)
draw.text((60, 108), 'One Django deployment serves the HTML storefront, the admin dashboards and the JSON API over HTTPS.', font=BODY, fill=MUTED)
draw.line([(60, 150), (W - 60, 150)], fill=LINE, width=2)

# Clients
box(draw, [60, 190, 1940, 300], fill=(240, 245, 235))
label(draw, (85, 207), 'CLIENTS', HEAD, GREEN_DARK)
client_boxes = [
    (90, 240, 610, 285, 'Customers - storefront, cart, checkout, tracking'),
    (640, 240, 1160, 285, 'Sellers - studio, listings, stock, orders'),
    (1190, 240, 1710, 285, 'Administrators - dashboard, moderation, reports'),
    (1740, 240, 1910, 285, 'API clients - bearer token'),
]
for x1, y1, x2, y2, text in client_boxes:
    box(draw, [x1, y1, x2, y2], fill=WHITE)
    label(draw, (x1 + 14, y1 + 12), text, SMALL)

arrow(draw, (1000, 300), (1000, 355), GREEN)
label(draw, (1015, 315), 'HTTPS / TLS 1.3  (Render, HSTS, secure cookies)', SMALL, MUTED)

# App container
box(draw, [60, 365, 1940, 830], fill=WHITE, outline=GREEN, width=3)
label(draw, (85, 383), 'DJANGO APPLICATION (Gunicorn workers)', HEAD, GREEN_DARK)
label(draw, (1510, 390), 'Django 6.1  -  Python 3.13', SMALL, MUTED)

# Row of internal components
box(draw, [90, 430, 530, 560], fill=(248, 250, 244))
label(draw, (108, 445), 'Presentation', BOLD, GREEN_DARK)
for index, text in enumerate([
    'Django templates + responsive CSS',
    'Chart.js admin reports',
    'Order tracking timeline',
    'WhiteNoise static files',
]):
    label(draw, (108, 478 + index * 20), f'- {text}', SMALL)

box(draw, [555, 430, 995, 560], fill=(248, 250, 244))
label(draw, (573, 445), 'Interface layer', BOLD, GREEN_DARK)
for index, text in enumerate([
    'HTML views + forms (CSRF)',
    'JSON API /api/v1/',
    'Role decorators + object checks',
    'Bearer tokens / sessions',
]):
    label(draw, (573, 478 + index * 20), f'- {text}', SMALL)

box(draw, [1020, 430, 1460, 560], fill=(240, 246, 251))
label(draw, (1038, 445), 'Service layer', BOLD, BLUE)
for index, text in enumerate([
    'cart.py - limits, merge, totals',
    'checkout.py - atomic stock',
    'orders.py - lifecycle + audit',
    'payments.py - mock gateway',
]):
    label(draw, (1038, 478 + index * 20), f'- {text}', SMALL)

box(draw, [1485, 430, 1910, 560], fill=(252, 247, 236))
label(draw, (1503, 445), 'Reporting and moderation', BOLD, AMBER)
for index, text in enumerate([
    'reports.py - revenue, sellers, stock',
    'Admin approval + disputes',
    'Order dispatch / delivery',
    'CSV-friendly JSON endpoints',
]):
    label(draw, (1503, 478 + index * 20), f'- {text}', SMALL)

# Integrity strip
box(draw, [90, 590, 1910, 690], fill=(235, 243, 231), outline=(190, 210, 186))
label(draw, (108, 606), 'INTEGRITY CONTROLS', BOLD, GREEN_DARK)
integrity = [
    'select_for_update() row locks',
    'conditional UPDATE ... WHERE stock >= qty',
    'DB CHECK constraints (stock >= 0, status set)',
    'immutable order-item price snapshots',
    'status state machine + audit events',
    'HMAC-signed gateway callback',
]
for index, text in enumerate(integrity):
    label(draw, (108 + (index % 3) * 600, 638 + (index // 3) * 24), f'- {text}', SMALL)

# Data layer
label(draw, (90, 735), 'DATA AND EXTERNAL SERVICES', BOLD, MUTED)
box(draw, [90, 765, 690, 815], fill=WHITE)
label(draw, (108, 780), 'PostgreSQL (Neon / Render) - 17 tables', SMALL)
box(draw, [720, 765, 1260, 815], fill=WHITE)
label(draw, (738, 780), 'Media / CDN (local or Cloudinary / R2)', SMALL)
box(draw, [1290, 765, 1910, 815], fill=WHITE)
label(draw, (1308, 780), 'Mock gateway (success / failure, signed webhook)', SMALL)

# Arrows app to data
arrow(draw, (390, 690), (390, 765), GREEN)
arrow(draw, (990, 690), (990, 765), GREEN)
arrow(draw, (1600, 690), (1600, 765), GREEN)

# Bootstrap arrows between internal components
for x in (530, 995, 1460):
    arrow(draw, (x + 3, 495), (x + 22, 495), GREEN, 2)

# Bottom notes
draw.line([(60, 880), (W - 60, 880)], fill=LINE, width=2)
label(draw, (60, 905), 'Request path', HEAD, GREEN_DARK)
notes = [
    '1. Browser sends an HTTPS request to the single Render URL.',
    '2. Django routes it to a view or API endpoint; authentication and role checks run first.',
    '3. The service layer validates stock and prices, then writes inside one transaction.',
    '4. PostgreSQL enforces constraints; the response is rendered as HTML or JSON.',
]
for index, text in enumerate(notes):
    label(draw, (60, 948 + index * 28), text, BODY, INK)

label(draw, (1050, 948), 'Concurrency guarantee', HEAD, GREEN_DARK)
concurrency = [
    'Two customers can read the same stock row.',
    'Both attempt UPDATE ... SET stock = stock - qty WHERE stock >= qty.',
    'Only the rows that satisfy the predicate are updated.',
    'The loser gets 0 rows -> the order rolls back; no overselling.',
]
for index, text in enumerate(concurrency):
    label(draw, (1050, 988 + index * 28), text, SMALL, INK)

draw.text((60, H - 38), 'Generated from the deployed Django project - see docs/ERD.md and docs/PROJECT_REPORT.md', font=SMALL, fill=MUTED)

OUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUT, 'PNG', optimize=True)
print(f'Wrote {OUT} ({OUT.stat().st_size // 1024} KB)')
