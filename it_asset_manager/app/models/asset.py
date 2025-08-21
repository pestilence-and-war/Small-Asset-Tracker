# app/models/asset.py
from datetime import datetime
from app import db
from enum import Enum
from .maintenance import MaintenanceSchedule, MaintenanceRecord
from .asset_history import AssetHistory
from .custom_field import CustomFieldValue

class AssetStatus(Enum):
    AVAILABLE = "Available"
    IN_USE = "In Use"
    MAINTENANCE = "Maintenance"
    RETIRED = "Retired"

class AssetType(Enum):
    PC_LAPTOP = "PC/Laptop"
    MOBILE = "Mobile Device"
    TABLET = "Tablet"

class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_type = db.Column(db.String(50), nullable=False)
    asset_tag = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default=AssetStatus.AVAILABLE.value)
    details = db.Column(db.JSON)
    maintenance_records = db.relationship('MaintenanceRecord', backref='asset', lazy=True)
    maintenance_schedule = db.relationship('MaintenanceSchedule', backref='asset', lazy=True)
    last_maintenance_date = db.Column(db.DateTime)
    next_maintenance_date = db.Column(db.DateTime)

    # Add relationship
    assignments = db.relationship('Assignment', backref='asset', lazy=True)
    history = db.relationship('AssetHistory', backref='asset', lazy=True)
    custom_field_values = db.relationship('CustomFieldValue', backref='asset', lazy=True)

    def __init__(self, asset_type, asset_tag, status=None, details=None):
        # Validate and standardize asset type
        if isinstance(asset_type, AssetType):
            self.asset_type = asset_type.value
        else:
            try:
                # Try to match the input to an enum value
                matched_type = next(t for t in AssetType if t.value.lower() == asset_type.lower())
                self.asset_type = matched_type.value
            except StopIteration:
                raise ValueError(f"Invalid asset type: {asset_type}")

        # Standardize asset tag (e.g., uppercase, remove extra spaces)
        self.asset_tag = str(asset_tag).strip().upper()

        # Validate and standardize status
        if status:
            if isinstance(status, AssetStatus):
                self.status = status.value
            else:
                try:
                    # Try to match the input to an enum value
                    matched_status = next(s for s in AssetStatus if s.value.lower() == status.lower())
                    self.status = matched_status.value
                except StopIteration:
                    raise ValueError(f"Invalid status: {status}")
        else:
            self.status = AssetStatus.AVAILABLE.value

        self.details = details or {}

    def schedule_maintenance(self, maintenance_type, frequency):
        """Create or update maintenance schedule"""
        schedule = MaintenanceSchedule.query.filter_by(
            asset_id=self.id,
            maintenance_type=maintenance_type
        ).first()

        if not schedule:
            schedule = MaintenanceSchedule(
                asset_id=self.id,
                maintenance_type=maintenance_type,
                frequency=frequency
            )
            db.session.add(schedule)
        else:
            schedule.frequency = frequency

        db.session.commit()
        return schedule

    def get_maintenance_status(self):
        """Get asset's maintenance status"""
        if not self.next_maintenance_date:
            return "No Schedule"

        today = datetime.utcnow()
        if self.next_maintenance_date < today:
            return "Overdue"

        days_until = (self.next_maintenance_date - today).days
        if days_until <= 7:
            return "Due Soon"
        return "On Schedule"

    def __repr__(self):
        return f'<Asset {self.asset_tag}: {self.asset_type} ({self.status})>'
