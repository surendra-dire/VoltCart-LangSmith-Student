"""Static electronics catalog and small search helpers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable


def _product(
    product_id: str,
    name: str,
    brand: str,
    category: str,
    price: int,
    mrp: int,
    rating: float,
    reviews: int,
    stock: int,
    icon: str,
    short_spec: str,
    specs: list[str],
    badge: str = "Deal",
    theme: str = "blue",
) -> dict[str, Any]:
    discount = round((mrp - price) * 100 / mrp)
    return {
        "id": product_id,
        "name": name,
        "brand": brand,
        "category": category,
        "price": price,
        "mrp": mrp,
        "discount": discount,
        "rating": rating,
        "reviews": reviews,
        "stock": stock,
        "icon": icon,
        "short_spec": short_spec,
        "specs": specs,
        "badge": badge,
        "theme": theme,
        "delivery": "Free delivery in 2–4 days",
    }


PRODUCTS: list[dict[str, Any]] = [
    _product("PHN-101", "iPhone 15 128GB", "Apple", "Smartphones", 69900, 79900, 4.7, 1834, 18, "📱", "A16 Bionic · 48MP camera", ["6.1-inch Super Retina XDR", "A16 Bionic chip", "48MP main camera"], "Top pick", "sky"),
    _product("PHN-102", "Galaxy S24 256GB", "Samsung", "Smartphones", 74999, 79999, 4.6, 1251, 14, "📱", "Galaxy AI · 50MP camera", ["6.2-inch Dynamic AMOLED", "Galaxy AI features", "256GB storage"], "AI phone", "violet"),
    _product("PHN-103", "OnePlus 12R 256GB", "OnePlus", "Smartphones", 42999, 45999, 4.5, 982, 21, "📱", "Snapdragon 8 Gen 2 · 120Hz", ["6.78-inch AMOLED", "5500mAh battery", "100W SUPERVOOC"], "Bestseller", "blue"),
    _product("PHN-104", "Pixel 8a 128GB", "Google", "Smartphones", 49999, 52999, 4.4, 647, 9, "📱", "Tensor G3 · AI camera", ["6.1-inch OLED", "Tensor G3", "7 years of updates"], "New", "mint"),
    _product("PHN-105", "Xiaomi 14 Civi", "Xiaomi", "Smartphones", 42999, 47999, 4.3, 526, 16, "📱", "Leica optics · 1.5K AMOLED", ["Leica triple camera", "Snapdragon 8s Gen 3", "67W charging"], "Camera deal", "coral"),
    _product("LAP-201", "Lenovo IdeaPad Slim 3", "Lenovo", "Laptops", 55990, 68990, 4.4, 893, 11, "💻", "Core i5 · 16GB · 512GB SSD", ["13th Gen Intel Core i5", "16GB DDR5 RAM", "15.6-inch FHD display"], "Student pick", "blue"),
    _product("LAP-202", "HP Victus 15 Gaming", "HP", "Laptops", 67990, 78999, 4.5, 731, 7, "🎮", "Ryzen 5 · RTX 3050 · 144Hz", ["AMD Ryzen 5", "NVIDIA RTX 3050", "144Hz FHD display"], "Gaming deal", "indigo"),
    _product("LAP-203", "ASUS Vivobook 15 OLED", "ASUS", "Laptops", 62990, 75990, 4.6, 608, 8, "💻", "Core i5 · OLED · 16GB", ["15.6-inch OLED display", "Intel Core i5", "16GB RAM and 512GB SSD"], "OLED deal", "violet"),
    _product("LAP-204", "MacBook Air M2", "Apple", "Laptops", 84990, 99900, 4.8, 2176, 6, "💻", "M2 chip · 13.6-inch · 18hr", ["Apple M2 chip", "13.6-inch Liquid Retina", "Up to 18-hour battery"], "Premium", "slate"),
    _product("LAP-205", "Dell Inspiron 14 2-in-1", "Dell", "Laptops", 72490, 83990, 4.3, 319, 5, "💻", "Core 7 · Touch · 16GB", ["14-inch FHD+ touch", "360-degree hinge", "16GB RAM and 1TB SSD"], "Flexible", "sky"),
    _product("AUD-301", "Sony WH-CH720N Headphones", "Sony", "Audio", 8990, 12990, 4.6, 3452, 32, "🎧", "Wireless ANC · 35hr battery · Multipoint", ["Digital noise cancellation", "Up to 35-hour battery", "Multipoint Bluetooth"], "Hot deal", "coral"),
    _product("AUD-302", "JBL Flip 6 Speaker", "JBL", "Audio", 9499, 14999, 4.7, 2801, 19, "🔊", "Wireless 30W · IP67 · 12hr battery", ["JBL Pro Sound", "IP67 waterproof", "12-hour playtime"], "32% off", "teal"),
    _product("AUD-303", "boAt Airdopes 141", "boAt", "Audio", 1299, 4490, 4.2, 18431, 54, "🎵", "Wireless · 42hr playtime · ENx calls", ["42-hour total playtime", "Low-latency mode", "Fast charge"], "Mega deal", "blue"),
    _product("AUD-304", "OnePlus Buds 3", "OnePlus", "Audio", 5499, 6499, 4.5, 1642, 27, "🎧", "Wireless · 49dB ANC · Dual drivers", ["49dB smart ANC", "Dual dynamic drivers", "Up to 44-hour battery"], "Bestseller", "mint"),
    _product("WER-401", "Galaxy Watch6", "Samsung", "Wearables", 23999, 32999, 4.5, 987, 12, "⌚", "AMOLED · Body composition", ["1.5-inch Super AMOLED", "Body composition tracking", "Wear OS"], "27% off", "violet"),
    _product("WER-402", "Apple Watch SE", "Apple", "Wearables", 29900, 34900, 4.7, 2044, 10, "⌚", "Crash Detection · GPS", ["Retina display", "Crash Detection", "Swimproof design"], "Popular", "coral"),
    _product("WER-403", "Fitbit Charge 6", "Fitbit", "Wearables", 13999, 16999, 4.3, 572, 15, "⌚", "GPS · ECG · 7-day battery", ["Built-in GPS", "ECG app", "Up to 7-day battery"], "Fitness pick", "teal"),
    _product("HOM-501", "LG 55-inch 4K Smart TV", "LG", "TV & Smart Home", 44990, 65990, 4.6, 1374, 6, "📺", "4K UHD · webOS · HDR10", ["55-inch 4K UHD", "webOS smart platform", "HDR10 Pro"], "Big screen", "indigo"),
    _product("HOM-502", "Samsung 43-inch Crystal 4K", "Samsung", "TV & Smart Home", 31490, 47990, 4.5, 1621, 8, "📺", "Crystal 4K · HDR · SmartThings", ["43-inch Crystal UHD", "PurColor", "SmartThings support"], "34% off", "blue"),
    _product("HOM-503", "Echo Dot 5th Gen", "Amazon", "TV & Smart Home", 4499, 5499, 4.6, 9751, 38, "🏠", "Alexa · Motion sensor · Bluetooth", ["Alexa voice assistant", "Temperature sensor", "Improved bass"], "Smart home", "sky"),
    _product("GAM-601", "PlayStation 5 Slim", "Sony", "Gaming & Accessories", 54990, 59990, 4.8, 3907, 4, "🎮", "1TB SSD · 4K gaming", ["1TB ultra-high-speed SSD", "4K gaming", "DualSense controller"], "Low stock", "slate"),
    _product("ACC-602", "Logitech MX Master 3S", "Logitech", "Gaming & Accessories", 8995, 10995, 4.7, 1263, 17, "🖱️", "8K DPI · Quiet clicks · USB-C", ["8,000 DPI sensor", "Quiet clicks", "Multi-device control"], "Creator pick", "teal"),
    _product("ACC-603", "Keychron K2 V2 Keyboard", "Keychron", "Gaming & Accessories", 7499, 8999, 4.5, 884, 13, "⌨️", "Wireless · Mechanical · RGB", ["75% mechanical layout", "Bluetooth and USB-C", "RGB backlight"], "Desk deal", "violet"),
    _product("ACC-604", "SanDisk Extreme SSD 1TB", "SanDisk", "Gaming & Accessories", 8799, 12499, 4.7, 2265, 22, "💾", "1050MB/s · IP65 · Portable", ["1TB portable storage", "Up to 1050MB/s", "IP65 water resistance"], "Storage deal", "coral"),
    _product("TAB-701", "iPad 10th Gen", "Apple", "Tablets", 31999, 39900, 4.7, 4863, 18, "📟", "10.9-inch · A14 · Wi-Fi", ["10.9-inch Liquid Retina", "A14 Bionic chip", "12MP landscape camera"], "Student deal", "sky"),
    _product("TAB-702", "Galaxy Tab S9 FE", "Samsung", "Tablets", 29999, 36999, 4.5, 941, 14, "📟", "10.9-inch · S Pen · IP68", ["10.9-inch 90Hz display", "S Pen included", "IP68 water resistance"], "S Pen included", "mint"),
]

PRODUCTS_BY_ID = {product["id"]: product for product in PRODUCTS}
CATEGORIES = sorted({product["category"] for product in PRODUCTS})

# Natural category words an LLM or shopper may use for the fixed catalog.
# Values remain canonical so filters and product data use one vocabulary.
CATEGORY_ALIASES = {
    "audio": "Audio",
    "earbud": "Audio",
    "earbuds": "Audio",
    "headphone": "Audio",
    "headphones": "Audio",
    "speaker": "Audio",
    "speakers": "Audio",
    "laptop": "Laptops",
    "laptops": "Laptops",
    "computer": "Laptops",
    "computers": "Laptops",
    "phone": "Smartphones",
    "phones": "Smartphones",
    "smartphone": "Smartphones",
    "smartphones": "Smartphones",
    "mobile": "Smartphones",
    "mobiles": "Smartphones",
    "tablet": "Tablets",
    "tablets": "Tablets",
    "watch": "Wearables",
    "watches": "Wearables",
    "smartwatch": "Wearables",
    "smartwatches": "Wearables",
    "wearable": "Wearables",
    "wearables": "Wearables",
    "tv": "TV & Smart Home",
    "television": "TV & Smart Home",
    "smart home": "TV & Smart Home",
    "gaming": "Gaming & Accessories",
    "game": "Gaming & Accessories",
    "console": "Gaming & Accessories",
    "accessory": "Gaming & Accessories",
    "accessories": "Gaming & Accessories",
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def canonical_category(value: str) -> str:
    """Resolve a canonical category from UI or natural-language terminology."""
    normalized = normalize(value)
    if not normalized:
        return ""
    exact = {normalize(category): category for category in CATEGORIES}
    if normalized in exact:
        return exact[normalized]
    if normalized in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[normalized]
    # Accept descriptive values such as "wireless headphones" or
    # "audio headphones" without allowing a partial two-letter match.
    alias_matches = {
        category
        for alias, category in CATEGORY_ALIASES.items()
        if re.search(rf"\b{re.escape(alias)}\b", normalized)
    }
    return next(iter(alias_matches)) if len(alias_matches) == 1 else ""


def get_product(product_id: str) -> dict[str, Any] | None:
    product = PRODUCTS_BY_ID.get(product_id.upper().strip())
    return dict(product) if product else None


def _haystack(product: dict[str, Any]) -> str:
    return normalize(" ".join([product["id"], product["name"], product["brand"], product["category"], product["short_spec"], *product["specs"]]))


def search_products(
    query: str = "",
    category: str = "",
    max_price: int | None = None,
    in_stock_only: bool = False,
    limit: int = 26,
) -> list[dict[str, Any]]:
    query_tokens = set(normalize(query).split())
    resolved_category = canonical_category(category)
    category_normalized = normalize(resolved_category or category)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for product in PRODUCTS:
        if category_normalized and category_normalized not in normalize(product["category"]):
            continue
        if max_price is not None and product["price"] > max_price:
            continue
        if in_stock_only and product["stock"] <= 0:
            continue
        haystack = _haystack(product)
        haystack_tokens = set(haystack.split())
        if query_tokens:
            overlap = len(query_tokens & haystack_tokens) / len(query_tokens)
            phrase_bonus = 1.0 if normalize(query) in haystack else 0.0
            score = overlap + phrase_bonus
            if score <= 0:
                continue
        else:
            score = product["rating"] / 10 + product["discount"] / 100
        ranked.append((score, product))
    ranked.sort(key=lambda item: (item[0], item[1]["rating"], item[1]["discount"]), reverse=True)
    return [dict(product) for _, product in ranked[: max(1, min(limit, 26))]]


def find_best_product(reference: str, candidates: Iterable[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    reference_normalized = normalize(reference)
    if not reference_normalized:
        return None
    direct = get_product(reference)
    if direct:
        return direct
    best: tuple[float, dict[str, Any]] | None = None
    for product in candidates or PRODUCTS:
        name = normalize(f"{product['brand']} {product['name']}")
        token_overlap = len(set(reference_normalized.split()) & set(name.split())) / max(1, len(set(name.split())))
        contains = 0.75 if reference_normalized in name or name in reference_normalized else 0.0
        sequence = SequenceMatcher(None, reference_normalized, name).ratio()
        score = contains + token_overlap + sequence * 0.35
        if best is None or score > best[0]:
            best = (score, product)
    return dict(best[1]) if best and best[0] >= 0.42 else None
