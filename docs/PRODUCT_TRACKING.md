# Product Tracking Feature

## Overview

This feature adds product tracking capabilities to the casino-system bot, allowing it to store and manage product information from e-commerce platforms like AliExpress.

## Database Schema

A new `products` table has been added to the database with the following fields:

- `id`: Auto-incrementing primary key
- `product_id`: Unique identifier for the product on the source platform
- `source`: Platform source (e.g., "aliexpress")
- `url`: Full URL to the product page
- `title`: Product title/name
- `price`: Current price
- `original_price`: Original/list price before discounts
- `discount_percent`: Discount percentage
- `rating`: Product rating
- `sales_count`: Number of sales
- `promo_info`: Promotional information and offers
- `meta_json`: Additional metadata in JSON format
- `created_at`: Timestamp when the record was created
- `updated_at`: Timestamp when the record was last updated

## API Functions

### `create_product()`

Create or update a product entry. If a product with the same `product_id` and `source` already exists, it will be updated.

```python
from app.db import create_product

row_id = create_product(
    product_id="1005008142620956",
    source="aliexpress",
    url="https://ko.aliexpress.com/item/1005008142620956.html",
    title="홀라이프 파워부스트 아르기닌6300 고함량 L-아르기닌 타우린 100포 x 1박스",
    price="₩21,519",
    original_price="₩28,560",
    discount_percent=24,
    rating="4.8",
    sales_count="900+",
    promo_info="₩130,000 구매 시 ₩15,000 할인\n신규 회원 ₩7,041 할인",
    meta_json='{"sku": "00936", "category": "건강보조식품"}',
)
```

### `get_product_by_id()`

Retrieve a product by its product_id and source.

```python
from app.db import get_product_by_id

product = get_product_by_id("1005008142620956", "aliexpress")
if product:
    print(f"Title: {product['title']}")
    print(f"Price: {product['price']}")
```

### `list_products()`

List all products with pagination.

```python
from app.db import list_products

products = list_products(limit=10, offset=0)
for p in products:
    print(f"{p['title']} - {p['price']}")
```

## Example Products

### Holife Arginine 6300

The first tracked product is the Holife Power Boost Arginine supplement from AliExpress:

- **Product ID**: 1005008142620956
- **Title**: 홀라이프 파워부스트 아르기닌6300 고함량 L-아르기닌 타우린 100포 x 1박스 (00936)
- **Price**: ₩21,519 (24% off from ₩28,560)
- **Rating**: 4.8 stars
- **Sales**: 900+ units sold
- **Promotions**:
  - ₩15,000 discount on purchases over ₩130,000
  - ₩7,041 discount for new members

## Scripts

### add_holife_product.py

Script to add the Holife Arginine product to the database:

```bash
python3 scripts/add_holife_product.py
```

### test_product_tracking.py

Test script to verify product tracking functionality:

```bash
python3 scripts/test_product_tracking.py
```

## Future Enhancements

Potential improvements for this feature:

1. **Product Scraper**: Automated scraping of product information from AliExpress and other platforms
2. **Price Tracking**: Historical price tracking and alerts for price changes
3. **Bot Integration**: Commands to query and display products via the Telegram bot
4. **Recommendation Engine**: Suggest products based on user preferences
5. **Affiliate Link Management**: Integration with affiliate programs for revenue generation
