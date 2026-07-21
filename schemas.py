from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from models import OrderStatus, ApprovalStatus

# User Schemas
class UserBase(BaseModel):
    employee_id: str
    name: str
    email: str
    department: str
    role: str = "user"
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    employee_id: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# PM Code Request Schemas
class PMCodeTransactionResponse(BaseModel):
    id: int
    request_id: int
    from_state: Optional[str]
    to_state: Optional[str]
    action_by_dept: Optional[str]
    action_by_user_id: int
    primary_pm_code: Optional[str]
    secondary_pm_code: Optional[str]
    leaf_pm_code: Optional[str]
    remarks: Optional[str]
    created_at: datetime
    response_time_days: float

    class Config:
        from_attributes = True

class PMCodeRequestResponse(BaseModel):
    id: int
    product_sku: str
    status: str
    current_primary_pm_code: Optional[str]
    current_secondary_pm_code: Optional[str]
    current_leaf_pm_code: Optional[str]
    created_at: datetime
    updated_at: datetime
    transactions: List[PMCodeTransactionResponse] = []

    class Config:
        from_attributes = True

class PMCodeRequestCreate(BaseModel):
    product_sku: str

class PMCodeSubmit(BaseModel):
    primary_pm_code: str
    secondary_pm_code: str
    leaf_pm_code: str
    remarks: Optional[str] = None

class PMCodeDecision(BaseModel):
    decision: str  # ACCEPT or REJECT
    remarks: Optional[str] = None

# Product Schemas
class ProductBase(BaseModel):
    sku_code: str
    product_name: str
    category: Optional[str] = None
    country: Optional[str] = None
    customer: Optional[str] = None
    pack_size: Optional[str] = None
    standard_batch_size: Optional[int] = None
    moq: Optional[int] = None
    primary_pm_code: Optional[str] = None
    secondary_pm_code: Optional[str] = None
    leaf_pm_code: Optional[str] = None
    current_artwork_version: Optional[str] = None
    artwork_status: str = "Not Available"

class ProductCreate(ProductBase):
    pass

class ProductResponse(ProductBase):
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pm_code_requests: List[PMCodeRequestResponse] = []

    class Config:
        from_attributes = True

class SkuItem(BaseModel):
    sku_code: str
    product_name: str

    class Config:
        from_attributes = True

class SkuItem(BaseModel):
    sku_code: str
    product_name: str

    class Config:
        from_attributes = True

# Registration Schemas
class RegistrationBase(BaseModel):
    country: str
    sku: str
    registration_number: str
    registration_status: str = "Active"
    registration_issue_date: Optional[date] = None
    registration_expiry_date: Optional[date] = None
    remarks: Optional[str] = None

class RegistrationCreate(RegistrationBase):
    pass

class RegistrationResponse(RegistrationBase):
    id: int
    certificate_path: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Customer Schemas
class CustomerBase(BaseModel):
    customer_name: str
    country: str
    payment_terms: Optional[str] = None
    agreement_status: str = "Pending"
    agreement_validity: Optional[date] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    order_type: Optional[str] = None # New field for auto-selection
    default_artwork_status: Optional[str] = None # New field for auto-selection
    order_count: Optional[int] = None
    category: Optional[str] = None

    class Config:
        from_attributes = True


# Milestone Schemas
class MilestoneBase(BaseModel):
    name: str
    category: str
    status: str = "PENDING"
    target_date: Optional[date] = None
    actual_date: Optional[date] = None
    remarks: Optional[str] = None

class MilestoneCreate(MilestoneBase):
    order_id: int

class MilestoneResponse(MilestoneBase):
    id: int
    order_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class MilestoneUpdate(BaseModel):
    status: Optional[str] = None
    actual_date: Optional[date] = None
    remarks: Optional[str] = None

# Order Approval Schemas
class OrderApprovalBase(BaseModel):
    department: str
    status: str = "PENDING"
    remarks: Optional[str] = None
    sequence: int = 0

class OrderApprovalCreate(OrderApprovalBase):
    order_id: int

class OrderApprovalResponse(OrderApprovalBase):
    id: int
    order_id: int
    approver_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    approver: Optional[UserResponse] = None

    class Config:
        from_attributes = True

class ApprovalDecision(BaseModel):
    decision: ApprovalStatus  # APPROVED, APPROVED_WITH_REMARKS, REJECTED
    remarks: Optional[str] = None
    tentative_production_date: Optional[date] = None
    tentative_release_date: Optional[date] = None
    regulatory_action: Optional[str] = None # New field: "SEND_TO_ARTWORK" or "APPROVE_TO_FINANCE"
    target_department: Optional[str] = None # For SCM override to specify which department's approval to override

# Alert Schemas
class AlertBase(BaseModel):
    alert_type: str
    message: str
    priority: str = "MEDIUM"
    department: Optional[str] = None

class AlertCreate(AlertBase):
    order_id: Optional[int] = None

class AlertResponse(AlertBase):
    id: int
    order_id: Optional[int] = None
    is_read: bool
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Audit Log Schemas
class AuditLogBase(BaseModel):
    action: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    remarks: Optional[str] = None

class AuditLogCreate(AuditLogBase):
    order_id: int
    user_id: int
    ip_address: Optional[str] = None

class AuditLogResponse(AuditLogBase):
    id: int
    order_id: int
    user_id: int
    timestamp: Optional[datetime]
    ip_address: Optional[str]
    user: Optional[UserResponse]

    class Config:
        from_attributes = True

# Order Schemas
class OrderBase(BaseModel):
    order_number: Optional[str] = None
    customer_id: int
    country: str
    po_number: str
    po_date: date
    sku: str
    sales_quantity: int = 0
    free_quantity: int = 0
    quantity: int
    requested_delivery_date: date
    shipping_terms: Optional[str] = None
    import_license_required: bool = False
    import_license_validity: Optional[date] = None
    remarks: Optional[str] = None

class OrderCreate(OrderBase):
    status: Optional[OrderStatus] = None

class OrderResponse(OrderBase):
    id: int
    order_id: str
    status: str
    compliance_status: Optional[str] = None
    compliance_remarks: Optional[str] = None
    tentative_production_date: Optional[date] = None
    tentative_release_date: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    customer: Optional[CustomerResponse] = None
    product: Optional[ProductResponse] = None
    approvals: List[OrderApprovalResponse] = []
    milestones: List[MilestoneResponse] = []
    alerts: List[AlertResponse] = []

    class Config:
        from_attributes = True

class OrderUpdate(BaseModel):
    status: Optional[OrderStatus] = None
    remarks: Optional[str] = None

# Dashboard Schemas
class DashboardStats(BaseModel):
    new_orders: int = 0
    pending_approval: int = 0
    accepted: int = 0
    in_execution: int = 0
    ready_shipment: int = 0
    shipped: int = 0
    delivered: int = 0
    at_risk: int = 0
    expiring_registrations: int = 0
    missing_certificates: int = 0
    pending_approvals: int = 0
    open_orders: int = 0
    delayed: int = 0
    on_time_deliveries: int = 0
    total_delivered: int = 0
    compliance_issues: int = 0

class DashboardData(BaseModel):
    stats: DashboardStats
    recent_orders: List[OrderResponse]
    alerts: List[AlertResponse]

    class Config:
        from_attributes = True

class CanApproveResponse(BaseModel):
    can_approve: bool
    is_scm_override: bool
    is_exports_override: bool = False # New field
    reason: Optional[str] = None
    current_sequence: Optional[int] = None
    pending_department: Optional[str] = None # Department awaiting approval
    waiting_for: Optional[dict] = None # Details of the approval blocking current user

# Compliance Check Result
class ComplianceCheckResult(BaseModel):
    status: str
    remarks: str
    issues: List[str]

class CountryListResponse(BaseModel):
    countries: List[str]


