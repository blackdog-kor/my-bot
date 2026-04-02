#!/usr/bin/env python3
"""
Test script for product tracking functionality.
"""
import sys
import os

# Add automation app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automation"))

from app.db import ensure_db, get_product_by_id, list_products


def test_product_tracking():
    """Test that product tracking functionality works correctly."""
    print("Testing product tracking functionality...\n")

    # Ensure database is initialized
    ensure_db()
    print("✓ Database initialized successfully\n")

    # Test 1: Retrieve specific product
    print("Test 1: Retrieve Holife Arginine product")
    product = get_product_by_id("1005008142620956", "aliexpress")
    if product:
        print(f"  ✓ Product found: {product['title']}")
        print(f"    Price: {product['price']}")
        print(f"    Rating: {product['rating']}")
        print(f"    Discount: {product['discount_percent']}%")
    else:
        print("  ✗ Product not found")
        return False

    # Test 2: List all products
    print("\nTest 2: List all products")
    products = list_products(limit=10)
    print(f"  ✓ Found {len(products)} product(s)")
    for p in products:
        print(f"    - [{p['source']}] {p['title'][:50]}...")

    # Test 3: Verify data integrity
    print("\nTest 3: Verify data integrity")
    if product['product_id'] == "1005008142620956":
        print("  ✓ Product ID matches")
    else:
        print("  ✗ Product ID mismatch")
        return False

    if product['source'] == "aliexpress":
        print("  ✓ Source is correct")
    else:
        print("  ✗ Source mismatch")
        return False

    if product['discount_percent'] == 24:
        print("  ✓ Discount percentage is correct")
    else:
        print("  ✗ Discount percentage mismatch")
        return False

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_product_tracking()
    sys.exit(0 if success else 1)
