# app/routes/assignments.py
from flask import render_template, request, jsonify
from app.models import Assignment, Asset, Employee, AssetStatus
from app import db
from app.routes import assignments_bp as bp
from datetime import datetime

@bp.route('/')
def list_assignments():
    assignments = Assignment.query.all()
    return render_template('assignments.html', assignments=assignments)

@bp.route('/add', methods=['GET', 'POST'])
def add_assignment():
    if request.method == 'POST':
        asset = Asset.query.get(request.form['asset_id'])
        if asset.status != 'Available':
            return jsonify({'error': 'Asset is not available'}), 400
            
        assignment = Assignment(
            asset_id=request.form['asset_id'],
            employee_id=request.form['employee_id'],
            assigned_date=datetime.utcnow()
        )
        
        # Update asset status
        asset.status = 'In Use'
        
        db.session.add(assignment)
        db.session.commit()
        return render_template('partials/assignment_row.html', assignment=assignment)
        
    available_assets = Asset.query.filter_by(status='Available').all()
    employees = Employee.query.all()
    return render_template('add_assignment.html', available_assets=available_assets, employees=employees)

@bp.route('/<int:id>/return', methods=['POST'])
def return_asset(id):
    assignment = Assignment.query.get_or_404(id)
    asset = Asset.query.get(assignment.asset_id)
    
    assignment.return_date = datetime.utcnow()
    asset.status = AssetStatus.AVAILABLE.value
    
    db.session.commit()
    return jsonify({'status': 'success'})

