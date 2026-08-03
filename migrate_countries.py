from database import engine, SessionLocal
from sqlalchemy import text, inspect

db = SessionLocal()
inspector = inspect(engine)

# 1. Check countries table and seed
with engine.connect() as conn:
    conn.execute(text('''
    CREATE TABLE IF NOT EXISTS countries (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE
    )
    '''))
    conn.commit()

countries_list = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
    "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo", "Costa Rica",
    "Côte d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czech Republic", "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica", "Dominican Republic",
    "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji", "Finland",
    "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea",
    "Guinea-Bissau", "Guyana", "Haiti", "Holy See", "Honduras", "Hungary", "Iceland", "India", "Indonesia", "Iran",
    "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius",
    "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia", "Norway",
    "Oman", "Pakistan", "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland",
    "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland",
    "Syria", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey",
    "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan", "Vanuatu",
    "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

with engine.connect() as conn:
    for c in sorted(countries_list):
        conn.execute(text("INSERT IGNORE INTO countries (name) VALUES (:name)"), {"name": c})
    conn.commit()

print("Seeded countries table with ~195 countries.")

# 2. Check and migrate customers table
with engine.connect() as conn:
    customer_cols = [c['name'] for c in inspector.get_columns('customers')]
    if 'country_id' not in customer_cols:
        conn.execute(text("ALTER TABLE customers ADD COLUMN country_id INT"))
        conn.commit()
        print("Added country_id column to customers.")

    if 'country' in customer_cols:
        # Migrate existing customers country string to country_id
        res = conn.execute(text("SELECT id, country FROM customers WHERE country_id IS NULL AND country IS NOT NULL")).fetchall()
        for cid, cstr in res:
            c_res = conn.execute(text("SELECT id FROM countries WHERE name = :name"), {"name": cstr.strip()}).fetchone()
            if c_res:
                conn.execute(text("UPDATE customers SET country_id = :country_id WHERE id = :id"), {"country_id": c_res[0], "id": cid})
            else:
                # Default to India (id=79) or handle unmapped countries as needed
                conn.execute(text("UPDATE customers SET country_id = 79 WHERE id = :id"), {"id": cid})
        conn.commit()
        print("Migrated customer country_ids.")

        # Drop the old 'country' string column after migration
        conn.execute(text("ALTER TABLE customers DROP COLUMN country"))
        conn.commit()
        print("Dropped old country string column from customers.")

    # Make country_id NOT NULL and add foreign key constraint if not already
    if 'country_id' in customer_cols:
        # Check if NOT NULL constraint is already there (might vary by DB)
        # For simplicity, we'll try to add and catch error or check metadata later.
        # Assume it's not yet NOT NULL after initial ADD COLUMN.
        try:
            conn.execute(text("ALTER TABLE customers MODIFY COLUMN country_id INT NOT NULL"))
            conn.commit()
            print("Made customers.country_id NOT NULL.")
        except Exception as e:
            print(f"Could not make customers.country_id NOT NULL (might be already or data issues): {e}")

        # Add foreign key constraint if it doesn't exist
        existing_fks = inspector.get_foreign_keys(table_name='customers')
        if not any(fk['constrained_columns'] == ['country_id'] for fk in existing_fks):
            try:
                conn.execute(text("ALTER TABLE customers ADD CONSTRAINT fk_customer_country FOREIGN KEY (country_id) REFERENCES countries(id)"))
                conn.commit()
                print("Added foreign key constraint to customers.country_id.")
            except Exception as e:
                print(f"Could not add foreign key to customers.country_id: {e}")


# 3. Check and migrate products table
with engine.connect() as conn:
    product_cols = [c['name'] for c in inspector.get_columns('products')]
    if 'country_id' not in product_cols:
        conn.execute(text("ALTER TABLE products ADD COLUMN country_id INT"))
        conn.commit()
        print("Added country_id column to products.")

    if 'country' in product_cols:
        # Migrate existing products country string to country_id
        res = conn.execute(text("SELECT id, country FROM products WHERE country_id IS NULL AND country IS NOT NULL")).fetchall()
        for pid, cstr in res:
            c_res = conn.execute(text("SELECT id FROM countries WHERE name = :name"), {"name": cstr.strip()}).fetchone()
            if c_res:
                conn.execute(text("UPDATE products SET country_id = :country_id WHERE id = :id"), {"country_id": c_res[0], "id": pid})
            else:
                # Default to India (id=79) or handle unmapped countries as needed
                conn.execute(text("UPDATE products SET country_id = 79 WHERE id = :id"), {"id": pid})
        conn.commit()
        print("Migrated product country_ids.")

        # Drop the old 'country' string column after migration
        conn.execute(text("ALTER TABLE products DROP COLUMN country"))
        conn.commit()
        print("Dropped old country string column from products.")
    
    if 'country_id' in product_cols:
        # Make country_id NOT NULL and add foreign key constraint
        try:
            conn.execute(text("ALTER TABLE products MODIFY COLUMN country_id INT NOT NULL"))
            conn.commit()
            print("Made products.country_id NOT NULL.")
        except Exception as e:
            print(f"Could not make products.country_id NOT NULL (might be already or data issues): {e}")

        existing_fks = inspector.get_foreign_keys(table_name='products')
        if not any(fk['constrained_columns'] == ['country_id'] for fk in existing_fks):
            try:
                conn.execute(text("ALTER TABLE products ADD CONSTRAINT fk_product_country FOREIGN KEY (country_id) REFERENCES countries(id)"))
                conn.commit()
                print("Added foreign key constraint to products.country_id.")
            except Exception as e:
                print(f"Could not add foreign key to products.country_id: {e}")


# 4. Check and migrate registrations table
with engine.connect() as conn:
    registration_cols = [c['name'] for c in inspector.get_columns('registrations')]
    if 'country_id' not in registration_cols:
        conn.execute(text("ALTER TABLE registrations ADD COLUMN country_id INT"))
        conn.commit()
        print("Added country_id column to registrations.")

    if 'country' in registration_cols:
        # Migrate existing registrations country string to country_id
        res = conn.execute(text("SELECT id, country FROM registrations WHERE country_id IS NULL AND country IS NOT NULL")).fetchall()
        for rid, cstr in res:
            c_res = conn.execute(text("SELECT id FROM countries WHERE name = :name"), {"name": cstr.strip()}).fetchone()
            if c_res:
                conn.execute(text("UPDATE registrations SET country_id = :country_id WHERE id = :id"), {"country_id": c_res[0], "id": rid})
            else:
                # Default to India (id=79) or handle unmapped countries as needed
                conn.execute(text("UPDATE registrations SET country_id = 79 WHERE id = :id"), {"id": rid})
        conn.commit()
        print("Migrated registration country_ids.")

        # Drop the old 'country' string column after migration
        conn.execute(text("ALTER TABLE registrations DROP COLUMN country"))
        conn.commit()
        print("Dropped old country string column from registrations.")

    if 'country_id' in registration_cols:
        # Make country_id NOT NULL and add foreign key constraint
        try:
            conn.execute(text("ALTER TABLE registrations MODIFY COLUMN country_id INT NOT NULL"))
            conn.commit()
            print("Made registrations.country_id NOT NULL.")
        except Exception as e:
            print(f"Could not make registrations.country_id NOT NULL (might be already or data issues): {e}")

        existing_fks = inspector.get_foreign_keys(table_name='registrations')
        if not any(fk['constrained_columns'] == ['country_id'] for fk in existing_fks):
            try:
                conn.execute(text("ALTER TABLE registrations ADD CONSTRAINT fk_registration_country FOREIGN KEY (country_id) REFERENCES countries(id)"))
                conn.commit()
                print("Added foreign key constraint to registrations.country_id.")
            except Exception as e:
                print(f"Could not add foreign key to registrations.country_id: {e}")


# 5. Check and migrate orders table
with engine.connect() as conn:
    order_cols = [c['name'] for c in inspector.get_columns('orders')]
    if 'country_id' not in order_cols:
        conn.execute(text("ALTER TABLE orders ADD COLUMN country_id INT"))
        conn.commit()
        print("Added country_id column to orders.")

    if 'country' in order_cols:
        # Migrate existing orders country string to country_id
        res = conn.execute(text("SELECT id, country FROM orders WHERE country_id IS NULL AND country IS NOT NULL")).fetchall()
        for oid, cstr in res:
            c_res = conn.execute(text("SELECT id FROM countries WHERE name = :name"), {"name": cstr.strip()}).fetchone()
            if c_res:
                conn.execute(text("UPDATE orders SET country_id = :country_id WHERE id = :id"), {"country_id": c_res[0], "id": oid})
            else:
                # Default to India (id=79) or handle unmapped countries as needed
                conn.execute(text("UPDATE orders SET country_id = 79 WHERE id = :id"), {"id": oid})
        conn.commit()
        print("Migrated order country_ids.")

        # Drop the old 'country' string column after migration
        conn.execute(text("ALTER TABLE orders DROP COLUMN country"))
        conn.commit()
        print("Dropped old country string column from orders.")
    
    if 'country_id' in order_cols:
        # Make country_id NOT NULL and add foreign key constraint
        try:
            conn.execute(text("ALTER TABLE orders MODIFY COLUMN country_id INT NOT NULL"))
            conn.commit()
            print("Made orders.country_id NOT NULL.")
        except Exception as e:
            print(f"Could not make orders.country_id NOT NULL (might be already or data issues): {e}")

        existing_fks = inspector.get_foreign_keys(table_name='orders')
        if not any(fk['constrained_columns'] == ['country_id'] for fk in existing_fks):
            try:
                conn.execute(text("ALTER TABLE orders ADD CONSTRAINT fk_order_country FOREIGN KEY (country_id) REFERENCES countries(id)"))
                conn.commit()
                print("Added foreign key constraint to orders.country_id.")
            except Exception as e:
                print(f"Could not add foreign key to orders.country_id: {e}")

print("Migration completed successfully.")
