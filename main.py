from typing import List, Optional
from datetime import date, datetime, timedelta
import uuid
import os
import shutil
import logging
from time import perf_counter
import traceback
from sqlalchemy.orm import relationship, joinedload, selectinload
from sqlalchemy import func, or_, cast, String # Import or_, cast, String for search conditions

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

import models
import schemas
import auth
from schemas import ProductPMCodeUpdate
from database import engine, get_db, SessionLocal
from auth import get_current_user, authenticate_user, create_access_token, get_password_hash
from schemas import CanApproveResponse, CountryListResponse, ProductCreate, ProductSearchResponse, ProductSearchItem, Country, CustomerResponse, SearchSuggestionsResponse, SearchSuggestion, RegistrationCreateRequest, FullSearchResultItem, FullSearchResponse


# Create database tables


app = FastAPI(
    title="EOCT - Export Order Control Tower",
    description="API for managing export orders, compliance, and execution tracking",
    version="1.0.0"
)

logging.basicConfig(level=logging.DEBUG)

@app.on_event("startup")
def update_existing_milestone_names():
    db = SessionLocal()
    try:
        updated_count = db.query(models.Milestone).filter(
            models.Milestone.name == "PM Procurement Released"
        ).update({"name": "PO Released"}, synchronize_session=False)
        if updated_count > 0:
            db.commit()
            logging.info(f"Updated {updated_count} existing milestone(s) from 'PM Procurement Released' to 'PO Released'.")
    except Exception as e:
        db.rollback()
        logging.exception("Error updating milestone names on startup:") # Using logging.exception for full traceback
    finally:
        db.close()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","https://exportordercontroltower.netlify.app",],  # React frontend
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = perf_counter()
    response = await call_next(request)
    process_time = perf_counter() - start_time
    logging.info(f"Request {request.method} {request.url.path} finished in {process_time:.4f}s with status {response.status_code}")
    return response

# Debug endpoint to list all milestones
@app.get("/milestones_debug")
def get_milestones_debug(db: Session = Depends(get_db)):
    """Debug endpoint to list all milestones."""
    return db.query(models.Milestone).all()

# Ensure upload directory exists
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

security = HTTPBearer()

# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/api/auth/login", response_model=schemas.Token)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    start = perf_counter()

    try:
        print("========== LOGIN START ==========")

        t = perf_counter()
        print("1. Request received")
        print("Employee:", user_credentials.employee_id)
        print(f"Time: {perf_counter()-t:.3f}s")

        t = perf_counter()
        print("2. Calling authenticate_user...")
        user = authenticate_user(
            db,
            user_credentials.employee_id,
            user_credentials.password
        )
        print(f"authenticate_user completed in {perf_counter()-t:.3f}s")

        if not user:
            print("User not found")
            raise HTTPException(
                status_code=401,
                detail="Invalid employee ID or password"
            )

        t = perf_counter()
        print("3. Updating last_login")
        user.last_login = datetime.utcnow()
        db.commit()
        print(f"Commit completed in {perf_counter()-t:.3f}s")

        t = perf_counter()
        print("4. Creating JWT")
        access_token = create_access_token(
            data={"sub": user.employee_id}
        )
        print(f"JWT created in {perf_counter()-t:.3f}s")

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user
        }

    except Exception:
        traceback.print_exc()
        raise



@app.get("/api/auth/me", response_model=schemas.UserResponse)
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    logging.debug(f"Current User Info: ID={current_user.id}, EmployeeID={current_user.employee_id}, Department={current_user.department}, Role={current_user.role}")
    return current_user

# ==================== USER MANAGEMENT ====================

@app.get("/api/users", response_model=List[schemas.UserResponse])
def get_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@app.post("/api/users", response_model=schemas.UserResponse)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Check if employee_id already exists
    db_user = db.query(models.User).filter(models.User.employee_id == user.employee_id).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Employee ID already registered")
    
    # Check if email already exists
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Store raw password (no hashing)
    raw_password = get_password_hash(user.password)
    db_user = models.User(
        employee_id=user.employee_id,
        name=user.name,
        email=user.email,
        password=raw_password,
        department=user.department,
        role=user.role,
        is_active=user.is_active
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# ==================== MASTER DATA - PRODUCTS ====================

@app.get("/api/products", response_model=List[schemas.ProductResponse])
def get_products(
    skip: int = 0,
    limit: int = 20,
    scm_user_type: Optional[str] = None, # New parameter for filtering
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Product).options(
        selectinload(models.Product.pm_code_requests).selectinload(models.PMCodeRequest.transactions),
        joinedload(models.Product.country)
    )


    products = query.offset(skip).limit(limit).all()
    return products


@app.post("/api/products", response_model=schemas.ProductResponse)
def create_product(
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Regulatory":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Regulatory department can create products"
        )

    # Check if SKU already exists
    existing_product = db.query(models.Product).filter(models.Product.sku_code == product.sku_code).first()
    if existing_product:
        raise HTTPException(status_code=400, detail="SKU code already exists")

    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@app.get("/api/products/detail/{product_id}", response_model=schemas.ProductResponse)
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    product = db.query(models.Product).options(
        joinedload(models.Product.country),
        joinedload(models.Product.pm_code_requests).joinedload(models.PMCodeRequest.transactions)
    ).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.put("/api/products/{product_id}", response_model=schemas.ProductResponse)
def update_product(
    product_id: int,
    product_update: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Regulatory":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Regulatory department can update products"
        )

    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_product, key, value)

    db_product.updated_at = datetime.utcnow()
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@app.get("/api/products/check-duplicate")
def check_duplicate_product(
    country_name: str,
    customer: str,
    pack_size: str,
    db: Session = Depends(get_db)
):
    country = db.query(models.Country).filter(models.Country.name == country_name).first()
    if not country:
        return {"is_duplicate": False}
    
    existing = db.query(models.Product).filter(

        models.Product.country_id == country.id,
        models.Product.customer == customer,
        models.Product.pack_size == pack_size
    ).first()
    
    if existing:
        return {"is_duplicate": True, "sku": existing.sku_code}
    return {"is_duplicate": False}


@app.get("/api/products/by-country/{country_name}", response_model=List[schemas.ProductResponse])
def get_products_by_country(
    country_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    country = db.query(models.Country).filter(models.Country.name == country_name).first()
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")

    products = (
        db.query(models.Product).options(joinedload(models.Product.country))
        .filter(models.Product.country_id == country.id)
        .filter(models.Product.is_active == True)
        .order_by(models.Product.product_name)
        .all()
    )

    return products


@app.get("/api/products/search", response_model=schemas.ProductSearchResponse)
def search_products(
    query: str = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Search for products by partial SKU code, product name, category, customer, or country name."""
    if not query:
        return {"products": []}
    
    search_query = f"%{query}%"
    
    products = db.query(models.Product).options(joinedload(models.Product.country)).filter(
        models.Product.sku_code.ilike(search_query) |
        models.Product.product_name.ilike(search_query) |

        models.Product.customer.ilike(search_query) |
        (models.Product.country.has(models.Country.name.ilike(search_query)))
    ).limit(10).all()
    
    return {"products": [schemas.ProductSearchItem(sku_code=p.sku_code, product_name=p.product_name) for p in products]}

@app.get("/api/products/last-sku")
def get_last_sku(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get the SKU code of the last created product."""
    last_product = db.query(models.Product).order_by(models.Product.id.desc()).first()
    if last_product:
        return {"sku": last_product.sku_code}
    return {"sku": None}

@app.get("/api/products/sku/{sku_code}", response_model=schemas.ProductResponse)
def get_product_by_sku(
    sku_code: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user) # Keep authentication for now
):
    """Retrieve a single product by its SKU code."""
    print(f"DEBUG: Attempting to fetch product with SKU: {sku_code}")
    product = db.query(models.Product).options(joinedload(models.Product.country)).filter(models.Product.sku_code == sku_code).first()
    if product:
        print(f"DEBUG: Found product: {product.product_name} ({product.sku_code})")
    else:
        print(f"DEBUG: Product with SKU: {sku_code} not found in DB.")
        raise HTTPException(status_code=404, detail="Product not found")
    return product



@app.get("/api/products/filtered", response_model=List[schemas.ProductResponse])
def get_filtered_products(
    country_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Retrieve products filtered by country and/or customer ID."""
    query = db.query(models.Product).options(joinedload(models.Product.country)).filter(models.Product.is_active == True)

    if country_id:
        query = query.filter(models.Product.country_id == country_id)

    if customer_id:
        customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        query = query.filter(models.Product.customer == customer.customer_name)

    products = query.order_by(models.Product.product_name).all()
    return products


@app.get("/api/skus/{country_name}", response_model=List[schemas.ProductSearchItem])
def get_skus_by_country(
    country_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return SKUs (code and name) that have an active registration for the given country name."""
    country = db.query(models.Country).filter(models.Country.name == country_name).first()
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")

    products = db.query(models.Product).filter(
        models.Product.country_id == country.id,
        models.Product.is_active == True
    ).order_by(models.Product.product_name).all()
    
    return [schemas.ProductSearchItem(sku_code=p.sku_code, product_name=p.product_name) for p in products]

@app.get("/api/search/suggestions", response_model=schemas.SearchSuggestionsResponse)
def get_search_suggestions(
    query: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    suggestions = []
    if not query:
        return {"suggestions": []}

    search_pattern = f"%{query.lower()}%"

    # Product search suggestions
    products = db.query(models.Product).options(joinedload(models.Product.country)).filter(
        or_(
            func.lower(models.Product.sku_code).like(search_pattern),
            func.lower(models.Product.product_name).like(search_pattern),
            func.lower(models.Product.category).like(search_pattern),
            func.lower(models.Product.customer).like(search_pattern),
            cast(models.Product.id, String).like(search_pattern)
        )
    ).limit(5).all()
    for p in products:
        suggestions.append(schemas.SearchSuggestion(type="product", id=str(p.id), name=f"{p.product_name} ({p.sku_code})"))

    # Customer search suggestions
    customers = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(
        or_(
            func.lower(models.Customer.customer_name).like(search_pattern),
            func.lower(models.Customer.payment_terms).like(search_pattern),
            func.lower(models.Customer.agreement_status).like(search_pattern),
            cast(models.Customer.id, String).like(search_pattern)
        )
    ).limit(5).all()
    for c in customers:
        suggestions.append(schemas.SearchSuggestion(type="customer", id=str(c.id), name=c.customer_name))

    # Order search suggestions
    orders = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.product),
        joinedload(models.Order.country)
    ).filter(
        or_(
            func.lower(models.Order.order_id).like(search_pattern),
            func.lower(models.Order.order_number).like(search_pattern),
            func.lower(models.Order.po_number).like(search_pattern),
            func.lower(models.Order.sku).like(search_pattern),
            func.lower(models.Order.status).like(search_pattern),
            cast(models.Order.id, String).like(search_pattern),
            func.lower(models.Order.customer.has(models.Customer.customer_name)).like(search_pattern),
            func.lower(models.Order.product.has(models.Product.product_name)).like(search_pattern)
        )
    ).limit(5).all()
    for o in orders:
        cust_name = o.customer.customer_name if o.customer else "N/A"
        suggestions.append(schemas.SearchSuggestion(type="order", id=str(o.id), name=f"Order {o.order_id} - {cust_name} (PO: {o.po_number})"))

    return {"suggestions": suggestions}


@app.get("/api/search/full", response_model=schemas.FullSearchResponse)
def full_search(
    query: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    results: List[schemas.FullSearchResultItem] = []
    if not query:
        return {"results": []}

    search_pattern = f"%{query.lower()}%"

    # Search Products
    products = db.query(models.Product).options(joinedload(models.Product.country)).filter(
        or_(
            func.lower(models.Product.sku_code).like(search_pattern),
            func.lower(models.Product.product_name).like(search_pattern),
            func.lower(models.Product.category).like(search_pattern),
            func.lower(models.Product.customer).like(search_pattern),
            func.lower(models.Product.pack_size).like(search_pattern),
            func.lower(models.Product.primary_pm_code).like(search_pattern),
            func.lower(models.Product.secondary_pm_code).like(search_pattern),
            func.lower(models.Product.leaf_pm_code).like(search_pattern),
            func.lower(models.Product.artwork_status).like(search_pattern),
            cast(models.Product.id, String).like(search_pattern)
        )
    ).all()

    for p in products:
        c_name = p.country.name if p.country else "N/A"
        results.append(schemas.FullSearchResultItem(
            type="product",
            id=str(p.id),
            name=f"{p.product_name} ({p.sku_code})",
            description=f"SKU: {p.sku_code}, Customer: {p.customer or 'N/A'}, Country: {c_name}, Pack: {p.pack_size or 'N/A'}",
            link=f"/products"
        ))

    # Search Customers
    customers = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(
        or_(
            func.lower(models.Customer.customer_name).like(search_pattern),
            func.lower(models.Customer.payment_terms).like(search_pattern),
            func.lower(models.Customer.agreement_status).like(search_pattern),
            cast(models.Customer.id, String).like(search_pattern)
        )
    ).all()

    for c in customers:
        c_name = c.country.name if c.country else "N/A"
        results.append(schemas.FullSearchResultItem(
            type="customer",
            id=str(c.id),
            name=c.customer_name,
            description=f"ID: {c.id}, Country: {c_name}, Agreement: {c.agreement_status or 'N/A'}, Payment Terms: {c.payment_terms or 'N/A'}",
            link=f"/customers/{c.id}"
        ))

    # Search Orders
    orders = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.product),
        joinedload(models.Order.country)
    ).filter(
        or_(
            func.lower(models.Order.order_id).like(search_pattern),
            func.lower(models.Order.order_number).like(search_pattern),
            func.lower(models.Order.po_number).like(search_pattern),
            func.lower(models.Order.sku).like(search_pattern),
            func.lower(models.Order.shipping_terms).like(search_pattern),
            func.lower(models.Order.remarks).like(search_pattern),
            func.lower(models.Order.status).like(search_pattern),
            func.lower(models.Order.compliance_status).like(search_pattern),
            func.lower(models.Order.compliance_remarks).like(search_pattern),
            cast(models.Order.id, String).like(search_pattern),
            func.lower(models.Order.customer.has(models.Customer.customer_name)).like(search_pattern),
            func.lower(models.Order.product.has(models.Product.product_name)).like(search_pattern)
        )
    ).all()

    for o in orders:
        cust_name = o.customer.customer_name if o.customer else "N/A"
        prod_name = o.product.product_name if o.product else "N/A"
        results.append(schemas.FullSearchResultItem(
            type="order",
            id=str(o.id),
            name=f"Order {o.order_id} (PO: {o.po_number})",
            description=f"ID: {o.id}, Customer: {cust_name}, Product: {prod_name}, Status: {o.status}",
            link=f"/orders/{o.id}"
        ))

    return {"results": results}

@app.patch("/api/products/{sku}/pm-code", response_model=schemas.ProductResponse)
def update_product_pm_code(
    sku: str,
    product_update: schemas.ProductPMCodeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Allow Regulatory, Artwork, and Management departments to update PM code."""
    if current_user.department not in ["Regulatory", "Management", "Artwork"]:
        raise HTTPException(
            status_code=403,
            detail="Only Regulatory, Artwork, or Management can update PM code"
        )
    product = db.query(models.Product).filter(models.Product.sku_code == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    update_data = product_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
        
    db.commit()
    db.refresh(product)
    return product


@app.get("/api/products/pm-requests", response_model=List[schemas.PMCodeRequestResponse])
def get_pm_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.PMCodeRequest).order_by(models.PMCodeRequest.updated_at.desc()).all()

@app.post("/api/products/{sku}/pm-requests", response_model=schemas.PMCodeRequestResponse)
def create_pm_request(
    sku: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    product = db.query(models.Product).filter(models.Product.sku_code == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if current_user.department != "Regulatory":
        raise HTTPException(status_code=403, detail="Only Regulatory department can request PM Code")
    
    request = db.query(models.PMCodeRequest).filter(
        models.PMCodeRequest.product_sku == sku
    ).order_by(models.PMCodeRequest.created_at.desc()).first()
    
    if not request or request.status == "APPROVED":
        request = models.PMCodeRequest(
            product_sku=sku,
            status="PENDING_ARTWORK",
            current_primary_pm_code="",
            current_secondary_pm_code="",
            current_leaf_pm_code=""
        )
        db.add(request)
        db.flush()
        
        transaction = models.PMCodeTransaction(
            request_id=request.id,
            from_state=None,
            to_state="PENDING_ARTWORK",
            action_by_dept="Regulatory",
            action_by_user_id=current_user.id,
            remarks="PM Code requested from Artwork team"
        )
        db.add(transaction)
    else:
        old_status = request.status
        request.status = "PENDING_ARTWORK"
        request.updated_at = datetime.utcnow()
        transaction = models.PMCodeTransaction(
            request_id=request.id,
            from_state=old_status,
            to_state="PENDING_ARTWORK",
            action_by_dept="Regulatory",
            action_by_user_id=current_user.id,
            remarks="PM Code requested from Artwork team"
        )
        db.add(transaction)
            
    db.commit()
    db.refresh(request)
    return request

@app.post("/api/products/pm-requests/{request_id}/submit-artwork", response_model=schemas.PMCodeRequestResponse)
def submit_artwork_pm_code(
    request_id: int,
    data: schemas.PMCodeArtworkSubmit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Artwork":
        raise HTTPException(status_code=403, detail="Only Artwork department can submit PM Code for review")

    request = db.query(models.PMCodeRequest).filter(models.PMCodeRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="PM Code Request not found")
    
    if request.status != "PENDING_ARTWORK":
        raise HTTPException(status_code=400, detail="PM Code Request is not in PENDING_ARTWORK status")

    old_status = request.status
    request.current_primary_pm_code = data.primary_pm_code
    request.current_secondary_pm_code = data.secondary_pm_code
    request.current_leaf_pm_code = data.leaf_pm_code
    request.status = "AWAITING_REGULATORY_APPROVAL"
    request.updated_at = datetime.utcnow()

    transaction = models.PMCodeTransaction(
        request_id=request.id,
        from_state=old_status,
        to_state=request.status,
        action_by_dept="Artwork",
        action_by_user_id=current_user.id,
        primary_pm_code=data.primary_pm_code,
        secondary_pm_code=data.secondary_pm_code,
        leaf_pm_code=data.leaf_pm_code,
        remarks=data.remarks,
        created_at=datetime.utcnow(),
        response_time_days=0.0 # This will be calculated by regulatory later.
    )
    db.add(transaction)
    db.commit()
    db.refresh(request)
    return request

@app.post("/api/products/pm-requests/{request_id}/decide", response_model=schemas.PMCodeRequestResponse)
def decide_pm_code(
    request_id: int,
    data: schemas.PMCodeDecision,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Regulatory":
        raise HTTPException(status_code=403, detail="Only Regulatory department can make decisions on PM Code")
    
    request = db.query(models.PMCodeRequest).filter(models.PMCodeRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="PM Code Request not found")
    
    if request.status != "AWAITING_REGULATORY_APPROVAL":
        raise HTTPException(status_code=400, detail="Request is not awaiting regulatory approval")
    
    last_tx = db.query(models.PMCodeTransaction).filter(
        models.PMCodeTransaction.request_id == request.id
    ).order_by(models.PMCodeTransaction.created_at.desc()).first()
    
    now = datetime.utcnow()
    response_time_days = 0.0
    if last_tx:
        time_diff = now - last_tx.created_at
        response_time_days = round(time_diff.total_seconds() / 86400.0, 2)
    
    old_status = request.status
    if data.decision == "ACCEPT":
        request.status = "APPROVED"
        product = db.query(models.Product).filter(models.Product.sku_code == request.product_sku).first()
        if product:
            if data.primary_pm_code is not None:
                product.primary_pm_code = data.primary_pm_code
                request.current_primary_pm_code = data.primary_pm_code
            else:
                product.primary_pm_code = request.current_primary_pm_code

            if data.secondary_pm_code is not None:
                product.secondary_pm_code = data.secondary_pm_code
                request.current_secondary_pm_code = data.secondary_pm_code
            else:
                product.secondary_pm_code = request.current_secondary_pm_code

            if data.leaf_pm_code is not None:
                product.leaf_pm_code = data.leaf_pm_code
                request.current_leaf_pm_code = data.leaf_pm_code
            else:
                product.leaf_pm_code = request.current_leaf_pm_code

            if data.artwork_status:
                product.artwork_status = data.artwork_status
            else:
                product.artwork_status = "Available"

            db.add(product)
    else:
        request.status = "PENDING_ARTWORK"
    
    request.updated_at = now
    
    transaction = models.PMCodeTransaction(
        request_id=request.id,
        from_state=old_status,
        to_state=request.status,
        action_by_dept="Regulatory",
        action_by_user_id=current_user.id,
        primary_pm_code=request.current_primary_pm_code,
        secondary_pm_code=request.current_secondary_pm_code,
        leaf_pm_code=request.current_leaf_pm_code,
        remarks=data.remarks,
        created_at=now,
        response_time_days=response_time_days
    )
    db.add(transaction)
    db.commit()
    db.refresh(request)
    return request

# ==================== MASTER DATA - REGISTRATIONS ====================

@app.post("/api/registrations", response_model=schemas.RegistrationResponse)
def create_registration(
    registration_request: schemas.RegistrationCreateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Find the country by name
    country = db.query(models.Country).filter(models.Country.name == registration_request.country).first()
    if not country:
        raise HTTPException(status_code=404, detail=f"Country '{registration_request.country}' not found")

    # Check if a registration for this country and SKU already exists
    existing_registration = db.query(models.Registration).filter(
        models.Registration.country_id == country.id,
        models.Registration.sku == registration_request.sku
    ).first()

    if existing_registration:
        # Automatically update existing registration instead of creating a duplicate
        existing_registration.registration_number = registration_request.registration_number
        existing_registration.registration_status = registration_request.registration_status
        existing_registration.registration_issue_date = registration_request.registration_issue_date
        existing_registration.registration_expiry_date = registration_request.registration_expiry_date
        existing_registration.remarks = registration_request.remarks
        db.commit()
        db.refresh(existing_registration)
        return existing_registration
    
    # Create the registration with the resolved country_id
    db_registration = models.Registration(
        country_id=country.id,
        sku=registration_request.sku,
        registration_number=registration_request.registration_number,
        registration_status=registration_request.registration_status,
        registration_issue_date=registration_request.registration_issue_date,
        registration_expiry_date=registration_request.registration_expiry_date,
        remarks=registration_request.remarks
    )

    db.add(db_registration)
    db.commit()
    db.refresh(db_registration)
    return db_registration

@app.get("/api/registrations", response_model=List[schemas.RegistrationResponse])
def get_registrations(
    skip: int = 0,
    limit: int = 20,
    country_id: Optional[int] = None,
    sku: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Registration).options(joinedload(models.Registration.product), joinedload(models.Registration.country))
    if country_id:
        query = query.filter(models.Registration.country_id == country_id)
    if sku:
        query = query.filter(models.Registration.sku == sku)
    registrations = query.offset(skip).limit(limit).all()
    return registrations

@app.put("/api/registrations/{registration_id}", response_model=schemas.RegistrationResponse)
def update_registration(
    registration_id: int,
    registration_request: schemas.RegistrationCreateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_registration = db.query(models.Registration).filter(models.Registration.id == registration_id).first()
    if not db_registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    db_registration.registration_number = registration_request.registration_number
    db_registration.registration_status = registration_request.registration_status
    db_registration.registration_issue_date = registration_request.registration_issue_date
    db_registration.registration_expiry_date = registration_request.registration_expiry_date
    db_registration.remarks = registration_request.remarks

    db.commit()
    db.refresh(db_registration)
    return db_registration


DEFAULT_COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Argentina", "Australia", "Austria", "Bangladesh", "Belgium", "Brazil", 
    "Cambodia", "Canada", "Chile", "China", "Colombia", "Denmark", "Egypt", "Ethiopia", "France", "Germany", 
    "Ghana", "Greece", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Japan", "Jordan", 
    "Kenya", "Korea (South)", "Kuwait", "Malaysia", "Mexico", "Myanmar", "Nepal", "Netherlands", "New Zealand", 
    "Nigeria", "Norway", "Oman", "Pakistan", "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Russia", 
    "Saudi Arabia", "Singapore", "South Africa", "Spain", "Sri Lanka", "Sudan", "Sweden", "Switzerland", 
    "Taiwan", "Tanzania", "Thailand", "Turkey", "UAE", "Uganda", "Ukraine", "United Kingdom", "United States", 
    "Uzbekistan", "Vietnam", "Zambia", "Zimbabwe"
]



@app.get("/api/countries", response_model=List[schemas.Country])
def get_countries(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Retrieve all countries from the database."""
    countries = db.query(models.Country).order_by(models.Country.name).all()
    return countries

@app.get("/api/customers/by-country/{country_id}", response_model=List[schemas.CustomerResponse])
def get_customers_by_country_id(
    country_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Retrieve customers by country ID."""
    customers = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(models.Customer.country_id == country_id).order_by(models.Customer.customer_name).all()
    return customers





@app.get("/api/registrations/by-sku", response_model=List[schemas.RegistrationResponse])
def get_registrations_by_sku(
    sku: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return all registrations for a given SKU code so frontend can populate registration number dropdown."""
    registrations = (
        db.query(models.Registration)
        .filter(models.Registration.sku == sku)
        .order_by(models.Registration.country_id)
        .all()
    )
    return registrations

@app.get("/api/debug/registrations", response_model=List[schemas.RegistrationResponse])
def debug_registrations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Debug endpoint to return all registrations."""
    registrations = db.query(models.Registration).all()
    print(f"DEBUG: All Registrations from DB: {registrations}")
    return registrations


@app.get("/api/registrations/by-country-sku", response_model=Optional[schemas.RegistrationResponse])
def get_registration_by_country_and_sku(
    country_id: int,
    sku: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return a single registration for a given country and SKU, if it exists."""
    registration = (
        db.query(models.Registration)
        .options(joinedload(models.Registration.product), joinedload(models.Registration.country))
        .filter(models.Registration.country_id == country_id)
        .filter(models.Registration.sku == sku)
        .first()
    )
    if not registration:
        return None 
    return registration

@app.post("/api/registrations/{registration_id}/upload")
def upload_registration_certificate(
    registration_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    registration = db.query(models.Registration).filter(models.Registration.id == registration_id).first()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    
    # Save file
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"cert_{uuid.uuid4().hex}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    registration.certificate_path = unique_filename
    db.commit()
    
    return {"filename": unique_filename, "path": file_path}

# ==================== MASTER DATA - CUSTOMERS ====================

@app.get("/api/customers", response_model=List[schemas.CustomerResponse])
def get_customers(
    skip: int = 0,
    limit: int = 20,
    country_id: Optional[int] = None,
    product_sku: Optional[str] = None,
    product_name: Optional[str] = None,

    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    query = db.query(models.Customer).options(joinedload(models.Customer.country))

    if country_id:
        query = query.filter(models.Customer.country_id == country_id)

    if product_sku or product_name:

        # If a country_id is provided, filter products by that country as well
        if country_id:
            subquery = subquery.join(models.Customer, models.Product.customer == models.Customer.customer_name)
            subquery = subquery.filter(models.Customer.country_id == country_id)

        matching_customer_names = [c[0] for c in subquery.all()]
        if matching_customer_names:
            query = query.filter(models.Customer.customer_name.in_(matching_customer_names))
        else:
            return [] # No products match, so no customers to return

    customers = query.offset(skip).limit(limit).all()
    return customers

@app.get("/api/debug/customers", response_model=List[schemas.CustomerResponse])
def debug_get_customers(
    country_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Customer).options(joinedload(models.Customer.country))
    if country_id:
        query = query.filter(models.Customer.country_id == country_id)
    customers = query.all()
    return customers

@app.post("/api/customers", response_model=schemas.CustomerResponse)
def create_customer(
    customer: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    db_customer = models.Customer(**customer.dict(exclude_unset=True))
    


    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

@app.get("/api/customers/{customer_id}/products", response_model=List[schemas.ProductResponse])
def get_products_for_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return products for the given customer's country and customer name."""
    customer = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Fetch products that match the customer's country_id and customer name
    products = db.query(models.Product).options(joinedload(models.Product.country)).filter(
        models.Product.country_id == customer.country_id,
        models.Product.customer == customer.customer_name,
        models.Product.is_active == True
    ).all()
    
    # Fallback to country matching products if no customer-specific products are found
    if not products:
        products = db.query(models.Product).options(joinedload(models.Product.country)).filter(
            models.Product.country_id == customer.country_id,
            models.Product.is_active == True
        ).all()
        
    return products


@app.get("/api/customers/{customer_id}", response_model=schemas.CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    customer = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    return customer

@app.put("/api/customers/{customer_id}", response_model=schemas.CustomerResponse)
def update_customer(
    customer_id: int,
    customer_update: schemas.CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    db_customer = db.query(models.Customer).options(joinedload(models.Customer.country)).filter(models.Customer.id == customer_id).first()
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    update_data = customer_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_customer, key, value)

    db_customer.updated_at = datetime.utcnow()
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer



# ==================== ORDER MANAGEMENT ====================

def run_compliance_check(order: models.Order, db: Session):
    """Run automatic compliance check on order"""
    issues = []
    
    # Check registration
    registration = db.query(models.Registration).filter(
        models.Registration.country_id == order.country_id,
        models.Registration.sku == order.sku,
        models.Registration.registration_status == "Active"
    ).first()
    
    if not registration:
        issues.append(f"No active registration found for SKU {order.sku} in {order.country.name}")
    elif registration.registration_expiry_date and registration.registration_expiry_date < date.today():
        issues.append(f"Registration expired for SKU {order.sku} in {order.country.name}")
    elif registration.registration_expiry_date and registration.registration_expiry_date < order.requested_delivery_date:
        issues.append(f"Registration expires before delivery date")
    
    # Check artwork
    product = db.query(models.Product).filter(models.Product.sku_code == order.sku).first()
    if not product or product.artwork_status != "Available":
        issues.append(f"Artwork not available for SKU {order.sku}")
    
    # Check customer agreement
    customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
    if customer and customer.agreement_status != "Active":
        issues.append(f"Customer agreement not active")
    
    # Check batch size
    if product and product.standard_batch_size:
        if product.moq is not None and order.quantity < product.moq:    
            issues.append(f"Order quantity below MOQ ({product.moq})")
    
    if issues:
        return {
            "status": "FAILED",
            "remarks": "; ".join(issues),
            "issues": issues
        }
    
    return {
        "status": "PASSED",
        "remarks": "All compliance checks passed",
        "issues": []
    }

def get_responsible_department(issue: str) -> str:
    """Determine responsible department based on issue"""
    issue_lower = issue.lower()
    if "registration" in issue_lower:
        return "Regulatory"
    elif "artwork" in issue_lower:
        return "Artwork"
    elif "agreement" in issue_lower:
        return "Finance"
    elif "batch" in issue_lower or "moq" in issue_lower:
        return "SCM"
    return "Exports"

def create_milestones(order: models.Order, db: Session):
    """Create default milestones for order"""
    milestones = [
        # Artwork milestones
        {"name": "Artwork Requested", "category": "Artwork"},
        {"name": "Artwork Approved", "category": "Artwork"},
        {"name": "PO Released", "category": "Artwork"},
        {"name": "PM Received", "category": "Artwork"},
        # SCM milestones
        {"name": "Production Planned", "category": "SCM"},
        {"name": "Production Started", "category": "SCM"},
        {"name": "Production Completed", "category": "SCM"},
        {"name": "Batch Released", "category": "SCM"},
        # Logistics milestones
        {"name": "Ready for Shipment", "category": "Logistics"},
        {"name": "Freight Booked", "category": "Logistics"},
        {"name": "Shipped", "category": "Logistics"},
        {"name": "Delivered", "category": "Logistics"}
    ]
    
    for m in milestones:
        milestone = models.Milestone(
            order_id=order.id,
            name=m["name"],
            category=m["category"], # Include category
            status="PENDING"
        )
        db.add(milestone)

def log_audit(db: Session, order_id: int, user_id: int, action: str, 
              prev_status: Optional[str], new_status: Optional[str], 
              remarks: str, ip_address: Optional[str] = None):
    """Log audit trail"""
    audit = models.AuditLog(
        order_id=order_id,
        user_id=user_id,
        action=action,
        previous_status=prev_status,
        new_status=new_status,
        remarks=remarks,
        ip_address=ip_address
    )
    db.add(audit)
    db.flush()
    db.refresh(audit)

def get_user_approval_department(
    user_department: str,
    all_approvals: List[models.OrderApproval]
) -> Optional[models.ApprovalDepartment]:
    """
    Determines the specific ApprovalDepartment enum for a user based on their department
    and the current pending approval in the sequence.
    User departments from auth are TitleCase (e.g. 'Regulatory', 'Finance').
    ApprovalDepartment enum values are UPPERCASE (e.g. 'REGULATORY', 'FINANCE').
    """
    if user_department == "SCM":
        # SCM is handled separately as an override, not part of sequential flow
        return None

    # Find the next pending approval in the sequence
    next_pending_approval = None
    for approval in all_approvals:
        if approval.status == models.ApprovalStatus.PENDING.value:
            next_pending_approval = approval
            break

    if not next_pending_approval:
        return None  # No pending approvals

    # For Exports department, we need to distinguish between initial and final
    if user_department.upper() == "EXPORTS":
        if next_pending_approval.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value:
            return models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL
        elif next_pending_approval.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value:
            return models.ApprovalDepartment.EXPORTS_MANAGER_FINAL
        else:
            return None  # Exports user is not responsible for current pending approval
    else:
        # For other departments, match case-insensitively
        # e.g. user_department='Regulatory' matches ad.value='REGULATORY'
        for ad in models.ApprovalDepartment:
            if ad.value.upper() == user_department.upper():
                return ad
    return None


@app.get("/api/orders", response_model=List[schemas.OrderResponse])
def get_orders(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    product_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Get orders based on the logged-in user's department.

    SCM:
        PNS user -> orders.order_type = PNS
        PP user  -> orders.order_type = PP

    Artwork:
        Only pending artwork orders.

    product_type:
        Filters orders.category.
    """

    logging.debug("=" * 70)
    logging.debug("GET ORDERS")
    logging.debug(
        f"Employee       : {current_user.employee_id}"
    )
    logging.debug(
        f"Department     : {current_user.department}"
    )
    logging.debug(
        f"Role           : {current_user.role}"
    )
    logging.debug(
        f"SCM Order Type : "
        f"{getattr(current_user, 'order_type', None)}"
    )
    logging.debug(
        f"Product Type   : {product_type}"
    )
    logging.debug(
        f"Status         : {status}"
    )
    logging.debug("=" * 70)

    # ============================================================
    # BASE QUERY
    # ============================================================

    query = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.product),
        joinedload(models.Order.country),

        selectinload(
            models.Order.approvals
        ).joinedload(
            models.OrderApproval.approver
        ),

        selectinload(models.Order.milestones),
        selectinload(models.Order.alerts)
    )

    # ============================================================
    # ARTWORK FILTER
    # ============================================================

    if current_user.department == "Artwork":

        logging.debug(
            f"Artwork user {current_user.employee_id} "
            f"-> showing pending artwork orders"
        )

        query = query.filter(
            models.Order.status ==
            models.OrderStatus.PENDING_ARTWORK_PROCESS.value
        )

    # ============================================================
    # PRODUCT TYPE FILTER
    # ============================================================

    if product_type:

        requested_type = (
            product_type
            .strip()
            .upper()
        )

        logging.debug(
            f"Product category filter -> "
            f"{requested_type}"
        )

        # Product Type means the Order.category value.
        #
        # Example:
        # Drug
        # Nutra
        #
        # It is NOT PNS / PP.

        query = query.filter(
            func.upper(
                func.trim(
                    models.Order.category
                )
            ) == requested_type
        )

    # ============================================================
    # SCM FILTER
    # ============================================================

    elif current_user.department == "SCM":

        scm_type = (
            getattr(
                current_user,
                "order_type",
                None
            ) or ""
        ).strip().upper()

        logging.debug(
            f"SCM filter -> "
            f"employee={current_user.employee_id}, "
            f"SCM order_type={repr(scm_type)}"
        )

        # --------------------------------------------------------
        # PNS SCM
        # --------------------------------------------------------

        if scm_type == "PNS":

            logging.debug(
                f"SCM PNS user "
                f"{current_user.employee_id} "
                f"-> filtering Order.order_type = PNS"
            )

            query = query.filter(
                func.upper(
                    func.trim(
                        models.Order.order_type
                    )
                ) == "PNS"
            )

        # --------------------------------------------------------
        # PP SCM
        # --------------------------------------------------------

        elif scm_type == "PP":

            logging.debug(
                f"SCM PP user "
                f"{current_user.employee_id} "
                f"-> filtering Order.order_type = PP"
            )

            query = query.filter(
                func.upper(
                    func.trim(
                        models.Order.order_type
                    )
                ) == "PP"
            )

        # --------------------------------------------------------
        # INVALID SCM TYPE
        # --------------------------------------------------------

        else:

            logging.warning(
                f"Invalid SCM order_type for "
                f"{current_user.employee_id}: "
                f"{repr(scm_type)}"
            )

            # Never expose all orders when SCM type
            # is missing or invalid.

            query = query.filter(False)

    # ============================================================
    # STATUS FILTER
    # ============================================================

    if status:

        requested_status = status.strip()

        logging.debug(
            f"Status filter -> "
            f"{requested_status}"
        )

        query = query.filter(
            models.Order.status == requested_status
        )

    # ============================================================
    # FETCH ORDERS
    # ============================================================

    logging.debug("=" * 70)
    logging.debug("FINAL ORDER QUERY")
    logging.debug(
        f"Employee       : {current_user.employee_id}"
    )
    logging.debug(
        f"Department     : {current_user.department}"
    )
    logging.debug(
        f"SCM Order Type : "
        f"{getattr(current_user, 'order_type', None)}"
    )
    logging.debug(
        f"Product Type   : {product_type}"
    )
    logging.debug(
        f"Status         : {status}"
    )
    logging.debug("=" * 70)

    orders = (
        query
        .order_by(
            models.Order.created_at.desc()
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    # ============================================================
    # DEBUG RESULTS
    # ============================================================

    logging.debug(
        f"Orders returned for "
        f"{current_user.employee_id}: "
        f"{len(orders)}"
    )

    for order in orders:

        logging.debug(
            f"ORDER -> "
            f"id={order.id}, "
            f"order_id={order.order_id}, "
            f"order_type={getattr(order, 'order_type', None)}, "
            f"sku={order.sku}, "
            f"status={order.status}"
        )

    return orders


@app.post("/api/orders", response_model=schemas.OrderResponse)
def create_order(
    order: schemas.OrderCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Only Regulatory or Exports department can create orders
    if current_user.department not in ["Regulatory", "Exports"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Regulatory or Exports department can create orders"
        )

    # Generate unique Order ID
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    
    # Auto-generate order_number
    customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
    country_obj = db.query(models.Country).filter(models.Country.id == order.country_id).first()
    country_prefix = country_obj.name[:3].upper() if country_obj and country_obj.name else "XXX"
    customer_prefix = customer.customer_name[:3].upper() if customer and customer.customer_name else "XXX"
    current_time = datetime.now()
    order_number = f"{country_prefix}-{customer_prefix}-{current_time.strftime('%m%Y')}"
    order_data = order.dict()

    # If PO number is provided, append count
    if order.po_number:
        base_po_number = order.po_number  # Assuming po_number comes in as "MYA-LOY-07/26"
        
        import re
        if re.search(r'-\d+$', base_po_number):
            # It already has the serial suffix (e.g. -1), keep it as is
            order_data['po_number'] = base_po_number
        else:
            # Count existing orders with the same base PO number
            existing_orders_count = db.query(models.Order).filter(models.Order.po_number.like(f"{base_po_number}-%")).count()
            
            # Increment count for the new order
            new_po_number = f"{base_po_number}-{existing_orders_count + 1}"
            order_data['po_number'] = new_po_number

        
    print(f"Original PO number from frontend: {order_data.get('po_number')}")
    order_data['order_number'] = order_number
    # Auto-compute total quantity from sales + free
    order_data['quantity'] = order_data.get('sales_quantity', 0) + order_data.get('free_quantity', 0)
    db_order = models.Order(
        order_id=order_id,
        **order_data
    )
    db.add(db_order)
    db.flush()  # Get order.id
    
    # Run compliance check
    compliance_result = run_compliance_check(db_order, db)
    db_order.compliance_status = compliance_result["status"]
    db_order.compliance_remarks = compliance_result["remarks"]
    
    if compliance_result["status"] == "FAILED":
        db_order.status = models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value
        # Create alerts for failed checks
        for issue in compliance_result["issues"]:
            alert = models.Alert(
                alert_type="COMPLIANCE_ISSUE",
                order_id=db_order.id,
                message=issue,
                priority="HIGH",
                department=get_responsible_department(issue)
            )
            db.add(alert)
    else:
        db_order.status = models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value

    # Create approval records with sequential workflow
    # Approval Flow:
    # 1. Exports Manager (Initial Review) — reviews order submitted by Regulatory.
    # 2. Regulatory — reviews and approves after Exports Manager's initial check.
    # 3. Finance — approves after Regulatory.
    # 4. Exports Manager (Final Check) — final sign-off before order finalization.
    approval_sequence = [
        (models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL, 1),
        (models.ApprovalDepartment.REGULATORY, 2),
        (models.ApprovalDepartment.FINANCE, 3),
        (models.ApprovalDepartment.EXPORTS_MANAGER_FINAL, 4),
    ]
    for dept_enum, seq in approval_sequence:
        approval = models.OrderApproval(
            order_id=db_order.id,
            department=dept_enum.value,
            status=models.ApprovalStatus.PENDING.value,
            sequence=seq
        )
        db.add(approval)
    
    # Create initial milestones
    ensure_order_milestones(db_order.id, db)
    
    # Log audit
    log_audit(db, db_order.id, current_user.id, "ORDER_CREATED", None, "NEW ORDER", 
              "Order created and compliance check run", request.client.host)
    
    db.commit()
    db.refresh(db_order)
    return db_order

def ensure_order_milestones(order_id: int, db: Session):
    default_milestones = [
        ("PO Released", "Artwork"),
        ("PM Received", "Artwork"),
        ("Production Planned", "SCM"),
        ("Production Started", "SCM"),
        ("Production Completed", "SCM"),
        ("Batch Released", "SCM"),
        ("Ready for Shipment", "Logistics"),
        ("Freight Booked", "Logistics"),
        ("Shipped", "Logistics"),
        ("Delivered", "Logistics")
    ]
    
    try:
        existing = db.query(models.Milestone).filter(models.Milestone.order_id == order_id).all()
        
        # 1. Clean up invalid/nameless milestones & rename legacy PM Procurement Released
        for m in existing:
            if not m.name or not str(m.name).strip():
                db.delete(m)
            elif m.name == "PM Procurement Released":
                m.name = "PO Released"
        db.commit()
        
        # 2. Deduplicate by milestone name
        existing = db.query(models.Milestone).filter(models.Milestone.order_id == order_id).all()
        existing_map = {}
        dupes_to_delete = []
        
        for m in existing:
            name_key = str(m.name).strip()
            if name_key in existing_map:
                prev = existing_map[name_key]
                if m.status == 'COMPLETED' and prev.status != 'COMPLETED':
                    dupes_to_delete.append(prev)
                    existing_map[name_key] = m
                else:
                    dupes_to_delete.append(m)
            else:
                existing_map[name_key] = m
                
        if dupes_to_delete:
            for d in dupes_to_delete:
                db.delete(d)
            db.commit()
            
        # 3. Add any missing default milestones safely
        added_count = 0
        for m_name, m_cat in default_milestones:
            if m_name not in existing_map:
                new_m = models.Milestone(
                    order_id=order_id,
                    name=m_name,
                    category=m_cat,
                    status="PENDING"
                )
                db.add(new_m)
                added_count += 1
        
        if added_count > 0:
            db.commit()
            logging.info(f"Initialized {added_count} missing milestones for Order #{order_id}")
        else:
            logging.info(f"Milestones already fully initialized for Order #{order_id}")
    except Exception as e:
        db.rollback()
        logging.error(f"Milestone initialization failed for Order #{order_id}: {e}")
        raise e


def ensure_order_approvals(order_id: int, db: Session):
    approval_sequence = [
        ("EXPORTS_MANAGER_INITIAL", 1),
        ("REGULATORY", 2),
        ("FINANCE", 3),
        ("EXPORTS_MANAGER_FINAL", 4),
    ]
    
    existing = db.query(models.OrderApproval).filter(models.OrderApproval.order_id == order_id).order_by(models.OrderApproval.id.asc()).all()
    seen_depts = {}
    dupes_to_delete = []
    
    for app in existing:
        dept = app.department
        if dept in seen_depts:
            prev = seen_depts[dept]
            if app.status != 'PENDING' and prev.status == 'PENDING':
                dupes_to_delete.append(prev)
                seen_depts[dept] = app
            else:
                dupes_to_delete.append(app)
        else:
            seen_depts[dept] = app
            
    if dupes_to_delete:
        for d in dupes_to_delete:
            db.delete(d)
        db.commit()
        
    for dept, correct_seq in approval_sequence:
        if dept in seen_depts:
            app = seen_depts[dept]
            if app.sequence != correct_seq:
                app.sequence = correct_seq
        else:
            new_app = models.OrderApproval(
                order_id=order_id,
                department=dept,
                status=models.ApprovalStatus.PENDING.value,
                sequence=correct_seq
            )
            db.add(new_app)
    db.commit()


@app.get("/api/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Ensure exactly 4 unique approvals exist (1: Exports Initial, 2: Regulatory, 3: Finance, 4: Exports Final)
    ensure_order_approvals(order_id, db)

    # Ensure all 12 default milestones exist with proper names and no duplicates
    ensure_order_milestones(order_id, db)

    order = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.product),
        joinedload(models.Order.country),
        selectinload(models.Order.approvals).joinedload(models.OrderApproval.approver),
        selectinload(models.Order.milestones),
        selectinload(models.Order.alerts)
    ).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order


@app.put("/api/orders/{order_id}", response_model=schemas.OrderResponse)
def update_order(
    order_id: int,
    order_update: schemas.OrderCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Exports" or current_user.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Exports Team members can edit orders"
        )
        
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    # Check if order can be edited (no approvals completed yet)
    all_pending = all(a.status == "PENDING" for a in db_order.approvals)
    if not all_pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order cannot be edited after approvals have started"
        )
        
    # Update order fields
    for key, value in order_update.dict().items():
        setattr(db_order, key, value)
        
    # Re-run compliance check
    db.query(models.Alert).filter(
        models.Alert.order_id == db_order.id,
        models.Alert.alert_type == "COMPLIANCE_ISSUE"
    ).delete()
    
    compliance_result = run_compliance_check(db_order, db)
    db_order.compliance_status = compliance_result["status"]
    db_order.compliance_remarks = compliance_result["remarks"]
    
    if compliance_result["status"] == "FAILED":
        db_order.status = "HOLD"
        # Create alerts for failed checks
        for issue in compliance_result["issues"]:
            alert = models.Alert(
                alert_type="COMPLIANCE_ISSUE",
                order_id=db_order.id,
                message=issue,
                priority="HIGH",
                department=get_responsible_department(issue)
            )
            db.add(alert)
    else:
        db_order.status = models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value
        
    # Log audit
    log_audit(db, db_order.id, current_user.id, "ORDER_UPDATED", None, db_order.status,
              "Order details updated and compliance check re-run", request.client.host)
              
    db.commit()
    db.refresh(db_order)
    return db_order

@app.get("/api/orders/{order_id}/can-approve")
def get_can_approve(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    user_dept = current_user.department

    all_approvals = db.query(models.OrderApproval).filter(
        models.OrderApproval.order_id == order_id
    ).order_by(models.OrderApproval.sequence).all()

    # SCM Override Path
    if user_dept == "SCM":
        return {
            "can_approve": True,
            "is_scm_override": True,
            "is_exports_override": False,
            "reason": "SCM Override Available",
            "current_sequence": None,
            "waiting_for": None
        }

    # Find the first PENDING approval in sequence
    next_pending = next((a for a in all_approvals if a.status == models.ApprovalStatus.PENDING.value), None)
    if not next_pending:
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": "Order approvals are completed or finalized",
            "current_sequence": None,
            "waiting_for": None
        }

    # Exports Manager Path
    if user_dept == "Exports":
        if current_user.role != "manager":
            return {
                "can_approve": False,
                "is_scm_override": False,
                "is_exports_override": False,
                "reason": "Only Exports Manager can approve created orders",
                "current_sequence": None,
                "waiting_for": None
            }
        if next_pending.department in [models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value, models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value]:
            return {
                "can_approve": True,
                "is_scm_override": False,
                "is_exports_override": True,
                "reason": None,
                "current_sequence": next_pending.sequence,
                "pending_department": next_pending.department,
                "waiting_for": None
            }
        else:
            return {
                "can_approve": False,
                "is_scm_override": False,
                "is_exports_override": True,
                "reason": f"Waiting for {next_pending.department} approval first",
                "current_sequence": next_pending.sequence,
                "waiting_for": {"department": next_pending.department}
            }

    # Other departments
    user_dept_enum = get_user_approval_department(user_dept, all_approvals)
    if user_dept_enum and next_pending.department == user_dept_enum.value:
        return {
            "can_approve": True,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": None,
            "current_sequence": next_pending.sequence,
            "pending_department": next_pending.department,
            "waiting_for": None
        }

    return {
        "can_approve": False,
        "is_scm_override": False,
        "is_exports_override": False,
        "reason": f"Waiting for {next_pending.department} approval first",
        "current_sequence": next_pending.sequence,
        "waiting_for": {"department": next_pending.department}
    }


@app.put("/api/orders/{order_id}/approve")
def approve_order(
    order_id: int,
    approval_data: schemas.ApprovalDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    logging.debug(f"[{current_user.employee_id}] Approving Order ID: {order_id}")
    logging.debug(f"[{current_user.employee_id}] User Department: {current_user.department}, Role: {current_user.role}")
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    user_dept = current_user.department

    # Resolve decision to its string representation (handles Pydantic enum or string)
    decision_str = approval_data.decision.value if hasattr(approval_data.decision, "value") else approval_data.decision

    # Fetch all approvals for the order to determine the current step
    all_approvals = db.query(models.OrderApproval).filter(
        models.OrderApproval.order_id == order_id
    ).order_by(models.OrderApproval.sequence).all()

    # Exports Manager Override Path
    if user_dept == "Exports":
        if current_user.role != "manager":
            raise HTTPException(
                status_code=403,
                detail="Only Exports Manager can approve created orders"
            )
        exports_pending_approvals = [
            a for a in all_approvals
            if a.status == models.ApprovalStatus.PENDING.value and
               (a.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value or
                a.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value)
        ]
        
        if not exports_pending_approvals:
            logging.debug(f"[{current_user.employee_id}] Exports Manager: No pending Exports Manager approvals found.")
            raise HTTPException(
                status_code=403,
                detail="No pending Exports Manager approvals found for this order to approve."
            )
        
        # Find the earliest Exports Manager approval in sequence to act on
        approval_to_act_on = min(exports_pending_approvals, key=lambda x: x.sequence)

        # Ensure previous approvals before this sequence are completed
        previous_approvals = [a for a in all_approvals if a.sequence < approval_to_act_on.sequence]
        for prev in previous_approvals:
            if prev.status not in [models.ApprovalStatus.APPROVED.value, models.ApprovalStatus.APPROVED_WITH_REMARKS.value]:
                raise HTTPException(
                    status_code=403,
                    detail=f"Cannot approve: {prev.department} has not approved yet."
                )

        # Mark with decision
        approval_to_act_on.status = decision_str
        approval_to_act_on.remarks = f"{approval_data.remarks.strip() if approval_data.remarks else ''}"
        approval_to_act_on.approver_id = current_user.id
        approval_to_act_on.approved_at = datetime.utcnow()

        log_audit(
            db, order_id, current_user.id,
            f"EXPORTS_MANAGER_APPROVAL_SEQ{approval_to_act_on.sequence}",
            order.status, order.status,
            f"Exports Manager approved {approval_to_act_on.department} (seq {approval_to_act_on.sequence}): "
            f"{approval_to_act_on.status} - {approval_to_act_on.remarks}",
            request.client.host
        )

        check_all_approvals(order, db, current_user.id, request.client.host)
        db.commit()
        return {"message": f"Exports Manager has approved {approval_to_act_on.department} successfully."}


    user_dept_enum = get_user_approval_department(user_dept, all_approvals)

    if user_dept_enum is None and user_dept != "SCM": # SCM is handled separately
        logging.debug(f"[{current_user.employee_id}] Normal Approval: User department {user_dept} not part of approval workflow or not their turn.")
        raise HTTPException(status_code=403, detail="Your department is not part of the defined approval workflow or it's not your turn to approve.")

    # ── SCM Override Path ────────────────────────────────────────────────────
    # SCM can approve/reject ANY pending approval on behalf of any department.
    # Remarks are mandatory for an SCM override action.
    if user_dept == "SCM": # SCM department is not part of the sequential approval enum, so handle separately
        if not approval_data.remarks or not approval_data.remarks.strip():
            logging.debug(f"[{current_user.employee_id}] SCM Override: Remarks are mandatory for SCM override.")
            raise HTTPException(
                status_code=400,
                detail="SCM must provide remarks when overriding a department approval."
            )
        
        # SCM must specify which department's approval they are overriding.
        if not approval_data.target_department:
            logging.debug(f"[{current_user.employee_id}] SCM Override: Target department not specified for SCM override.")
            raise HTTPException(
                status_code=400,
                detail="SCM must specify a target department for override."
            )

        # Find the approval for the specified target_department
        approval = next((a for a in all_approvals if a.department == approval_data.target_department), None)
        if not approval:
            logging.debug(f"[{current_user.employee_id}] SCM Override: Approval for target department {approval_data.target_department} not found.")
            raise HTTPException(
                status_code=404,
                detail=f"Approval for department \\'{approval_data.target_department}\\' not found for this order."
            )

        # Mark with decision and flag it as SCM override
        approval.status = decision_str
        approval.remarks = f"[SCM Override] {approval_data.remarks.strip()}"
        approval.approver_id = current_user.id
        approval.approved_at = datetime.utcnow()

        log_audit(
            db, order_id, current_user.id,
            f"SCM_OVERRIDE_APPROVAL_SEQ{approval.sequence}",
            order.status, order.status,
            f"SCM overrode {approval.department} approval (seq {approval.sequence}): "
            f"{approval.status} - {approval_data.remarks}",
            request.client.host
        )

        check_all_approvals(order, db, current_user.id, request.client.host)
        db.commit()
        return {"message": f"SCM has overridden the {approval.department} approval successfully."}

    # ── Normal Approval Path ─────────────────────────────────────────────────
    if user_dept_enum not in [models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL, models.ApprovalDepartment.EXPORTS_MANAGER_FINAL, models.ApprovalDepartment.ARTWORK, models.ApprovalDepartment.REGULATORY, models.ApprovalDepartment.FINANCE]:
         raise HTTPException(
            status_code=403,
            detail="Your department is not authorized to approve orders in this workflow."
        )

    if user_dept_enum in [models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL, models.ApprovalDepartment.EXPORTS_MANAGER_FINAL] and current_user.role != "manager":
        logging.debug(f"[{current_user.employee_id}] Normal Approval: User department is Exports Manager but role is not 'manager'.")
        raise HTTPException(status_code=403, detail="Only Export Manager can approve Exports approvals")

    # Remarks are mandatory for REJECTED decisions
    if decision_str == models.ApprovalStatus.REJECTED.value and not (approval_data.remarks and approval_data.remarks.strip()):
        logging.debug(f"[{current_user.employee_id}] Normal Approval: Remarks are mandatory for rejection.")
        raise HTTPException(
            status_code=400,
            detail="Remarks are mandatory when rejecting an order."
        )

    # Filter approvals relevant to the current user's department and that are pending
    user_pending_approvals = [
        a for a in all_approvals 
        if a.status == models.ApprovalStatus.PENDING.value and a.department == user_dept_enum.value
    ]

    if not user_pending_approvals:
        logging.debug(f"[{current_user.employee_id}] Normal Approval: No pending approval found for user\\'s department {user_dept_enum.value}.")
        raise HTTPException(
            status_code=403,
            detail="No pending approval found for your department for this order."
        )
    
    # Determine the specific approval to act on
    if user_dept_enum == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL:
        approval_to_act_on = next(
            (a for a in user_pending_approvals if a.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value),
            None
        )
    elif user_dept_enum == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL:
        approval_to_act_on = next(
            (a for a in user_pending_approvals if a.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value),
            None
        )
    else:
        # For other departments, there should ideally be only one pending approval at a time
        approval_to_act_on = user_pending_approvals[0]
    
    if not approval_to_act_on:
        logging.debug(f"[{current_user.employee_id}] Normal Approval: No pending approval found for specific role in department {user_dept_enum.value}.")
        raise HTTPException(
            status_code=403,
            detail="No pending approval found for your specific role in this department."
        )

    current_sequence = approval_to_act_on.sequence
    previous_approvals = [a for a in all_approvals if a.sequence < current_sequence]
    for prev_approval in previous_approvals:
        if prev_approval.status not in [
            models.ApprovalStatus.APPROVED.value,
            models.ApprovalStatus.APPROVED_WITH_REMARKS.value,
            models.ApprovalStatus.REJECTED.value
        ]:
            logging.debug(f"[{current_user.employee_id}] Normal Approval: Cannot approve due to pending previous approval from {prev_approval.department}.")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Cannot approve: {prev_approval.department} (sequence {prev_approval.sequence}) "
                    f"has not approved yet. Current status: {prev_approval.status}"
                )
            )

    # Apply decision to the identified approval
    approval_to_act_on.status = decision_str
    approval_to_act_on.remarks = approval_data.remarks.strip() if approval_data.remarks else None
    approval_to_act_on.approver_id = current_user.id
    approval_to_act_on.approved_at = datetime.utcnow()

    # Handle Regulatory specific actions
    if current_user.department == "Regulatory" and decision_str == models.ApprovalStatus.APPROVED.value:
        if not approval_data.regulatory_action:
            raise HTTPException(status_code=400, detail="Regulatory action is required for Regulatory approval.")
        
        # Log the specific regulatory action
        log_audit(
            db, order_id, current_user.id,
            f"REGULATORY_ACTION_{approval_data.regulatory_action}",
            order.status, order.status,
            f"Regulatory department approved with action: {approval_data.regulatory_action} - {approval_data.remarks or ''}",
            request.client.host
        )

        if approval_data.regulatory_action == "SEND_TO_ARTWORK":
            order.status = models.OrderStatus.PENDING_ARTWORK_PROCESS.value
        elif approval_data.regulatory_action == "APPROVE_TO_FINANCE":
            # This will naturally lead to the next approval in check_all_approvals
            pass # Status update will be handled by check_all_approvals
    
    # Log audit for the general approval/rejection
    log_audit(
        db, order_id, current_user.id,
        f"ORDER_APPROVAL_SEQ{approval_to_act_on.sequence}",
        order.status, order.status, # Status might change below in check_all_approvals
        f"{user_dept_enum.value} department {decision_str.lower()}: {approval_data.remarks or ''}",
        request.client.host
    )

    check_all_approvals(order, db, current_user.id, request.client.host)
    db.commit()
    return {"message": f"{user_dept_enum.value} has {decision_str.lower()} the order successfully."}

    logging.debug(f"[{current_user.employee_id}] Can approve: True, Reason: All checks passed.")
    return {"can_approve": True, "is_scm_override": False, "is_exports_override": False, "reason": None, "current_sequence": current_sequence, "waiting_for": None}


def check_all_approvals(order: models.Order, db: Session, user_id: int, ip_address: Optional[str]):
    """Check if all departments have approved and update order status accordingly"""
    approvals = db.query(models.OrderApproval).filter(models.OrderApproval.order_id == order.id).order_by(models.OrderApproval.sequence).all()

    prev_order_status = order.status

    # Check for any rejections first
    if any(a.status == models.ApprovalStatus.REJECTED.value for a in approvals):
        order.status = models.OrderStatus.REJECTED.value
    else:
        # Determine the highest sequence number that has been approved
        last_approved_sequence = 0
        for approval in approvals:
            if approval.status in [models.ApprovalStatus.APPROVED.value, models.ApprovalStatus.APPROVED_WITH_REMARKS.value]:
                last_approved_sequence = max(last_approved_sequence, approval.sequence)
            else:
                # If we encounter a pending approval, we stop here as the flow is sequential
                break
        
        # Find the next pending approval in the sequence (if any)
        next_pending_approval = None
        for approval in approvals:
            if approval.sequence > last_approved_sequence and approval.status == models.ApprovalStatus.PENDING.value:
                next_pending_approval = approval
                break

        if next_pending_approval:
            # Set order status based on the next pending department
            if next_pending_approval.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value:
                order.status = models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value
            elif next_pending_approval.department == models.ApprovalDepartment.REGULATORY.value:
                # Regulatory step: comes after Exports Manager initial approval
                order.status = models.OrderStatus.PENDING_REGULATORY_REVISION.value
            elif next_pending_approval.department == models.ApprovalDepartment.ARTWORK.value:
                order.status = models.OrderStatus.PENDING_ARTWORK_PROCESS.value
            elif next_pending_approval.department == models.ApprovalDepartment.FINANCE.value:
                order.status = models.OrderStatus.PENDING_FINANCE_APPROVAL.value
            elif next_pending_approval.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value:
                order.status = models.OrderStatus.PENDING_FINAL_EXPORTS_CHECK.value
        else:
            # If no pending approvals and no rejections, then all are approved
            order.status = models.OrderStatus.ORDER_FINALIZED.value
            order.accepted_at = datetime.utcnow()

    if prev_order_status != order.status:
        log_audit(db, order.id, user_id, "ORDER_STATUS_CHANGE", prev_order_status, order.status,
                  f"Status updated due to approval process: {prev_order_status} -> {order.status}", ip_address)

@app.put("/api/orders/{order_id}/milestone/{milestone_name}")
def update_milestone(
    order_id: int,
    milestone_name: str,
    milestone_update: schemas.MilestoneUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    milestone = db.query(models.Milestone).filter(
        models.Milestone.order_id == order_id,
        models.Milestone.name == milestone_name
    ).first()

    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    user_dept = current_user.department
    print(f"DEBUG: User Department: {current_user.department}")


    prev_status = milestone.status

    if milestone_update.status:
        milestone.status = milestone_update.status
    if milestone_update.target_date is not None:
        if milestone.target_date != milestone_update.target_date:
            old_val = str(milestone.target_date) if milestone.target_date else None
            new_val = str(milestone_update.target_date) if milestone_update.target_date else None
            hist = models.MilestoneHistory(
                milestone_id=milestone.id,
                change_type="TARGET_DATE_UPDATE",
                old_value=old_val,
                new_value=new_val,
                changed_by_user_id=current_user.id
            )
            db.add(hist)
        milestone.target_date = milestone_update.target_date
    if milestone_update.actual_date:
        milestone.actual_date = milestone_update.actual_date
    if milestone_update.remarks:
        milestone.remarks = milestone_update.remarks

    milestone.updated_at = datetime.utcnow()

    # Check for delays
    if milestone.status == "COMPLETED" and milestone.target_date:
        if milestone.actual_date and milestone.actual_date > milestone.target_date:
            milestone.status = "DELAYED"
            create_delay_alert(order, milestone, db)

    # Update order status based on milestones
    update_order_status_from_milestones(order, db, current_user.id, request.client.host)

    log_audit(
        db, order_id, current_user.id, "MILESTONE_UPDATE",
        prev_status, milestone.status,
        f"Milestone '{milestone_name}' updated to {milestone.status} by {user_dept}",
        request.client.host
    )

    db.commit()
    return {"message": "Milestone updated successfully"}

@app.get("/api/milestones/{milestone_id}/history", response_model=List[schemas.MilestoneHistoryResponse])
def get_milestone_history(
    milestone_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Check if the milestone itself exists
    milestone_exists = db.query(models.Milestone).filter(models.Milestone.id == milestone_id).first()
    if not milestone_exists:
        raise HTTPException(status_code=404, detail="Milestone not found")

    history_entries = db.query(models.MilestoneHistory).options(
        joinedload(models.MilestoneHistory.changed_by_user)
    ).filter(models.MilestoneHistory.milestone_id == milestone_id).order_by(models.MilestoneHistory.changed_at.desc()).all()
    # Explicitly construct MilestoneHistoryResponse objects
    response_history = []
    for entry in history_entries:
        user_response = None
        if entry.changed_by_user:
            user_response = schemas.UserResponse(
                id=entry.changed_by_user.id,
                employee_id=entry.changed_by_user.employee_id,
                name=entry.changed_by_user.name,
                email=entry.changed_by_user.email,
                department=entry.changed_by_user.department,
                role=entry.changed_by_user.role,
                is_active=entry.changed_by_user.is_active,
                created_at=entry.changed_by_user.created_at,
                last_login=entry.changed_by_user.last_login,
                order_type=entry.changed_by_user.order_type
            )

        response_history.append(
            schemas.MilestoneHistoryResponse(
                id=entry.id,
                milestone_id=entry.milestone_id,
                change_type=entry.change_type,
                old_value=entry.old_value,
                new_value=entry.new_value,
                remarks=entry.remarks,
                changed_by_user=user_response,
                changed_at=entry.changed_at,
            )
        )
    return response_history

@app.put("/api/milestones/{milestone_id}")
def update_milestone_by_id(
    milestone_id: int,
    milestone_update: schemas.MilestoneUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    milestone = db.query(models.Milestone).filter(models.Milestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    order = db.query(models.Order).filter(models.Order.id == milestone.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    user_dept = current_user.department
    prev_status = milestone.status

    # Departmental milestone update permissions
    scm_allowed_milestones = [
        "PO Released", "PM Procurement Released", "PM Received",
        "Production Planned", "Production Started", "Production Completed", "Batch Released"
    ]
    exports_only_milestones = ["Ready for Shipment", "Freight Booked", "Shipped", "Delivered"]

    if user_dept == "SCM" and milestone.name in exports_only_milestones:
        raise HTTPException(status_code=403, detail="SCM department is not authorized to update Ready for Shipment, Freight Booked, Shipped, or Delivered milestones.")
    elif user_dept in ["Exports", "Exports Team"] and milestone.name in scm_allowed_milestones:
        raise HTTPException(status_code=403, detail="Exports department is not authorized to update SCM milestones.")

    # Mandatory remarks check when target date or status is modified
    if (milestone_update.target_date is not None and milestone.target_date != milestone_update.target_date) or (milestone_update.status and prev_status != milestone_update.status):
        if not milestone_update.remarks or not milestone_update.remarks.strip():
            raise HTTPException(status_code=400, detail="Remarks are mandatory when updating milestone target date or status.")

    if milestone_update.target_date is not None:
        if milestone.target_date != milestone_update.target_date:
            old_val = str(milestone.target_date.strftime('%Y-%m-%d')) if milestone.target_date else "Not Set"
            new_val = str(milestone_update.target_date.strftime('%Y-%m-%d')) if milestone_update.target_date else "Not Set"
            hist = models.MilestoneHistory(
                milestone_id=milestone.id,
                change_type="TARGET_DATE_UPDATE",
                old_value=old_val,
                new_value=new_val,
                remarks=milestone_update.remarks.strip() if milestone_update.remarks else None,
                changed_by_user_id=current_user.id
            )
            db.add(hist)
        milestone.target_date = milestone_update.target_date

    if milestone_update.status:
        if prev_status != milestone_update.status:
            hist = models.MilestoneHistory(
                milestone_id=milestone.id,
                change_type="STATUS_UPDATE",
                old_value=prev_status,
                new_value=milestone_update.status,
                remarks=milestone_update.remarks.strip() if milestone_update.remarks else None,
                changed_by_user_id=current_user.id
            )
            db.add(hist)
        milestone.status = milestone_update.status

    if milestone_update.actual_date is not None:
        milestone.actual_date = milestone_update.actual_date
    if milestone_update.remarks is not None:
        milestone.remarks = milestone_update.remarks

    milestone.updated_at = datetime.utcnow()

    # Check for delays
    if milestone.status == "COMPLETED" and milestone.target_date:
        if milestone.actual_date and milestone.actual_date > milestone.target_date:
            milestone.status = "DELAYED"
            create_delay_alert(order, milestone, db)

    # The prev_order_status is local to this function, so define it here
    prev_order_status_for_milestone_update = order.status
    update_order_status_from_milestones(order, db, current_user.id, request.client.host)

    log_audit(
        db, order.id, current_user.id, "MILESTONE_UPDATE",
        prev_status, milestone.status,
        f"Milestone '{milestone.name}' updated by {user_dept}",
        request.client.host
    )

    db.commit()
    return {"message": "Milestone updated successfully"}


@app.put("/api/orders/{order_id}/milestones/bulk-target-dates")   # ⚠️ KEEP YOUR EXISTING PATH — do not copy this line if yours differs
def set_bulk_target_dates(
    order_id: int,
    payload: schemas.BulkTargetDateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department not in ("SCM", "Management"):
        raise HTTPException(status_code=403, detail="Only SCM or Management can set milestone target dates")

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    def _norm(value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    ALIASES = {"pm procurement released": "po released"}
    CATEGORY_BY_NAME = {
        "PO Released": "Artwork", "PM Received": "Artwork",
        "Production Planned": "SCM", "Production Started": "SCM",
        "Production Completed": "SCM", "Batch Released": "SCM",
        "Ready for Shipment": "Logistics", "Freight Booked": "Logistics",
        "Shipped": "Logistics", "Delivered": "Logistics",
    }

    results = []
    for item in payload.milestones:
        milestone = None

        # 1) Find by ID
        if item.milestone_id:
            milestone = db.query(models.Milestone).filter(
                models.Milestone.id == item.milestone_id,
                models.Milestone.order_id == order_id
            ).first()

        # 2) Fallback: find by name (handles alias)
        if milestone is None and item.milestone_name:
            wanted = _norm(item.milestone_name)
            for m in order.milestones:
                db_name = _norm(m.name)
                if db_name == wanted or ALIASES.get(db_name) == wanted:
                    milestone = m
                    break

        # 3) Still missing → create it (for orders whose milestones were never initialized)
        if milestone is None:
            if not item.milestone_name:
                raise HTTPException(status_code=400,
                    detail=f"Milestone id={item.milestone_id} not found for order {order_id}")
            milestone = models.Milestone(
                order_id=order_id,
                name=item.milestone_name,
                category=CATEGORY_BY_NAME.get(item.milestone_name, "SCM"),
                status="PENDING",
                target_date=item.target_date,
            )
            db.add(milestone)
            db.flush()
            results.append({"milestone_id": milestone.id, "milestone_name": milestone.name,
                            "target_date": str(item.target_date) if item.target_date else None,
                            "action": "created"})
            continue

        # Existing → update + write history
        old_date = milestone.target_date
        if old_date != item.target_date:
            db.add(models.MilestoneHistory(
                milestone_id=milestone.id,
                change_type="TARGET_DATE_UPDATE",
                old_value=str(old_date) if old_date else None,
                new_value=str(item.target_date) if item.target_date else None,
                changed_by_user_id=current_user.id,
            ))
            milestone.target_date = item.target_date
            action = "updated"
        else:
            action = "unchanged"

        results.append({"milestone_id": milestone.id, "milestone_name": milestone.name,
                        "target_date": str(item.target_date) if item.target_date else None,
                        "action": action})

    # Audit trail entry (uses your existing helper)
    log_audit(db, order_id=order_id, user_id=current_user.id,
              action="MILESTONE_TARGET_DATES_SET",
              prev_status=None, new_status=None,
              remarks=" | ".join(f"{r['milestone_name']} → {r['target_date']}" for r in results))

    db.commit()
    return {"order_id": order_id, "results": results}

    
def create_delay_alert(order: models.Order, milestone: models.Milestone, db: Session):
    """Create alert for delayed milestone"""
    alert = models.Alert(
        alert_type="MILESTONE_DELAY",
        order_id=order.id,
        message=f"Milestone '{milestone.name}' is delayed for Order {order.order_id}",
        priority="HIGH",
        department=milestone.category
    )
    db.add(alert)

def update_order_status_from_milestones(order: models.Order, db: Session, user_id: int, ip_address: Optional[str]):
    """Update order status based on milestone progress"""
    milestones = db.query(models.Milestone).filter(models.Milestone.order_id == order.id).all()
    
    # Check if shipped
    shipped = any(m.name == "Shipped" and m.status == "COMPLETED" for m in milestones)
    delivered = any(m.name == "Delivered" and m.status == "COMPLETED" for m in milestones)
    ready_for_shipment = any(m.name == "Ready for Shipment" and m.status == "COMPLETED" for m in milestones)
    
    prev_status = order.status
    
    if delivered:
        order.status = "DELIVERED"
        order.delivered_at = datetime.utcnow()
    elif shipped:
        order.status = "SHIPPED"
        order.shipped_at = datetime.utcnow()
    elif ready_for_shipment:
        order.status = "READY FOR SHIPMENT"
    elif order.status == "ORDER ACCEPTED":
        order.status = "IN EXECUTION"
    
    # Check for delays
    delayed_milestones = [m for m in milestones if m.status == "DELAYED"]
    if delayed_milestones and order.status not in ["SHIPPED", "DELIVERED"]:
        order.status = "AT RISK"
    
    if prev_status != order.status:
        log_audit(db, order.id, user_id, "ORDER_STATUS_CHANGE", prev_status, order.status,
                  f"Status updated due to approval process: {prev_status} -> {order.status}", ip_address)

# ==================== ALERTS ====================

@app.get("/api/alerts", response_model=List[schemas.AlertResponse])
def get_alerts(
    is_read: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Alert).filter(models.Alert.department == current_user.department)
    if is_read is not None:
        query = query.filter(models.Alert.is_read == is_read)
    alerts = query.order_by(models.Alert.created_at.desc()).all()
    return alerts

@app.put("/api/alerts/{alert_id}/read")
def mark_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_read = True
    db.commit()
    return {"message": "Alert marked as read"}

# ==================== AUDIT LOGS ====================

@app.get("/api/audit-logs", response_model=List[schemas.AuditLogResponse])
def get_audit_logs(
    order_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.AuditLog).options(joinedload(models.AuditLog.user))
    if order_id:
        query = query.filter(models.AuditLog.order_id == order_id)
    logs = query.order_by(models.AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
    return logs


# ==================== DASHBOARD ====================

@app.get("/api/dashboard", response_model=schemas.DashboardData)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Get total new orders
    # This part should be implemented based on your definition of "new orders"
    # For example, orders created in the last 24 hours.
    # For demonstration, let's assume 0 for now.
    new_orders_count = db.query(models.Order).filter(models.Order.created_at >= (datetime.utcnow() - timedelta(days=1))).count()

    # Get total pending approval orders (any status that indicates pending approval)
    pending_approval_count = db.query(models.Order).filter(
        models.Order.status.in_([
            models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value,
            models.OrderStatus.PENDING_REGULATORY_REVISION.value,
            models.OrderStatus.PENDING_ARTWORK_PROCESS.value,
            models.OrderStatus.PENDING_FINANCE_APPROVAL.value,
            models.OrderStatus.PENDING_FINAL_EXPORTS_CHECK.value,
            models.OrderStatus.HOLD.value # Assuming HOLD also counts as pending action/approval
        ])
    ).count()

    # Get total accepted orders
    accepted_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.ORDER_FINALIZED.value).count()

    # Get total in execution orders
    in_execution_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.IN_EXECUTION.value).count()

    # Get total ready for shipment orders
    ready_shipment_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.READY_FOR_SHIPMENT.value).count()

    # Get total shipped orders
    shipped_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.SHIPPED.value).count()

    # Get total delivered orders
    delivered_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.DELIVERED.value).count()

    # Get total at risk orders
    at_risk_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.AT_RISK.value).count()

    # Get expiring registrations (e.g., expiring in next 30 days)
    expiring_registrations_count = db.query(models.Registration).filter(
        models.Registration.registration_expiry_date <= (date.today() + timedelta(days=30)),
        models.Registration.registration_expiry_date >= date.today(),
        models.Registration.registration_status == "Active"
    ).count()

    # Get missing certificates (registrations without certificate path)
    missing_certificates_count = db.query(models.Registration).filter(
        models.Registration.certificate_path == None
    ).count()

    # Assuming `open_orders` could be anything not finalized or rejected
    open_orders_count = db.query(models.Order).filter(
        models.Order.status.notin_([
            models.OrderStatus.ORDER_FINALIZED.value,
            models.OrderStatus.REJECTED.value
        ])
    ).count()

    # Assuming `delayed` refers to orders with delayed milestones
    delayed_count = db.query(models.Order).filter(models.Order.status == models.OrderStatus.AT_RISK.value).count()

    # Placeholder for on-time deliveries, needs more complex logic to determine
    on_time_deliveries_count = 0 # Currently not implemented
    total_delivered_count = delivered_count # Re-using delivered count for this

    # Compliance issues are tracked via alerts, so count compliance issue alerts
    compliance_issues_count = db.query(models.Alert).filter(models.Alert.alert_type == "COMPLIANCE_ISSUE").count()

    stats = schemas.DashboardStats(
        new_orders=new_orders_count,
        pending_approval=pending_approval_count,
        accepted=accepted_count,
        in_execution=in_execution_count,
        ready_shipment=ready_shipment_count,
        shipped=shipped_count,
        delivered=delivered_count,
        at_risk=at_risk_count,
        expiring_registrations=expiring_registrations_count,
        missing_certificates=missing_certificates_count,
        pending_approvals=pending_approval_count, # Re-using pending_approval_count
        open_orders=open_orders_count,
        delayed=delayed_count,
        on_time_deliveries=on_time_deliveries_count,
        total_delivered=total_delivered_count,
        compliance_issues=compliance_issues_count
    )

    # Fetch recent orders (e.g., last 5 updated orders)
    recent_orders_query = db.query(models.Order)
    if current_user.department == "SCM" and getattr(current_user, 'order_type', None):
        recent_orders_query = recent_orders_query.join(models.Order.product)
        if current_user.order_type == "PP":
            recent_orders_query = recent_orders_query.filter((models.Product.category == "PP") | (models.Product.category == "ALL"))
        elif current_user.order_type == "PNS":
            recent_orders_query = recent_orders_query.filter((models.Product.category == "PNS") | (models.Product.category == "ALL"))

    recent_orders = recent_orders_query.order_by(models.Order.updated_at.desc()).limit(5).all()

    # Fetch alerts for the current user's department
    alerts = db.query(models.Alert).filter(
        models.Alert.department == current_user.department,
        models.Alert.is_read == False
    ).order_by(models.Alert.created_at.desc()).limit(5).all()

    return schemas.DashboardData(stats=stats, recent_orders=recent_orders, alerts=alerts)
