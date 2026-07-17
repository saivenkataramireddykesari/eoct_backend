import enum
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class ApprovalStatus(enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPROVED_WITH_REMARKS = "APPROVED_WITH_REMARKS"
    REJECTED = "REJECTED"

class ApprovalDepartment(enum.Enum):
    EXPORTS_MANAGER_INITIAL = "EXPORTS_MANAGER_INITIAL"
    ARTWORK = "ARTWORK"
    REGULATORY = "REGULATORY"
    FINANCE = "FINANCE"
    EXPORTS_MANAGER_FINAL = "EXPORTS_MANAGER_FINAL"

class OrderStatus(enum.Enum):
    REGULATORY_CREATED = "REGULATORY_CREATED"
    PENDING_EXPORTS_REVIEW = "PENDING_EXPORTS_REVIEW"
    EXPORTS_REVIEWED = "EXPORTS_REVIEWED"
    PENDING_REGULATORY_REVISION = "PENDING_REGULATORY_REVISION"
    REGULATORY_REVISED = "REGULATORY_REVISED"
    PENDING_ARTWORK_PROCESS = "PENDING_ARTWORK_PROCESS"
    ARTWORK_PROCESSED_AWAITING_REGULATORY = "ARTWORK_PROCESSED_AWAITING_REGULATORY"
    PENDING_FINANCE_APPROVAL = "PENDING_FINANCE_APPROVAL"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    PENDING_FINAL_EXPORTS_CHECK = "PENDING_FINAL_EXPORTS_CHECK"
    ORDER_FINALIZED = "ORDER_FINALIZED"
    REJECTED = "REJECTED"
    HOLD = "HOLD"
    IN_EXECUTION = "IN_EXECUTION"
    AT_RISK = "AT_RISK"
    READY_FOR_SHIPMENT = "READY_FOR_SHIPMENT"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    PENDING_EXPORTS_MANAGER_APPROVAL = "PENDING_EXPORTS_MANAGER_APPROVAL"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    password = Column(String(200), nullable=False)
    department = Column(String(50), nullable=False)  # Exports, Regulatory, SCM, Artwork, Finance, Management
    role = Column(String(50), nullable=False, default="user")  # user, manager, admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    approvals = relationship("OrderApproval", back_populates="approver")
    audit_logs = relationship("AuditLog", back_populates="user")

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku_code = Column(String(50), unique=True, index=True, nullable=False)
    product_name = Column(String(200), nullable=False)
    category = Column(String(100))
    country = Column(String(100))
    customer = Column(String(200))
    pack_size = Column(String(50))
    standard_batch_size = Column(Integer)
    moq = Column(Integer)
    primary_pm_code = Column(String(255))
    secondary_pm_code = Column(String(50))
    leaf_pm_code = Column(String(50))
    current_artwork_version = Column(String(20))
    artwork_status = Column(String(50), default="Not Available")  # Available, Pending, Not Available
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    orders = relationship("Order", back_populates="product")
    registrations = relationship("Registration", back_populates="product")
    pm_code_requests = relationship("PMCodeRequest", back_populates="product")

class Registration(Base):
    __tablename__ = "registrations"
    
    id = Column(Integer, primary_key=True, index=True)
    country = Column(String(100), nullable=False)
    sku = Column(String(50), ForeignKey("products.sku_code"), nullable=False)
    registration_number = Column(String(100), nullable=False)
    registration_status = Column(String(50), default="Active")  # Active, Expired, Pending
    registration_issue_date = Column(Date)
    registration_expiry_date = Column(Date)
    certificate_path = Column(String(500))
    remarks = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    product = relationship("Product", back_populates="registrations")

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(200), nullable=False)
    country = Column(String(100), nullable=False)
    payment_terms = Column(String(100))
    agreement_status = Column(String(50), default="Pending")  # Active, Expired, Pending
    agreement_validity = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    orders = relationship("Order", back_populates="customer")

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(50), unique=True, index=True, nullable=False)
    order_number = Column(String(50), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    country = Column(String(100), nullable=False)
    po_number = Column(String(50), nullable=False)
    po_date = Column(Date, nullable=False)
    sku = Column(String(50), ForeignKey("products.sku_code"), nullable=False)
    sales_quantity = Column(Integer, default=0)
    free_quantity = Column(Integer, default=0)
    quantity = Column(Integer, nullable=False)  # total = sales + free
    requested_delivery_date = Column(Date, nullable=False)
    shipping_terms = Column(String(100))
    import_license_required = Column(Boolean, default=False)
    import_license_validity = Column(Date)
    remarks = Column(Text)
    
    # Status tracking
    status = Column(String(50), default=OrderStatus.PENDING_EXPORTS_MANAGER_APPROVAL.value)
    
    # Compliance check results
    compliance_status = Column(String(50))
    compliance_remarks = Column(Text)
    
    # SCM Planning
    tentative_production_date = Column(Date)
    tentative_release_date = Column(Date)
    
    # Tracking dates
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    accepted_at = Column(DateTime)
    shipped_at = Column(DateTime)
    delivered_at = Column(DateTime)
    
    # Relationships
    customer = relationship("Customer", back_populates="orders")
    product = relationship("Product", back_populates="orders")
    approvals = relationship("OrderApproval", back_populates="order", cascade="all, delete-orphan")
    milestones = relationship("Milestone", back_populates="order", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="order", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="order", cascade="all, delete-orphan")

class OrderApproval(Base):
    __tablename__ = "order_approvals"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    department = Column(String(50), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(50), default=ApprovalStatus.PENDING.value)
    remarks = Column(Text)
    approved_at = Column(DateTime)
    sequence = Column(Integer, nullable=False) # Will be set based on ApprovalDepartment
    created_at = Column(DateTime, default=datetime.utcnow)
    
    order = relationship("Order", back_populates="approvals")
    approver = relationship("User", back_populates="approvals")

class Milestone(Base):
    __tablename__ = "milestones"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    name = Column(String(100), nullable=False)  # Artwork Requested, Artwork Approved, etc.
    category = Column(String(50), nullable=False)  # Artwork, SCM, Logistics
    status = Column(String(50), default="PENDING")  # PENDING, IN PROGRESS, COMPLETED, DELAYED
    target_date = Column(Date)
    actual_date = Column(Date)
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    order = relationship("Order", back_populates="milestones")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    previous_status = Column(String(50))
    new_status = Column(String(50))
    remarks = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(50))
    
    order = relationship("Order", back_populates="audit_logs")
    user = relationship("User", back_populates="audit_logs")

class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String(50), nullable=False)  # REGISTRATION_EXPIRY, ARTWORK_DELAY, MILESTONE_DELAY, DELIVERY_RISK, COMPLIANCE_ISSUE
    order_id = Column(Integer, ForeignKey("orders.id"))
    message = Column(Text, nullable=False)
    priority = Column(String(20), default="MEDIUM")  # LOW, MEDIUM, HIGH, CRITICAL
    department = Column(String(50))  # Target department
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
    
    order = relationship("Order", back_populates="alerts")

class PMCodeRequest(Base):
    __tablename__ = "pm_code_requests"

    id = Column(Integer, primary_key=True, index=True)
    product_sku = Column(String(50), ForeignKey("products.sku_code"), nullable=False)
    status = Column(String(50), default="PENDING_ARTWORK")

    current_primary_pm_code = Column(String(50))
    current_secondary_pm_code = Column(String(50))
    current_leaf_pm_code = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="pm_code_requests")
    transactions = relationship("PMCodeTransaction", back_populates="request", cascade="all, delete-orphan")

    
class PMCodeTransaction(Base):
    __tablename__ = "pm_code_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("pm_code_requests.id"), nullable=False)
    from_state = Column(String(50))
    to_state = Column(String(50))
    action_by_dept = Column(String(50))  # Regulatory, Artwork
    action_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    primary_pm_code = Column(String(50))
    secondary_pm_code = Column(String(50))
    leaf_pm_code = Column(String(50))
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    response_time_days = Column(Float, default=0.0)
    
    request = relationship("PMCodeRequest", back_populates="transactions")
    user = relationship("User")

