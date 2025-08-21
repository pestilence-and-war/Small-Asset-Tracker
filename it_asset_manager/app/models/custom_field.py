from app import db

class CustomField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # e.g., 'text', 'number', 'date'

    def __repr__(self):
        return f"CustomField('{self.name}', '{self.type}')"

class CustomFieldValue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey('custom_field.id'), nullable=False)
    value = db.Column(db.String(500), nullable=False)

    field = db.relationship('CustomField', backref='values')

    def __repr__(self):
        return f"CustomFieldValue('{self.field.name}', '{self.value}')"
