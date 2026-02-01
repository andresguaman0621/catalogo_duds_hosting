from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import FileResponse, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from .utils import Product, categorize_product, download_image
from io import BytesIO
import csv
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import textwrap 
from reportlab.lib.colors import black
from datetime import datetime
from urllib.parse import unquote
from django.db import connections
from django.utils import timezone
from django.contrib.auth import logout

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
                
                -- Formateo de color optimizado
                CASE 
                    WHEN v.color_raw IS NOT NULL AND TRIM(v.color_raw) != '' THEN
                        CONCAT(
                            UPPER(LEFT(REPLACE(v.color_raw, '-', ' '), 1)),
                            LOWER(SUBSTRING(REPLACE(v.color_raw, '-', ' '), 2))
                        )
                    ELSE 'Sin color'
                END AS color,
                
                -- Formateo de talla optimizado
                CASE 
                    WHEN v.talla_raw IS NOT NULL AND TRIM(v.talla_raw) != '' THEN
                        UPPER(SUBSTRING_INDEX(v.talla_raw, '-', -1))
                    ELSE 'Única'
                END AS size,
                
                v.stock_int AS stock,
                
                -- NUEVAS COLUMNAS DE UBICACIÓN
                v.stock_loc_294,
                v.stock_loc_295,
                
                -- JOIN directo para thumbnail
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
            
            # Validación rápida
            name = str(row_dict.get('name', '')).strip()
            stock = int(row_dict.get('stock', 0))
            
            if not name or stock <= 0:
                continue
            
            product = Product(
                sku=str(row_dict.get('sku') or row_dict['ID']),
                name=name,
                color=str(row_dict.get('color', 'Sin color')).strip(),
                size=str(row_dict.get('size', 'Única')).strip(),
                regular_price=Decimal('0.00'),
                stock=stock,
                thumbnail_url=str(row_dict.get('thumbnail_url', '')).strip(),
                
                # Mapeo de los CAMPOS NUEVOS
                stock_loc_294=str(row_dict.get('stock_loc_294', '0')).strip(),
                stock_loc_295=str(row_dict.get('stock_loc_295', '0')).strip(),
            )
            
            products.append(product)
            
    return products


@login_required
def select_category(request):
    """
    Muestra las categorías disponibles basadas en productos en stock
    """
    from .utils import categories
    
    # Obtener productos directamente de WordPress
    products = fetch_wordpress_products()
    product_categories = {categorize_product(p.name) for p in products if categorize_product(p.name) != "Sin categoría"}
    
    available_categories = {cat: categories[cat] for cat in product_categories if cat in categories}
    
    return render(request, 'catalog/select_category.html', {'categories': available_categories})

@login_required
def select_size(request, category):
    # Decodificar la categoría de la URL
    decoded_category = unquote(category)
    
    # Obtener productos directamente de WordPress con stock >= 1
    products = fetch_wordpress_products()
    
    # Usar la categoría decodificada para el filtro
    sizes = {p.size for p in products if categorize_product(p.name) == decoded_category}
    
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
    # Decodificar la categoría
    decoded_category = unquote(category)
    sizes = sizes.split(",")
    response_data = []
    
    for size in sizes:
        try:
            pdf_content = generate_pdf_content(decoded_category, size)
            if pdf_content:
                filename = f"{decoded_category}_{size}.pdf"
                if len(sizes) == 1:
                    response = HttpResponse(pdf_content, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    return response
                
                pdf_key = f'pdf_{category}_{size}'
                request.session[pdf_key] = pdf_content.hex()
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
    pdf_content = request.session.get(pdf_key)
    
    if pdf_content:
        # Convertir el string hex de vuelta a bytes
        pdf_bytes = bytes.fromhex(pdf_content)
        filename = f"{unquote(category)}_{size}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        # Limpiar la sesión después de la descarga
        del request.session[pdf_key]
        return response
    
    return HttpResponse('PDF not found', status=404)
    
def generate_pdf_content(category, size):
    # Función que genera el contenido del PDF para cada talla y categoría
    all_products = fetch_wordpress_products()
    products = [p for p in all_products if p.size == size and categorize_product(p.name) == category]
    
    products = sorted(products, key=lambda p: p.color.lower())

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    #Titulo del PDF
    c.setTitle("Catálogo DUDS")
    
    width, height = letter

    # Configuración de diseño
    space_between_rows = 3.5 * inch
    space_between_columns = 4 * inch
    image_display_width = 2.0 * inch

    # Agregar fecha y hora en la primera página
    current_datetime = timezone.localtime().strftime("%d/%m/%Y (%H:%M)")
    c.setFont("Helvetica", 10)
    c.drawString(width - 130, height - 20, current_datetime)

    def add_product_to_page(product, x, y):
        # Variables por defecto para imagen
        display_height = 2.0 * inch  # Altura estándar
        image_loaded = False
        temp_path = None
        
        # Intentar cargar y procesar imagen
        try:
            img = download_image(product.thumbnail_url)
            img_width, img_height = img.size
            aspect = img_height / float(img_width)
            display_height = image_display_width * aspect

            # Guardar temporalmente la imagen
            temp_path = f"temp_{product.sku}.jpg"
            img.save(temp_path, "JPEG", quality=85)
            image_loaded = True
            
        except Exception as e:
            print(f"Error cargando imagen para producto {product.sku}: {str(e)}")
            image_loaded = False

        # Fondo negro
        c.setFillColor(black)
        c.rect(x - 3, y - display_height - 5, image_display_width, display_height, fill=1)
        
        if image_loaded and temp_path:
            try:
                c.drawImage(
                    temp_path,
                    x + 2, y - display_height,
                    width=image_display_width,
                    height=display_height
                )
                os.remove(temp_path)
            except Exception as e:
                print(f"Error dibujando imagen para producto {product.sku}: {str(e)}")
                c.setFillColor('white')
                c.rect(x + 2, y - display_height, image_display_width, display_height, fill=1)
                c.setFont("Helvetica", 10)
                c.setFillColor(black)
                c.drawString(x + 30, y - display_height/2, "Error al cargar")
                c.drawString(x + 30, y - display_height/2 - 12, "imagen")
        else:
            c.setFillColor('white')
            c.rect(x + 2, y - display_height, image_display_width, display_height, fill=1)
            c.setFont("Helvetica", 10)
            c.setFillColor(black)
            c.drawString(x + 30, y - display_height/2, "Error al cargar")
            c.drawString(x + 30, y - display_height/2 - 12, "imagen")
        
        # Marco
        c.setStrokeColor(black)
        c.rect(x + 2, y - display_height, image_display_width, display_height, fill=0)

        # --- BLOQUE DE TEXTO DINÁMICO (nombre, SKU, color, talla) ---

        product_name = product.name.split('-')[0].strip()
        wrapped_lines = textwrap.wrap(product_name, width=15)

        text_x = x + 2.35 * inch
        text_y = y - 50  # punto de inicio del texto

        # Nombre
        c.setFont("Helvetica", 12)
        c.setFillColor(black)
        for line in wrapped_lines:
            c.drawString(text_x, text_y, line)
            text_y -= 14  # baja una línea

        # Pequeño espacio
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
        
        
        # 1. Posición base (Stock Total)
        y_stock_total = y - 168 
        
        c.setFont("Helvetica", 12)
        c.drawString(text_x, y_stock_total, f"Disponible: {product.stock}")

        # 2. Stock Ubicación 294 (Cablec)
        y_loc_294 = y_stock_total - 14 
        c.setFont("Helvetica", 10)
        c.drawString(text_x, y_loc_294, f"Cablec: {product.stock_loc_294}")
        
        # 3. Stock Ubicación 295 (Bodega)
        y_loc_295 = y_loc_294 - 12  
        c.drawString(text_x, y_loc_295, f"Bodega: {product.stock_loc_295}")
        
        # ------------------------------------


    for i, product in enumerate(products):
        page_position = i % 6  # 6 productos por página (2 columnas x 3 filas)
        if page_position == 0 and i != 0:
            c.showPage()
            # Agregar fecha en páginas subsiguientes
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
    
def user_logout(request):
    logout(request)
    return redirect('/admin/login/?next=/select_category/')