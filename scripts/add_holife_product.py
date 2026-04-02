#!/usr/bin/env python3
"""
Script to add Holife Arginine product information to the database.
"""
import sys
import os
import json

# Add automation app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automation"))

from app.db import ensure_db, create_product, get_product_by_id


def add_holife_arginine_product():
    """
    Add the Holife Power Boost Arginine 6300 product from AliExpress.
    Product details from issue: https://github.com/blackdog-kor/my-bot/issues/...
    """

    # Ensure database tables exist
    ensure_db()

    # Product information from the issue
    product_id = "1005008142620956"
    source = "aliexpress"
    url = "https://ko.aliexpress.com/item/1005008142620956.html"
    title = "홀라이프 파워부스트 아르기닌6300 고함량 L-아르기닌 타우린 100포 x 1박스 (00936)"
    price = "₩21,519"
    original_price = "₩28,560"
    discount_percent = 24
    rating = "4.8"
    sales_count = "900+"
    promo_info = "₩130,000 구매 시 ₩15,000 할인\n신규 회원 ₩7,041 할인"

    # Additional metadata
    meta_json = json.dumps({
        "sku": "00936",
        "package": "100포 x 1박스",
        "category": "건강보조식품",
        "ingredients": ["L-아르기닌", "타우린"],
        "description": "고함량 L-아르기닌 타우린 건강보조식품",
    }, ensure_ascii=False)

    # Create or update the product
    row_id = create_product(
        product_id=product_id,
        source=source,
        url=url,
        title=title,
        price=price,
        original_price=original_price,
        discount_percent=discount_percent,
        rating=rating,
        sales_count=sales_count,
        promo_info=promo_info,
        meta_json=meta_json,
    )

    print(f"✓ Product added/updated successfully with ID: {row_id}")

    # Verify the product was added
    product = get_product_by_id(product_id, source)
    if product:
        print(f"\n제품 정보 확인:")
        print(f"  Product ID: {product['product_id']}")
        print(f"  Title: {product['title']}")
        print(f"  Price: {product['price']} (원가: {product['original_price']}, {product['discount_percent']}% 할인)")
        print(f"  Rating: {product['rating']}")
        print(f"  Sales: {product['sales_count']} 판매")
        print(f"  URL: {product['url']}")
        print(f"  Promo Info:\n    {product['promo_info'].replace(chr(10), chr(10) + '    ')}")
        print(f"  Created: {product['created_at']}")
        print(f"  Updated: {product['updated_at']}")
    else:
        print("⚠ Warning: Could not retrieve product after creation")

    return row_id


if __name__ == "__main__":
    add_holife_arginine_product()
