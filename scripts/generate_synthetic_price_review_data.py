"""
Synthetic Cape Valley Foods price list generator (spec Section 42). Produces real .xlsx files
via openpyxl - not fixtures pretending to be files. Deliberately plants every category the spec
asks for: increases, decreases, unchanged, new products, discontinued products, description
changes, SKU changes, pack-size changes, and one ambiguous (variant-conflict) pair, so the demo
script that reads these files back exercises the whole pipeline on realistic data.
"""
from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

import openpyxl

random.seed(42)  # reproducible demo data

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Realistic-ish product nouns per category, not just a bare index number - a first pass at this
# generator used "{Category} Product {i} {pack}" for every SKU, which made unrelated products in
# the same category+pack combination score as near-duplicates on token overlap (discontinued
# items were getting force-matched onto whatever else shared a category and pack). Distinct
# nouns per product is what makes the synthetic data behave like a real catalog rather than a
# pathological case for the matcher.
PRODUCT_NOUNS = {
    "Dairy": ["Full Cream Milk", "Cheddar Cheese", "Greek Yoghurt", "Salted Butter", "Cream Cheese",
              "Mozzarella", "Feta Cheese", "Buttermilk", "Custard", "Sour Cream"],
    "Beverages": ["Cola", "Orange Juice", "Sparkling Water", "Iced Tea", "Energy Drink",
                  "Apple Juice", "Ginger Ale", "Tonic Water", "Lemonade", "Grape Juice"],
    "Frozen": ["Chips", "Peas", "Mixed Veg", "Chicken Nuggets", "Fish Fingers", "Ice Cream",
               "Berries", "Pizza Base", "Samoosas", "Spring Rolls"],
    "Dry Goods": ["Basmati Rice", "Penne Pasta", "Rolled Oats", "Cake Flour", "White Sugar",
                  "Brown Lentils", "Chickpeas", "Couscous", "Breadcrumbs", "Custard Powder"],
    "Meat": ["Beef Mince", "Chicken Breast", "Pork Bangers", "Lamb Chops", "Beef Biltong",
             "Chicken Thighs", "Boerewors", "Bacon Rashers", "Beef Rump", "Chicken Wings"],
    "Bakery": ["White Bread", "Burger Buns", "Croissants", "Rusks", "Ciabatta", "Bran Muffins",
               "Hot Dog Rolls", "Wholewheat Bread", "Bagels", "Shortbread"],
    "Packaging": ["Clingwrap", "Foil Trays", "Paper Bags", "Takeaway Boxes", "Cling Film Rolls",
                  "Cutlery Sets", "Napkins", "Freezer Bags", "Cup Lids", "Straws"],
}
CATEGORIES = list(PRODUCT_NOUNS.keys())
PACK_OPTIONS = ["24 x 330ml", "6 x 2L", "12 x 1kg", "10kg", "4 x 5kg", "case 24", "1 x 750ml", "6 x 1L"]

# Nouns reserved exclusively for the 8 planted "discontinued" items below (see idx < 58 branch).
# A first pass reused the shared noun pool for these too, so a discontinued item sometimes shared
# its product name with a genuinely different, still-current product that merely had a different
# pack size - the matcher then correctly treated that as an ambiguous pack-change candidate
# (matching same-name-different-pack products is the right behavior per spec Sections 6-7), which
# meant it was never a fair test of discontinued-detection at all. Reserving these names outright
# is what actually fixes it, not adjusting the matcher.
DISCONTINUED_ONLY_NOUNS = [
    ("Dairy", "Ricotta"), ("Beverages", "Root Beer"), ("Frozen", "Onion Rings"),
    ("Dry Goods", "Quinoa"), ("Meat", "Duck Breast"), ("Bakery", "Pretzels"),
    ("Packaging", "Ice Bags"), ("Frozen", "Waffles"),
]
for _category, _noun in DISCONTINUED_ONLY_NOUNS:
    PRODUCT_NOUNS[_category] = [n for n in PRODUCT_NOUNS[_category] if n != _noun]

BASE_PRODUCTS = []
used_descriptions: set[str] = set()  # every base product must have a genuinely unique
# description+pack combination - a first pass at this generator allowed collisions (only ~70
# distinct nouns across 7 categories for 90 products), which meant some "discontinued" planted
# items coincidentally shared a description with a real surviving product and matched it at high
# confidence for a legitimate reason (they really did look identical). A real catalog rarely has
# two different SKUs with byte-identical descriptions; this generator shouldn't either.
for i in range(1, 91):  # 90 "normal" SKUs, plus planted special cases below = ~100
    idx0 = i - 1  # 0-based, matches the idx used in the scenario-planting loop below
    if 50 <= idx0 < 58:
        # This index will be planted as "discontinued" below - give it a reserved noun so no
        # other product in the catalog can ever look like a plausible pack-change match for it.
        category, noun = DISCONTINUED_ONLY_NOUNS[idx0 - 50]
        pack = random.choice(PACK_OPTIONS)
        description = f"{noun} {pack}"
        used_descriptions.add(description)
    else:
        for _attempt in range(50):
            category = random.choice(CATEGORIES)
            noun = random.choice(PRODUCT_NOUNS[category])
            pack = random.choice(PACK_OPTIONS)
            description = f"{noun} {pack}"
            if description not in used_descriptions:
                used_descriptions.add(description)
                break
        else:
            raise RuntimeError("Could not generate a unique product description - widen PRODUCT_NOUNS")
    price = Decimal(random.randint(20, 800))
    BASE_PRODUCTS.append({
        "sku": f"CVF-{i:04d}",
        "description": description,
        "category": category,
        "pack_size": pack,
        "price": price,
        "barcode": f"60012345{i:04d}",
    })

old_rows = []
new_rows = []

for idx, p in enumerate(BASE_PRODUCTS):
    old_rows.append({**p})

    # Plant deliberate scenarios across the 90 base products by index range.
    if idx < 25:
        # price increase, 2-15%
        pct = Decimal(random.randint(2, 15)) / 100
        new_price = (p["price"] * (1 + pct)).quantize(Decimal("0.01"))
        new_rows.append({**p, "price": new_price})
    elif idx < 40:
        # price decrease
        pct = Decimal(random.randint(2, 10)) / 100
        new_price = (p["price"] * (1 - pct)).quantize(Decimal("0.01"))
        new_rows.append({**p, "price": new_price})
    elif idx < 50:
        # unchanged
        new_rows.append({**p})
    elif idx < 58:
        # discontinued - appears only on old list
        pass
    elif idx < 65:
        # description reworded but same SKU - matching stage 1 (SKU) should still catch it
        # regardless of the text change (e.g. supplier switched from a long-form to short-form
        # description between price-list versions).
        new_rows.append({**p, "description": p["description"].upper() + " NEW DESC"})
    elif idx < 70:
        # SKU changed but description/barcode stayed similar - stage 3/4/5 should catch it
        new_rows.append({**p, "sku": p["sku"] + "-V2"})
    elif idx < 75:
        # pack size changed - the trap case (spec Section 7/40)
        old_pack, old_price = "6 x 2L", Decimal("360")
        new_pack, new_price = "4 x 2L", Decimal("264")
        old_rows[-1] = {**p, "pack_size": old_pack, "price": old_price}
        new_rows.append({**p, "pack_size": new_pack, "price": new_price})
    else:
        new_rows.append({**p})

# New products - only on the new list
for i in range(91, 96):
    category = random.choice(CATEGORIES)
    noun = random.choice(PRODUCT_NOUNS[category])
    pack = random.choice(PACK_OPTIONS)
    new_rows.append({
        "sku": f"CVF-{i:04d}", "description": f"{noun} (New Listing) {pack}",
        "category": category, "pack_size": pack,
        "price": Decimal(random.randint(20, 500)), "barcode": f"60012345{i:04d}",
    })

# Ambiguous / variant-conflict pair: Cheddar Mature vs Cheddar Mild - must NOT auto-match.
old_rows.append({"sku": "CVF-9001", "description": "Cheddar Cheese Mature 2kg",
                  "category": "Dairy", "pack_size": "2kg", "price": Decimal("140"), "barcode": "6001234599901"})
new_rows.append({"sku": "CVF-9002", "description": "Cheddar Cheese Mild 2kg",
                  "category": "Dairy", "pack_size": "2kg", "price": Decimal("142"), "barcode": "6001234599902"})


def write_workbook(rows: list[dict], path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Price List"
    headers = ["Stock Code", "Description", "Category", "Pack Size", "Nett Price", "Barcode"]
    ws.append(headers)
    for r in rows:
        ws.append([r["sku"], r["description"], r["category"], r["pack_size"], float(r["price"]), r["barcode"]])
    wb.save(path)


write_workbook(old_rows, OUT_DIR / "cape_valley_foods_old_price_list.xlsx")
write_workbook(new_rows, OUT_DIR / "cape_valley_foods_new_price_list.xlsx")

print(f"Old list: {len(old_rows)} rows -> {OUT_DIR / 'cape_valley_foods_old_price_list.xlsx'}")
print(f"New list: {len(new_rows)} rows -> {OUT_DIR / 'cape_valley_foods_new_price_list.xlsx'}")
