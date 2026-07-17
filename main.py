from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime, timedelta
import uuid
import os
import shutil
import logging

from sqlalchemy.orm import relationship, joinedload # Added joinedload
import models
import schemas
import auth
from database import engine, get_db
from auth import get_current_user, authenticate_user, create_access_token, get_password_hash
from schemas import CanApproveResponse, CountryListResponse # Added CanApproveResponse, CountryListResponse

# Create database tables


app = FastAPI(
    title="EOCT - Export Order Control Tower",
    description="API for managing export orders, compliance, and execution tracking",
    version="1.0.0"
)

logging.basicConfig(level=logging.DEBUG)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","https://exportordercontroltower.netlify.app",],  # React frontend
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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
    user = authenticate_user(db, user_credentials.employee_id, user_credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid employee ID or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    access_token = create_access_token(data={"sub": user.employee_id})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

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
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department == "Artwork":
        products = db.query(models.Product).join(models.PMCodeRequest).distinct().offset(skip).limit(limit).all()
    else:
        products = db.query(models.Product).offset(skip).limit(limit).all()
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
    db_product = db.query(models.Product).filter(models.Product.sku_code == product.sku_code).first()
    if db_product:
        raise HTTPException(status_code=400, detail="SKU code already exists")
    
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

@app.get("/api/products/by-country", response_model=List[schemas.ProductResponse])
def get_products_by_country(
    country: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    products = (
        db.query(models.Product)
        .filter(models.Product.country == country)
        .filter(models.Product.is_active == True)
        .order_by(models.Product.product_name)
        .all()
    )

    return products

    
@app.get("/api/skus/{country}", response_model=List[schemas.SkuItem])
def get_skus_by_country(
    country: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return SKUs (code and name) that have an active registration for the given country."""
    registered_skus_codes = db.query(models.Registration.sku).filter(
        models.Registration.country == country,
        models.Registration.registration_status == "Active"
    ).distinct().all()
    
    sku_list = [r.sku for r in registered_skus_codes]
    if not sku_list:
        return []

    products = db.query(models.Product).filter(
        models.Product.sku_code.in_(sku_list),
        models.Product.is_active == True
    ).all()
    
    return [schemas.SkuItem(sku_code=p.sku_code, product_name=p.product_name) for p in products]

@app.get("/api/skus/{country}", response_model=List[schemas.SkuItem])
def get_skus_by_country(
    country: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return SKUs (code and name) that have an active registration for the given country."""
    registered_skus_codes = db.query(models.Registration.sku).filter(
        models.Registration.country == country,
        models.Registration.registration_status == "Active"
    ).distinct().all()
    
    sku_list = [r.sku for r in registered_skus_codes]
    if not sku_list:
        return []

    products = db.query(models.Product).filter(
        models.Product.sku_code.in_(sku_list),
        models.Product.is_active == True
    ).all()
    
    return [schemas.SkuItem(sku_code=p.sku_code, product_name=p.product_name) for p in products]

@app.get("/api/products/{sku}", response_model=schemas.ProductResponse)
def get_product(
    sku: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    product = db.query(models.Product).filter(models.Product.sku_code == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.patch("/api/products/{sku}/pm-code")
def update_product_pm_code(
    sku: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Allow Regulatory department to update PM code when artwork is not Available."""
    if current_user.department not in ["Regulatory", "Management"]:
        raise HTTPException(
            status_code=403,
            detail="Only Regulatory can update PM code"
        )
    product = db.query(models.Product).filter(models.Product.sku_code == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.primary_pm_code = data.get("primary_pm_code", product.primary_pm_code)
    product.secondary_pm_code = data.get("secondary_pm_code", product.secondary_pm_code)
    product.leaf_pm_code = data.get("leaf_pm_code", product.leaf_pm_code)
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
        models.PMCodeRequest.product_sku == sku,
        models.PMCodeRequest.status != "APPROVED"
    ).first()
    
    if not request:
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
        if request.status == "REJECTED":
            old_status = request.status
            request.status = "PENDING_ARTWORK"
            request.updated_at = datetime.utcnow()
            transaction = models.PMCodeTransaction(
                request_id=request.id,
                from_state=old_status,
                to_state="PENDING_ARTWORK",
                action_by_dept="Regulatory",
                action_by_user_id=current_user.id,
                remarks="PM Code requested again"
            )
            db.add(transaction)
            
    db.commit()
    db.refresh(request)
    return request

@app.post("/api/products/pm-requests/{request_id}/submit", response_model=schemas.PMCodeRequestResponse)
def submit_pm_code(
    request_id: int,
    data: schemas.PMCodeSubmit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.department != "Artwork":
        raise HTTPException(status_code=403, detail="Only Artwork team can submit PM Code")
    
    request = db.query(models.PMCodeRequest).filter(models.PMCodeRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="PM Code Request not found")
    
    if request.status != "PENDING_ARTWORK":
        raise HTTPException(status_code=400, detail="Request is not pending artwork action")
    
    last_tx = db.query(models.PMCodeTransaction).filter(
        models.PMCodeTransaction.request_id == request.id
    ).order_by(models.PMCodeTransaction.created_at.desc()).first()
    
    now = datetime.utcnow()
    response_time_days = 0.0
    if last_tx:
        time_diff = now - last_tx.created_at
        response_time_days = round(time_diff.total_seconds() / 86400.0, 2)
    
    old_status = request.status
    request.status = "AWAITING_REGULATORY_APPROVAL"
    request.current_primary_pm_code = data.primary_pm_code
    request.current_secondary_pm_code = data.secondary_pm_code
    request.current_leaf_pm_code = data.leaf_pm_code
    request.updated_at = now
    
    transaction = models.PMCodeTransaction(
        request_id=request.id,
        from_state=old_status,
        to_state="AWAITING_REGULATORY_APPROVAL",
        action_by_dept="Artwork",
        action_by_user_id=current_user.id,
        primary_pm_code=data.primary_pm_code,
        secondary_pm_code=data.secondary_pm_code,
        leaf_pm_code=data.leaf_pm_code,
        remarks=data.remarks,
        created_at=now,
        response_time_days=response_time_days
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
            product.primary_pm_code = request.current_primary_pm_code
            product.secondary_pm_code = request.current_secondary_pm_code
            product.leaf_pm_code = request.current_leaf_pm_code
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

@app.get("/api/registrations", response_model=List[schemas.RegistrationResponse])
def get_registrations(
    skip: int = 0,
    limit: int = 100,
    country: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Registration)
    if country:
        query = query.filter(models.Registration.country == country)
    registrations = query.offset(skip).limit(limit).all()
    return registrations

@app.get("/api/countries", response_model=schemas.CountryListResponse)
def get_countries(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    countries = (
        db.query(models.Product.country)
        .filter(models.Product.country.isnot(None))
        .filter(models.Product.country != "")
        .distinct()
        .order_by(models.Product.country)
        .all()
    )

    return {
        "countries": [c[0] for c in countries]
    }

@app.post("/api/registrations", response_model=schemas.RegistrationResponse)
def create_registration(
    registration: schemas.RegistrationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_registration = models.Registration(**registration.dict())
    db.add(db_registration)
    db.commit()
    db.refresh(db_registration)
    return db_registration

@app.get("/api/debug/registrations", response_model=List[schemas.RegistrationResponse])
def debug_registrations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Debug endpoint to return all registrations."""
    registrations = db.query(models.Registration).all()
    print(f"DEBUG: All Registrations from DB: {registrations}")
    return registrations

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
    limit: int = 100,
    country: Optional[str] = None, # Added optional country filter
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Customer)
    if country:
        query = query.filter(models.Customer.country == country)
    customers = query.offset(skip).limit(limit).all()
    return customers

@app.post("/api/customers", response_model=schemas.CustomerResponse)
def create_customer(
    customer: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_customer = models.Customer(**customer.dict())
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
    """Return products that have an active registration for the given customer's country."""
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    registered_skus = db.query(models.Registration.sku).filter(
        models.Registration.country == customer.country,
        models.Registration.registration_status == "Active"
    ).distinct().all()
    sku_list = [r.sku for r in registered_skus]
    if not sku_list:
        return []
    products = db.query(models.Product).filter(
        models.Product.sku_code.in_(sku_list),
        models.Product.is_active == True
    ).all()
    return products

@app.get("/api/customers/{customer_id}", response_model=schemas.CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# ==================== ORDER MANAGEMENT ====================

def run_compliance_check(order: models.Order, db: Session):
    """Run automatic compliance check on order"""
    issues = []
    
    # Check registration
    registration = db.query(models.Registration).filter(
        models.Registration.country == order.country,
        models.Registration.sku == order.sku,
        models.Registration.registration_status == "Active"
    ).first()
    
    if not registration:
        issues.append(f"No active registration found for SKU {order.sku} in {order.country}")
    elif registration.registration_expiry_date and registration.registration_expiry_date < date.today():
        issues.append(f"Registration expired for SKU {order.sku} in {order.country}")
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
        if order.quantity < product.moq:
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
        # {"name": "Artwork Requested", "category": "Artwork"},
        # {"name": "Artwork Approved", "category": "Artwork"},
        {"name": "PM Procurement Released", "category": "Artwork"},
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
            category=m["category"],
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
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Order)

    # Filter for Artwork department: only show orders that are pending artwork process
    if current_user.department == "Artwork":
        query = query.filter(models.Order.status == models.OrderStatus.PENDING_ARTWORK_PROCESS.value)
    
    if status:
        query = query.filter(models.Order.status == status)

    orders = query.order_by(models.Order.created_at.desc()).offset(skip).limit(limit).all()
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
    country_prefix = order.country[:3].upper() if order.country else "XXX"
    customer_prefix = customer.customer_name[:3].upper() if customer and customer.customer_name else "XXX"
    current_time = datetime.now()
    order_number = f"{country_prefix}-{customer_prefix}-{current_time.strftime('%m%Y')}"
    
    order_data = order.dict()
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
    create_milestones(db_order, db)
    
    # Log audit
    log_audit(db, db_order.id, current_user.id, "ORDER_CREATED", None, "NEW ORDER", 
              "Order created and compliance check run", request.client.host)
    
    db.commit()
    db.refresh(db_order)
    return db_order

@app.get("/api/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
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
    if user_dept == "Exports" and current_user.role == "manager":
        exports_pending_approvals = [
            a for a in all_approvals
            if a.status == models.ApprovalStatus.PENDING.value and
               (a.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value or
                a.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value)
        ]
        
        if not exports_pending_approvals:
            logging.debug(f"[{current_user.employee_id}] Exports Manager Override: No pending Exports Manager approvals to override.")
            raise HTTPException(
                status_code=403,
                detail="No pending Exports Manager approvals found for this order to override."
            )
        
        # Find the earliest Exports Manager approval in sequence to act on
        approval_to_act_on = min(exports_pending_approvals, key=lambda x: x.sequence)
        
        # Mark with decision and flag it as Exports Manager override
        approval_to_act_on.status = decision_str
        approval_to_act_on.remarks = f"[Exports Manager Override] {approval_data.remarks.strip() if approval_data.remarks else ''}"
        approval_to_act_on.approver_id = current_user.id
        approval_to_act_on.approved_at = datetime.utcnow()

        log_audit(
            db, order_id, current_user.id,
            f"EXPORTS_MANAGER_OVERRIDE_APPROVAL_SEQ{approval_to_act_on.sequence}",
            order.status, order.status,
            f"Exports Manager overrode {approval_to_act_on.department} approval (seq {approval_to_act_on.sequence}): "
            f"{approval_to_act_on.status} - {approval_to_act_on.remarks}",
            request.client.host
        )

        check_all_approvals(order, db, current_user.id, request.client.host)
        db.commit()
        return {"message": f"Exports Manager has overridden the {approval_to_act_on.department} approval successfully."}


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
                detail=f"Approval for department \'{approval_data.target_department}\' not found for this order."
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
        logging.debug(f"[{current_user.employee_id}] Normal Approval: No pending approval found for user\'s department {user_dept_enum.value}.")
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
        if prev_approval.status not in [models.ApprovalStatus.APPROVED.value, models.ApprovalStatus.APPROVED_WITH_REMARKS.value, models.ApprovalStatus.REJECTED.value]:
            logging.debug(f"[{current_user.employee_id}] Normal Approval: Cannot approve due to pending previous approval from {prev_approval.department}.")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Cannot approve: {prev_approval.department} (sequence {prev_approval.sequence}) "
                    f"has not approved yet. Current status: {prev_approval.status}"
                )
            )

    approval_to_act_on.status = decision_str
    approval_to_act_on.remarks = approval_data.remarks
    approval_to_act_on.approver_id = current_user.id
    approval_to_act_on.approved_at = datetime.utcnow()

    log_audit(
        db, order_id, current_user.id,
        f"{user_dept_enum.value}_APPROVAL_SEQ{approval_to_act_on.sequence}",
        order.status, order.status,
        f"{user_dept_enum.value} approval (seq {approval_to_act_on.sequence}): {approval_to_act_on.status} - {approval_to_act_on.remarks}",
        request.client.host
    )

    # After the specific approval is processed, check all approvals to update the overall order status
    check_all_approvals(order, db, current_user.id, request.client.host)
    db.commit()
    return {"message": "Approval submitted successfully"}

@app.get("/api/orders/{order_id}/can-approve", response_model=CanApproveResponse)
def can_approve_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Check if current user can approve this order based on sequential workflow.
    SCM can always approve/reject any pending approval as an override.
    Exports Manager can approve any pending Exports Manager approval (initial or final) at any time."""
    logging.debug(f"[{current_user.employee_id}] Checking can_approve for Order ID: {order_id}")
    logging.debug(f"[{current_user.employee_id}] User Department: {current_user.department}, Role: {current_user.role}")
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    user_dept = current_user.department

    # Fetch all approvals for the order to determine the current step
    all_approvals = db.query(models.OrderApproval).filter(
        models.OrderApproval.order_id == order_id
    ).order_by(models.OrderApproval.sequence).all()

    # Exports Manager Override Path
    if user_dept == "Exports" and current_user.role == "manager":
        exports_pending_approvals = [
            a for a in all_approvals
            if a.status == models.ApprovalStatus.PENDING.value and
               (a.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value or
                a.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value)
        ]
        if exports_pending_approvals:
            # Check if any previous required sequential approvals are still pending for non-Exports Manager steps
            # This allows Exports Manager to approve their step, even if other steps are skipped or yet to come.
            # However, if an earlier, non-Exports Manager step is PENDING, we should still indicate that as a blocker
            # unless the intent is a full override of all prior steps. For now, let's allow "their" step to be approved
            # if it's pending.
            
            # Find the lowest sequence Exports Manager approval that is pending
            earliest_exports_pending = min(exports_pending_approvals, key=lambda x: x.sequence)

            # Check if any non-Exports Manager approval with lower sequence is still pending.
            # If so, the Exports Manager can approve their step, but a "waiting_for" might still be shown
            # for the other department. This needs clarification.
            # For simplicity, let's assume if any Exports Manager approval is pending, they can approve it.
            
            logging.debug(f"[{current_user.employee_id}] Can approve (Exports Manager Override): True, Reason: Exports Manager pending approval found.")
            return {
                "can_approve": True,
                "is_scm_override": False,
                "is_exports_override": True,
                "reason": None,
                "current_sequence": earliest_exports_pending.sequence,
                "pending_department": earliest_exports_pending.department,
                "waiting_for": None
            }
        logging.debug(f"[{current_user.employee_id}] Can approve (Exports Manager Override): False, Reason: No pending Exports Manager approvals.")
        logging.debug(f"[{current_user.employee_id}] Can approve (Exports Manager Override): False, Reason: No pending Exports Manager approvals.")
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": True,
            "reason": "No pending Exports Manager approvals remaining on this order.",
            "current_sequence": None,
            "waiting_for": None
        }

    # SCM override: can approve any pending approval
    if user_dept == "SCM":
        pending = [a for a in all_approvals if a.status == models.ApprovalStatus.PENDING.value]
        if pending:
            logging.debug(f"[{current_user.employee_id}] Can approve (SCM Override): True, Reason: Pending approval found for SCM override.")
            logging.debug(f"[{current_user.employee_id}] Can approve (SCM Override): True, Reason: Pending approval found for SCM override.")
            return {
                "can_approve": True,
                "is_scm_override": True,
                "is_exports_override": False,
                "reason": None,
                "current_sequence": pending[0].sequence,
                "pending_department": pending[0].department,
                "waiting_for": None
            }
        logging.debug(f"[{current_user.employee_id}] Can approve (SCM Override): False, Reason: No pending approvals for SCM override.")
        logging.debug(f"[{current_user.employee_id}] Can approve (SCM Override): False, Reason: No pending approvals for SCM override.")
        return {
            "can_approve": False,
            "is_scm_override": True,
            "is_exports_override": False,
            "reason": "No pending approvals remaining on this order.",
            "current_sequence": None,
            "waiting_for": None
        }

    # Convert department strings to ApprovalDepartment enum members for easier comparison
    user_dept_enum = get_user_approval_department(user_dept, all_approvals)
    
    # If the user's department is not recognized in the enum and it's not SCM, then they cannot approve.
    if user_dept_enum is None:
        logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: Department not in workflow.")
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": "Your department is not part of the defined approval workflow.",
            "current_sequence": None,
            "waiting_for": None
        }

    if user_dept_enum in [models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL, models.ApprovalDepartment.EXPORTS_MANAGER_FINAL] and current_user.role != "manager":
        logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: Not Exports Manager.")
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": "Only Export Manager can approve Exports approvals",
            "current_sequence": None,
            "waiting_for": None
        }

    user_pending_approvals = [
        a for a in all_approvals 
        if a.status == models.ApprovalStatus.PENDING.value and a.department == user_dept_enum.value
    ]

    if not user_pending_approvals:
        logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: No pending approval for user's department.")
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": "No pending approval found for your department for this order.",
            "current_sequence": None,
            "waiting_for": None
        }
    
    # Determine the specific approval to act on (same logic as approve_order endpoint)
    if user_dept_enum == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL:
        approval_to_check = next(
            (a for a in user_pending_approvals if a.department == models.ApprovalDepartment.EXPORTS_MANAGER_INITIAL.value),
            None
        )
    elif user_dept_enum == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL:
        approval_to_check = next(
            (a for a in user_pending_approvals if a.department == models.ApprovalDepartment.EXPORTS_MANAGER_FINAL.value),
            None
        )
    else:
        approval_to_check = user_pending_approvals[0]

    if not approval_to_check:
        logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: No pending approval for specific role in department.")
        return {
            "can_approve": False,
            "is_scm_override": False,
            "is_exports_override": False,
            "reason": "No pending approval found for your specific role in this department.",
            "current_sequence": None,
            "waiting_for": None
        }

    current_sequence = approval_to_check.sequence
    previous_approvals = [a for a in all_approvals if a.sequence < current_sequence]
    for prev_approval in previous_approvals:
        if prev_approval.status not in [
            models.ApprovalStatus.APPROVED.value,
            models.ApprovalStatus.APPROVED_WITH_REMARKS.value,
            models.ApprovalStatus.REJECTED.value
        ]:
            logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: Previous approval not complete. Waiting for {prev_approval.department}.")
            return {
                "can_approve": False,
                "is_scm_override": False,
                "is_exports_override": False,
                "reason": (
                    f"Waiting for {prev_approval.department} (sequence {prev_approval.sequence}) "
                    f"has not approved yet. Current status: {prev_approval.status}"
                ),
                "current_sequence": current_sequence,
                "waiting_for": {
                    "department": prev_approval.department,
                    "sequence": prev_approval.sequence,
                    "status": prev_approval.status
                }
            }
        logging.debug(f"[{current_user.employee_id}] Can approve: False, Reason: Previous approval not complete. Waiting for {prev_approval.department}.")

    logging.debug(f"[{current_user.employee_id}] Can approve: True, Reason: All checks passed.")
    return {
        "can_approve": True,
        "is_scm_override": False,
        "is_exports_override": False,
        "reason": None,
        "current_sequence": current_sequence,
        "waiting_for": None
    }
    logging.debug(f"[{current_user.employee_id}] Can approve: True, Reason: All checks passed.")

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
                  f"Order status updated due to approval process: {prev_order_status} -> {order.status}", ip_address)

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
    print(f"DEBUG: User Department: {user_dept}, Milestone Category: {milestone.category}")

    # Authorization logic for milestone updates
    if milestone.category == "Logistics" and user_dept != "Regulatory":
        raise HTTPException(
            status_code=403,
            detail="Only the Exports department is allowed to update Logistics milestones."
        )
    elif milestone.category == "SCM" and user_dept != "SCM":
        raise HTTPException(
            status_code=403,
            detail="Only the SCM department is allowed to update SCM milestones."
        )
    elif milestone.category not in ["Logistics", "SCM"]:
        # For other categories, we might need a more general rule or explicit denials.
        # For now, deny if not SCM or Exports for Logistics/SCM respectively.
        # This implicitly denies updates for categories not explicitly handled.
        raise HTTPException(
            status_code=403,
            detail=f"Updates for {milestone.category} milestones are not explicitly authorized for your department."
        )

    prev_status = milestone.status

    if milestone_update.status:
        milestone.status = milestone_update.status
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
        log_audit(db, order.id, user_id, "STATUS_CHANGE", prev_status, order.status,
                  f"Status updated based on milestone progress", ip_address)

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
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.AuditLog)
    if order_id:
        query = query.filter(models.AuditLog.order_id == order_id)
    logs = query.order_by(models.AuditLog.timestamp.desc()).limit(limit).all()
    return logs

# ==================== DASHBOARD ====================

@app.get("/api/dashboard", response_model=schemas.DashboardData)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user_dept = current_user.department
    stats = schemas.DashboardStats()
    
    if user_dept == "Exports":
        stats.new_orders = db.query(models.Order).filter(models.Order.status == models.OrderStatus.REGULATORY_CREATED.value).count()
        stats.pending_approval = db.query(models.Order).filter(models.Order.status == models.OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value).count() # New: Pending Exports Manager Approval
        stats.accepted = db.query(models.Order).filter(models.Order.status == models.OrderStatus.ORDER_FINALIZED.value).count()
        stats.in_execution = db.query(models.Order).filter(
            models.Order.status.in_([models.OrderStatus.IN_EXECUTION.value, models.OrderStatus.AT_RISK.value])
        ).count()
        stats.ready_shipment = db.query(models.Order).filter(models.Order.status == models.OrderStatus.READY_FOR_SHIPMENT.value).count()
        stats.shipped = db.query(models.Order).filter(models.Order.status == models.OrderStatus.SHIPPED.value).count()
        stats.delivered = db.query(models.Order).filter(models.Order.status == models.OrderStatus.DELIVERED.value).count()
        stats.at_risk = db.query(models.Order).filter(models.Order.status == models.OrderStatus.AT_RISK.value).count()
    
    elif user_dept == "Regulatory":
        # Expiring registrations (within 90 days)
        expiry_date = date.today() + timedelta(days=90)
        stats.expiring_registrations = db.query(models.Registration).filter(
            models.Registration.registration_expiry_date <= expiry_date,
            models.Registration.registration_status == "Active"
        ).count()
        stats.missing_certificates = db.query(models.Registration).filter(
            models.Registration.certificate_path == None
        ).count()
        stats.pending_approvals = db.query(models.OrderApproval).filter(
            models.OrderApproval.department == models.ApprovalDepartment.REGULATORY.value,
            models.OrderApproval.status == models.ApprovalStatus.PENDING.value
        ).count()
    
    elif user_dept == "Artwork":
        stats.pending_approvals = db.query(models.OrderApproval).filter(
            models.OrderApproval.department == models.ApprovalDepartment.ARTWORK.value,
            models.OrderApproval.status == models.ApprovalStatus.PENDING.value
        ).count()
        stats.new_orders = db.query(models.Order).filter(
            models.Order.status == models.OrderStatus.PENDING_ARTWORK_PROCESS.value
        ).count()
    
    elif user_dept == "SCM":
        stats.pending_approvals = db.query(models.OrderApproval).filter(
            models.OrderApproval.department == "SCM",
            models.OrderApproval.status == "PENDING"
        ).count()
    
    elif user_dept == "Finance":
        stats.pending_approvals = db.query(models.OrderApproval).filter(
            models.OrderApproval.department == models.ApprovalDepartment.FINANCE.value,
            models.OrderApproval.status == models.ApprovalStatus.PENDING.value
        ).count()
    
    elif user_dept == "Management":
        stats.open_orders = db.query(models.Order).filter(
            ~models.Order.status.in_(["DELIVERED", "CANCELLED"])
        ).count()
        stats.at_risk = db.query(models.Order).filter(models.Order.status == "AT RISK").count()
        stats.delayed = db.query(models.Order).filter(models.Order.status == "DELAYED").count()
        
        # On-time delivery calculation
        delivered_orders = db.query(models.Order).filter(models.Order.status == "DELIVERED").all()
        on_time_count = sum(1 for o in delivered_orders 
                          if o.delivered_at and o.delivered_at.date() <= o.requested_delivery_date)
        stats.on_time_deliveries = on_time_count
        stats.total_delivered = len(delivered_orders)
        
        stats.compliance_issues = db.query(models.Order).filter(
            models.Order.compliance_status == "FAILED"
        ).count()
    
    # Recent orders
    recent_orders = db.query(models.Order).order_by(models.Order.created_at.desc()).limit(10).all()
    
    # Unread alerts
    alerts = db.query(models.Alert).filter(
        models.Alert.department == user_dept,
        models.Alert.is_read == False
    ).order_by(models.Alert.created_at.desc()).limit(5).all()
    
    return schemas.DashboardData(
        stats=stats,
        recent_orders=recent_orders,
        alerts=alerts
    )

# ==================== INITIALIZATION ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
