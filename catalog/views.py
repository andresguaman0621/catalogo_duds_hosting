from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from .utils import Product, categorize_product, download_image
from io import BytesIO
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
import textwrap
from reportlab.lib.colors import black
from urllib.parse import unquote
from django.db import connections
from django.utils import timezone
from django.contrib.auth import logout
from django.core.cache import cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import tempfile

PRODUCTS_CACHE_KEY = 'wordpress_products'
PRODUCTS_CACHE_TIMESTAMP_KEY = 'wordpress_products_timestamp'
PRODUCTS_CACHE_TTL = 300  # 5 minutos

PDF_TEMP_DIR = os.path.join(tempfile.gettempdir(), 'duds_pdfs')
os.makedirs(PDF_TEMP_DIR, exist_ok=True)


def fetch_wordpress_products():
    """
    Versión optimizada específica para MariaDB 10.6
    Usa GROUP BY en lugar de múltiples JOINs
    """
    products = []

    with connections['default'].cursor() as cursor:
        cursor.execute("""
            SELECT
                v.ID,
                v.sku,
                v.clean_name AS name,

                CASE
                    WHEN v.color_raw IS NOT NULL AND TRIM(v.color_raw) != '' THEN
                        CONCAT(
                            UPPER(LEFT(REPLACE(v.color_raw, '-', ' '), 1)),
                            LOWER(SUBSTRING(REPLACE(v.color_raw, '-', ' '), 2))
                        )
                    ELSE 'Sin color'
                END AS color,

                CASE
                    WHEN v.talla_raw IS NOT NULL AND TRIM(v.talla_raw) != '' THEN
                        UPPER(SUBSTRING_INDEX(v.talla_raw, '-', -1))
                    ELSE 'Única'
                END AS size,

                v.stock_int AS stock,
                v.stock_loc_294,
                v.stock_loc_295,
                COALESCE(att.guid, '') AS thumbnail_url

            FROM vw_products_mariadb v
            LEFT JOIN wpdt_posts att ON v.thumbnail_id = att.ID
                AND att.post_type = 'attachment'
            WHERE v.stock_int >= 1
            ORDER BY v.ID ASC;
        """)

        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        for row in rows:
            row_dict = dict(zip(columns, row))

            name = str(row_dict.get('name', '')).strip()
            stock = int(row_dict.get('stock', 0))

            if not name or stock <= 0:
                continue

            product = Product(
                sku=str(row_dict.get('sku') or row_dict['ID']),
                name=name,
                color=str(row_dict.get('color', 'Sin color')).strip(),
                size=str(row_dict.get('size', 'Única')).strip(),
                stock=stock,
                thumbnail_url=str(row_dict.get('thumbnail_url', '')).strip(),
                stock_loc_294=str(row_dict.get('stock_loc_294', '0')).strip(),
                stock_loc_295=str(row_dict.get('stock_loc_295', '0')).strip(),
            )

            products.append(product)

    return products


def get_cached_products():
    """Obtiene productos con cache de 5 minutos para evitar queries redundantes"""
    products = cache.get(PRODUCTS_CACHE_KEY)
    if products is None:
        products = fetch_wordpress_products()
        cache.set(PRODUCTS_CACHE_KEY, products, PRODUCTS_CACHE_TTL)
        cache.set(PRODUCTS_CACHE_TIMESTAMP_KEY, timezone.localtime(), PRODUCTS_CACHE_TTL)
    return products


def _get_cache_timestamp():
    """Retorna el timestamp de la última carga de datos"""
    return cache.get(PRODUCTS_CACHE_TIMESTAMP_KEY)


def _invalidate_cache():
    """Invalida el cache de productos para forzar recarga"""
    cache.delete(PRODUCTS_CACHE_KEY)
    cache.delete(PRODUCTS_CACHE_TIMESTAMP_KEY)


def _prefetch_images(products):
    """Pre-descarga imágenes en paralelo usando ThreadPoolExecutor"""
    unique_urls = list({p.thumbnail_url for p in products if p.thumbnail_url})
    image_map = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(download_image, url): url for url in unique_urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            image_map[url] = future.result()

    return image_map


@login_required
def select_category(request):
    """Muestra las categorías disponibles basadas en productos en stock"""
    from .utils import categories

    products = get_cached_products()

    # Conteo de productos por categoría
    category_counts = {}
    for p in products:
        cat = categorize_product(p.name)
        if cat == "Sin categoría" or cat not in categories:
            continue
        category_counts[cat] = category_counts.get(cat, 0) + 1

    available_categories = [
        (cat, category_counts[cat])
        for cat in categories
        if cat in category_counts
    ]

    last_updated = _get_cache_timestamp()

    return render(request, 'catalog/select_category.html', {
        'categories': available_categories,
        'last_updated': last_updated,
    })


@login_required
def refresh_data(request):
    """Invalida el cache y redirige a select_category"""
    _invalidate_cache()
    return redirect('select_category')


SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']

def _sort_sizes(sizes):
    """Ordena tallas según el estándar de tallas de ropa (XS, S, M, L...)"""
    order_map = {s: i for i, s in enumerate(SIZE_ORDER)}
    known = sorted([s for s in sizes if s in order_map], key=lambda s: order_map[s])
    unknown = sorted(s for s in sizes if s not in order_map)
    return known + unknown


@login_required
def select_size(request, category):
    decoded_category = unquote(category)
    products = get_cached_products()
    category_products = [p for p in products if categorize_product(p.name) == decoded_category]

    # Contar productos por talla
    size_counts = {}
    for p in category_products:
        size_counts[p.size] = size_counts.get(p.size, 0) + 1

    sorted_sizes = _sort_sizes(size_counts.keys())
    sizes = [(s, size_counts[s]) for s in sorted_sizes]

    if request.method == 'POST':
        selected_sizes = request.POST.getlist('sizes')

        if not selected_sizes:
            error_message = "Por favor selecciona al menos una talla."
            return render(request, 'catalog/select_size.html', {
                'category': decoded_category,
                'sizes': sizes,
                'error': error_message
            })

        return redirect('generate_pdfs', category=category, sizes=",".join(selected_sizes))

    return render(request, 'catalog/select_size.html', {
        'category': decoded_category,
        'sizes': sizes
    })


@login_required
def generate_pdfs(request, category, sizes):
    decoded_category = unquote(category)
    sizes = sizes.split(",")

    # Obtener productos UNA sola vez para todas las tallas
    all_products = get_cached_products()

    # Pre-filtrar y ordenar productos por talla
    products_by_size = {}
    for size in sizes:
        products_by_size[size] = sorted(
            [p for p in all_products if p.size == size and categorize_product(p.name) == decoded_category],
            key=lambda p: p.color.lower()
        )

    # Pre-descargar TODAS las imágenes de todas las tallas en paralelo
    all_filtered = [p for prods in products_by_size.values() for p in prods]
    image_map = _prefetch_images(all_filtered)

    response_data = []

    for size in sizes:
        try:
            pdf_content = generate_pdf_content(products_by_size[size], image_map)
            if pdf_content:
                filename = f"{decoded_category}_{size}.pdf"
                if len(sizes) == 1:
                    response = HttpResponse(pdf_content, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    return response

                # Guardar PDF en archivo temporal en lugar de sesión hex
                pdf_id = str(uuid.uuid4())
                pdf_path = os.path.join(PDF_TEMP_DIR, f"{pdf_id}.pdf")
                with open(pdf_path, 'wb') as f:
                    f.write(pdf_content)

                pdf_key = f'pdf_{category}_{size}'
                request.session[pdf_key] = pdf_id
                response_data.append({
                    'url': f'/download_pdf/{category}/{size}/',
                    'filename': filename
                })

        except Exception as e:
            return JsonResponse({
                'error': f"Error generating PDF for size {size}: {str(e)}"
            }, status=500)

    return JsonResponse({'files': response_data})


@login_required
def download_pdf(request, category, size):
    pdf_key = f'pdf_{category}_{size}'
    pdf_id = request.session.get(pdf_key)

    if pdf_id:
        pdf_path = os.path.join(PDF_TEMP_DIR, f"{pdf_id}.pdf")
        if os.path.exists(pdf_path):
            filename = f"{unquote(category)}_{size}.pdf"
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
            os.remove(pdf_path)
            del request.session[pdf_key]
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

    return HttpResponse('PDF not found', status=404)


def generate_pdf_content(products, image_map):
    """Genera el contenido del PDF para una lista de productos"""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setPageCompression(1)
    c.setTitle("Catálogo DUDS")

    width, height = letter

    # Configuración de diseño
    space_between_rows = 3.5 * inch
    space_between_columns = 4 * inch
    image_display_width = 2.0 * inch

    current_datetime = timezone.localtime().strftime("%d/%m/%Y (%H:%M)")
    c.setFont("Helvetica", 10)
    c.drawString(width - 130, height - 20, current_datetime)

    def add_product_to_page(product, x, y):
        display_height = 2.0 * inch
        img_reader = None

        try:
            img = image_map.get(product.thumbnail_url)
            if img is None:
                img = download_image(product.thumbnail_url)

            img_width, img_height = img.size
            aspect = img_height / float(img_width)
            display_height = image_display_width * aspect

            # Usar BytesIO en lugar de archivo temporal
            img_buffer = BytesIO()
            img.save(img_buffer, "JPEG", quality=85)
            img_buffer.seek(0)
            img_reader = ImageReader(img_buffer)

        except Exception as e:
            print(f"Error procesando imagen para producto {product.sku}: {str(e)}")
            img_reader = None

        # Fondo negro
        c.setFillColor(black)
        c.rect(x - 3, y - display_height - 5, image_display_width, display_height, fill=1)

        if img_reader:
            try:
                c.drawImage(
                    img_reader,
                    x + 2, y - display_height,
                    width=image_display_width,
                    height=display_height
                )
            except Exception as e:
                print(f"Error dibujando imagen para producto {product.sku}: {str(e)}")
                _draw_image_error(c, x, y, display_height, image_display_width)
        else:
            _draw_image_error(c, x, y, display_height, image_display_width)

        # Marco
        c.setStrokeColor(black)
        c.rect(x + 2, y - display_height, image_display_width, display_height, fill=0)

        # --- BLOQUE DE TEXTO ---
        product_name = product.name.split('-')[0].strip()
        wrapped_lines = textwrap.wrap(product_name, width=15)

        text_x = x + 2.35 * inch
        text_y = y - 50

        # Nombre
        c.setFont("Helvetica", 12)
        c.setFillColor(black)
        for line in wrapped_lines:
            c.drawString(text_x, text_y, line)
            text_y -= 14

        text_y -= 6

        # SKU
        c.setFont("Helvetica", 10)
        c.drawString(text_x, text_y, f"SKU: {product.sku}")
        text_y -= 14

        # Color
        c.setFont("Helvetica", 12)
        c.drawString(text_x, text_y, f"Color: {product.color}")
        text_y -= 18

        # Talla
        c.setFont("Helvetica-Bold", 15)
        c.drawString(text_x, text_y, f"{product.size}")

        # Stock
        y_stock_total = y - 168

        c.setFont("Helvetica", 12)
        c.drawString(text_x, y_stock_total, f"Disponible: {product.stock}")

        y_loc_294 = y_stock_total - 14
        c.setFont("Helvetica", 10)
        c.drawString(text_x, y_loc_294, f"Cablec: {product.stock_loc_294}")

        y_loc_295 = y_loc_294 - 12
        c.drawString(text_x, y_loc_295, f"Bodega: {product.stock_loc_295}")

    for i, product in enumerate(products):
        page_position = i % 6
        if page_position == 0 and i != 0:
            c.showPage()
            c.setFont("Helvetica", 10)
            c.drawString(width - 130, height - 20, current_datetime)

        row = page_position // 2
        col = page_position % 2

        x = 0.5 * inch + col * space_between_columns
        y = height - (0.5 * inch + row * space_between_rows)

        add_product_to_page(product, x, y)

    c.save()
    buffer.seek(0)
    pdf_content = buffer.getvalue()
    buffer.close()
    return pdf_content


def _draw_image_error(c, x, y, display_height, image_display_width):
    """Dibuja un placeholder cuando la imagen no se puede cargar"""
    c.setFillColor('white')
    c.rect(x + 2, y - display_height, image_display_width, display_height, fill=1)
    c.setFont("Helvetica", 10)
    c.setFillColor(black)
    c.drawString(x + 30, y - display_height / 2, "Error al cargar")
    c.drawString(x + 30, y - display_height / 2 - 12, "imagen")


def user_logout(request):
    logout(request)
    return redirect('/admin/login/?next=/select_category/')
