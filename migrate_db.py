"""
Database Migration Script
Add category, is_new_launch, and sale_price columns to Product table

Run this once to update your existing database
"""

import sqlite3
import os

def migrate_database():
    # Get database path
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, "store.db")
    
    print(f"Migrating database at: {db_path}")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(product)")
        columns = [column[1] for column in cursor.fetchall()]
        
        migrations_done = []
        
        # Add category column if not exists
        if 'category' not in columns:
            print("Adding category column...")
            cursor.execute("ALTER TABLE product ADD COLUMN category VARCHAR(50)")
            migrations_done.append("category")
        else:
            print("✓ Category column already exists")
        
        # Add is_new_launch column if not exists
        if 'is_new_launch' not in columns:
            print("Adding is_new_launch column...")
            cursor.execute("ALTER TABLE product ADD COLUMN is_new_launch BOOLEAN DEFAULT 0")
            migrations_done.append("is_new_launch")
        else:
            print("✓ is_new_launch column already exists")
        
        # Add sale_price column if not exists
        if 'sale_price' not in columns:
            print("Adding sale_price column...")
            cursor.execute("ALTER TABLE product ADD COLUMN sale_price INTEGER")
            migrations_done.append("sale_price")
        else:
            print("✓ sale_price column already exists")
        
        conn.commit()
        
        if migrations_done:
            print(f"\n✅ Successfully added columns: {', '.join(migrations_done)}")
        else:
            print("\n✅ All columns already exist - database is up to date!")
        
        # Display current products
        cursor.execute("SELECT id, name, category, is_new_launch, sale_price FROM product")
        products = cursor.fetchall()
        
        if products:
            print(f"\nCurrent products in database ({len(products)} total):")
            print("-" * 80)
            print(f"{'ID':<5} {'Name':<30} {'Category':<20} {'New Launch':<12} {'Sale Price':<10}")
            print("-" * 80)
            for product in products:
                category = product[2] if product[2] else "Not assigned"
                new_launch = "Yes" if product[3] else "No"
                sale_price = f"₹{product[4]}" if product[4] else "-"
                print(f"{product[0]:<5} {product[1][:29]:<30} {category:<20} {new_launch:<12} {sale_price:<10}")
            print("-" * 80)
        else:
            print("\nNo products found in database.")
        
        print("\n✅ Migration completed successfully!")
        print("\n📝 New Features Added:")
        print("1. Categories - Organize products into 7 categories")
        print("2. New Launch Tag - Mark products as newly launched (Green badge)")
        print("3. Sale Pricing - Set sale prices with automatic discount calculation")
        print("\n🎯 Next steps:")
        print("1. Run your Flask app: python app.py")
        print("2. Go to admin panel and update your products:")
        print("   - Assign categories")
        print("   - Mark new launches")
        print("   - Set sale prices")
        print("3. Features will appear automatically on your store!")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 80)
    print("KCX CROCHET STORE - DATABASE MIGRATION")
    print("=" * 80)
    print()
    migrate_database()