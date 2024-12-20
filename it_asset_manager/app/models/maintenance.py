# app/models/maintenance.py
from datetime import datetime, timedelta
from app import db
from enum import Enum

class MaintenanceType(Enum):
    PREVENTIVE = "Preventive"
    CORRECTIVE = "Corrective"
    UPGRADE = "Upgrade"

class MaintenancePriority(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    URGENT = "Urgent"

class MaintenanceRecord(db.Model):
    """Records of completed maintenance activities"""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    maintenance_type = db.Column(db.String(20), nullable=False)
    service_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completion_date = db.Column(db.DateTime)
    service_provider = db.Column(db.String(100))
    description = db.Column(db.Text)
    cost = db.Column(db.Numeric(10, 2))
    parts_replaced = db.Column(db.JSON)  # Store parts and their costs
    next_service_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="Pending")
    notes = db.Column(db.Text)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.maintenance_type == MaintenanceType.PREVENTIVE.value:
            # Set next service date based on asset type and maintenance schedule
            self.calculate_next_service_date()

    def calculate_next_service_date(self):
        schedule = MaintenanceSchedule.query.filter_by(asset_id=self.asset_id).first()
        if schedule and schedule.frequency:
            self.next_service_date = self.service_date + timedelta(days=schedule.frequency)

class MaintenanceSchedule(db.Model):
    """Defines maintenance schedules for assets"""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    maintenance_type = db.Column(db.String(20), nullable=False)
    frequency = db.Column(db.Integer)  # days between maintenance
    last_maintenance = db.Column(db.DateTime)
    next_maintenance = db.Column(db.DateTime)
    checklist = db.Column(db.JSON)  # Store maintenance checklist items
    priority = db.Column(db.String(20))
    
    def update_schedule(self, maintenance_record):
        """Update schedule after maintenance completion"""
        self.last_maintenance = maintenance_record.completion_date
        self.next_maintenance = maintenance_record.next_service_date

class ServiceProvider(db.Model):
    """Maintenance service providers"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    specializations = db.Column(db.JSON)  # List of asset types they can service
    contracts = db.relationship('MaintenanceContract', backref='provider', lazy=True)

class MaintenanceContract(db.Model):
    """Service contracts with providers"""
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('service_provider.id'))
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    terms = db.Column(db.Text)
    cost = db.Column(db.Numeric(10, 2))
    asset_types_covered = db.Column(db.JSON)