# app/models/__init__.py
from app import db

# Import models after db
from .asset import Asset, AssetStatus, AssetType
from .employee import Employee
from .assignment import Assignment

__all__ = ['Asset', 'AssetStatus', 'AssetType', 'Employee', 'Assignment']