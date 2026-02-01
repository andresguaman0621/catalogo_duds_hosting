from dataclasses import dataclass
from decimal import Decimal
import unicodedata
import re
import requests
from PIL import Image
from io import BytesIO

@dataclass
class Product:
    sku: str
    name: str
    color: str
    size: str
    regular_price: Decimal
    stock: int
    thumbnail_url: str
    stock_loc_294: str
    stock_loc_295: str
    
    def __str__(self):
        return f"{self.name} - {self.size}"

def normalizar_texto(texto):
    """Quita tildes y diacríticos del texto"""
    return unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('ascii')

# Diccionario original (mantener para compatibilidad con imports existentes)
categories = {
    "Camiseta Oversize": ["Camiseta", "Oversize"],
    "Camiseta Estampado Boxy Fit Original": ["Camiseta", "Boxy", "Fit", "Original"],
    "Camiseta Estampado Boxy Fit Premium": ["Camiseta", "Boxy", "Fit", "Premium"],
    "Jogger": ["Jogger"],
    "Hoodie Oversize": ["Hoodie", "Oversize Fit"],
    "Hoodie Oversize con Cierre": ["Hoodie Oversize", "con Cierre"],
    "Pantaloneta": ["Pantaloneta"],
    "Hoodie Relaxed Fit": ["Hoodie", "Relaxed"],
    "Camiseta Boxy Polo": ["Camiseta", "Boxy", "Polo"],
    "Colección Exclusiva": ["Twofold"],
    "Pantalones": ["Pantalon"]  # Solo una variante, sin tilde
}

# OPTIMIZACIÓN 1: Pre-normalizar las keywords una sola vez
def _normalize_categories(categories_dict):
    """Pre-normaliza todas las keywords para evitar repetir el proceso"""
    normalized = {}
    for category, keywords in categories_dict.items():
        normalized[category] = [normalizar_texto(keyword.lower()) for keyword in keywords]
    return normalized

# Keywords pre-normalizadas (se ejecuta solo una vez)
categories_normalized = _normalize_categories(categories)

def categorize_product(name):
    """
    Categoriza un producto basándose en su nombre, 
    ignorando tildes y diacríticos
    OPTIMIZADO: Ya no normaliza keywords en cada llamada
    """
    name_normalizado = normalizar_texto(name.lower())
    
    for category, keywords_normalizados in categories_normalized.items():
        # Las keywords ya están normalizadas, solo verificamos coincidencias
        if all(keyword in name_normalizado for keyword in keywords_normalizados):
            return category
    
    return "Sin categoría"

# OPTIMIZACIÓN 2: Compilar regex una sola vez
_dimension_pattern = re.compile(r'-\d+x\d+\.(jpg|jpeg|png|webp)$', re.IGNORECASE)
_extension_pattern = re.compile(r'\.(jpg|jpeg|png|webp)$', re.IGNORECASE)

def get_wordpress_optimized_url(original_url):
    """
    Convierte una URL original de WordPress a su versión optimizada 
    con las dimensiones específicas 1070x1536
    OPTIMIZADO: Usa regex pre-compilados
    """
    # Verificar si la URL ya tiene dimensiones (está optimizada)
    if _dimension_pattern.search(original_url):
        return original_url
    
    # Extraer la extensión del archivo
    match = _extension_pattern.search(original_url)
    if not match:
        return original_url
    
    extension = match.group(1)
    base_url = original_url.rsplit('.', 1)[0]
    
    # Construir la URL optimizada con las dimensiones específicas
    optimized_url = f"{base_url}-1070x1536.{extension}"
    return optimized_url

def download_image(url):
    """
    Descarga una imagen usando la versión optimizada de WordPress (1070x1536)
    OPTIMIZADO: Imports movidos al nivel superior, lógica de fallback simplificada
    """
    urls_to_try = [get_wordpress_optimized_url(url), url]
    
    for attempt_url in urls_to_try:
        try:
            response = requests.get(attempt_url, timeout=10)
            response.raise_for_status()
            return Image.open(BytesIO(response.content))
        except requests.exceptions.RequestException:
            continue  # Intentar con la siguiente URL
        except Exception:
            continue  # Para errores de PIL u otros
    
    # Si todas las URLs fallan, devolver imagen por defecto
    return Image.new('RGB', (1070, 1536), 'white')

# OPTIMIZACIÓN ADICIONAL: Cache para URLs ya procesadas (opcional)
#from functools import lru_cache

#@lru_cache(maxsize=128)
#def get_wordpress_optimized_url_cached(original_url):
    #"""
    #Versión con cache de get_wordpress_optimized_url
    #Útil si se procesan las mismas URLs repetidamente
    #"""
    #return get_wordpress_optimized_url(original_url)