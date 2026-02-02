from dataclasses import dataclass
from functools import lru_cache
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
    "Pantalones": ["Pantalon"]
}

# Pre-normalizar las keywords una sola vez
def _normalize_categories(categories_dict):
    """Pre-normaliza todas las keywords para evitar repetir el proceso"""
    normalized = {}
    for category, keywords in categories_dict.items():
        normalized[category] = [normalizar_texto(keyword.lower()) for keyword in keywords]
    return normalized

# Keywords pre-normalizadas (se ejecuta solo una vez)
categories_normalized = _normalize_categories(categories)

@lru_cache(maxsize=1024)
def categorize_product(name):
    """
    Categoriza un producto basándose en su nombre,
    ignorando tildes y diacríticos.
    Resultados cacheados con lru_cache para evitar recálculos.
    """
    name_normalizado = normalizar_texto(name.lower())

    for category, keywords_normalizados in categories_normalized.items():
        if all(keyword in name_normalizado for keyword in keywords_normalizados):
            return category

    return "Sin categoría"

# Regex pre-compilados
_dimension_pattern = re.compile(r'-\d+x\d+\.(jpg|jpeg|png|webp)$', re.IGNORECASE)
_extension_pattern = re.compile(r'\.(jpg|jpeg|png|webp)$', re.IGNORECASE)

def get_wordpress_optimized_url(original_url):
    """
    Convierte una URL original de WordPress a su versión optimizada
    con las dimensiones específicas 1070x1536
    """
    if _dimension_pattern.search(original_url):
        return original_url

    match = _extension_pattern.search(original_url)
    if not match:
        return original_url

    extension = match.group(1)
    base_url = original_url.rsplit('.', 1)[0]

    optimized_url = f"{base_url}-1070x1536.{extension}"
    return optimized_url

def download_image(url):
    """
    Descarga una imagen usando la versión optimizada de WordPress (1070x1536)
    """
    urls_to_try = [get_wordpress_optimized_url(url), url]

    for attempt_url in urls_to_try:
        try:
            response = requests.get(attempt_url, timeout=10)
            response.raise_for_status()
            return Image.open(BytesIO(response.content))
        except requests.exceptions.RequestException:
            continue
        except Exception:
            continue

    # Si todas las URLs fallan, devolver imagen por defecto
    return Image.new('RGB', (1070, 1536), 'white')
