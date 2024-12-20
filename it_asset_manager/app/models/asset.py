# app/models/asset.py
from app import db
from enum import Enum

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
    
    # Add relationship
    assignments = db.relationship('Assignment', backref='asset', lazy=True)
    
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
    
    def __repr__(self):
        return f'<Asset {self.asset_tag}: {self.asset_type} ({self.status})>'