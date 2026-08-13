from __future__ import annotations
from pydantic import BaseModel, Field, validator
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
    order_type: Optional[str] = None

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
    updated_at: Optional[datetime] = None
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
    primary_pm_code: Optional[str] = None
    secondary_pm_code: Optional[str] = None
    leaf_pm_code: Optional[str] = None
    artwork_status: Optional[str] = None

# Product Schemas
class ProductBase(BaseModel):
    sku_code: str
    product_name: str
    category: Optional[str] = None
    country_id: int
    customer: Optional[str] = None
    pack_size: Optional[str] = None
    standard_batch_size: Optional[int] = None
    moq: Optional[int] = None
    primary_pm_code: Optional[str] = None
    secondary_pm_code: Optional[str] = None
    leaf_pm_code: Optional[str] = None
    current_artwork_version: Optional[str] = None
    artwork_status: str = "Not Available"

class RegistrationDetails(BaseModel):
    registration_number: str
    registration_status: str = "Active"
    registration_issue_date: Optional[date] = None
    registration_expiry_date: Optional[date] = None
    remarks: Optional[str] = None

class ProductWithRegistrationCreate(ProductBase):
    registration: RegistrationDetails

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    category: Optional[str] = None
    country_id: int
    customer: Optional[str] = None
    pack_size: Optional[str] = None
    standard_batch_size: Optional[int] = None
    moq: Optional[int] = None
    primary_pm_code: Optional[str] = None
    secondary_pm_code: Optional[str] = None
    leaf_pm_code: Optional[str] = None
    current_artwork_version: Optional[str] = None
    artwork_status: Optional[str] = None
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pm_code_requests: List[PMCodeRequestResponse] = []
    country: Optional["Country"] = None

    class Config:
        from_attributes = True

class ProductSearchItem(BaseModel):
    sku_code: str
    product_name: str

    class Config:
        from_attributes = True

class ProductSearchResponse(BaseModel):
    products: List[ProductSearchItem]

class SearchSuggestion(BaseModel):
    type: str  # e.g., "product", "customer", "order"
    id: str    # e.g., SKU code, customer ID, order ID
    name: str  # e.g., Product Name, Customer Name
    
class SearchSuggestionsResponse(BaseModel):
    suggestions: List[SearchSuggestion]

# Registration Schemas
class RegistrationBase(BaseModel):
    sku: str
    registration_number: str
    registration_status: str = "Active"
    registration_issue_date: Optional[date] = None
    registration_expiry_date: Optional[date] = None
    remarks: Optional[str] = None

    @validator('registration_issue_date', 'registration_expiry_date', pre=True)
    def parse_optional_date(cls, value):
        if value == '':
            return None
        return value

class RegistrationCreateRequest(RegistrationBase):
    country: str # Country name from frontend

class RegistrationCreate(RegistrationBase):
    country_id: int # Country ID for internal use

class RegistrationResponse(RegistrationBase):
    id: int
    country_id: int # Add country_id to response as it's part of the model
    certificate_path: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    country: Optional["Country"] = None

    class Config:
        from_attributes = True

# Customer Schemas
class CountryBase(BaseModel):
    name: str

class CountryCreate(CountryBase):
    pass

class Country(CountryBase):
    id: int

    class Config:
        from_attributes = True

class CustomerBase(BaseModel):
    customer_name: str
    country_id: int

    payment_terms: Optional[str] = None
    agreement_status: Optional[str] = "Pending"
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
    country: Optional["Country"] = None # Relationship

    class Config:
        from_attributes = True

class CustomerUpdate(BaseModel):
    customer_name: Optional[str] = None
    country_id: int
    payment_terms: Optional[str] = None
    agreement_status: Optional[str] = None
    agreement_validity: Optional[date] = None
    is_active: Optional[bool] = None


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
    target_date: Optional[date] = None
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
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True

# Order Schemas
class OrderBase(BaseModel):
    order_number: Optional[str] = None
    customer_id: int
    country_id: int
    po_number: str
    po_date: date
    sku: str
    category: Optional[str] = None
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
    country: Optional["Country"] = None

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

class CategoryListResponse(BaseModel):
    categories: List[str]

class BulkTargetDateItem(BaseModel):
    milestone_id: int
    target_date: Optional[datetime] = None

class BulkTargetDateRequest(BaseModel):
    milestones: List[BulkTargetDateItem]

class MilestoneHistoryResponse(BaseModel):
    id: int
    milestone_id: int
    change_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None

    @validator('old_value', 'new_value', pre=True)
    def convert_date_to_str(cls, v):
        if isinstance(v, date):
            return v.isoformat()
        return v
    changed_by_user: Optional[UserResponse] = None
    changed_at: datetime

    class Config:
        from_attributes = True


ProductResponse.model_rebuild(_types_namespace=globals())
RegistrationResponse.model_rebuild(_types_namespace=globals())
CustomerResponse.model_rebuild(_types_namespace=globals())
OrderResponse.model_rebuild(_types_namespace=globals())




