from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from app.models import Assignment, Asset, Employee, AssetStatus
from app.models.asset_history import AssetHistory
from app import db, mail
from app.routes import assignments_bp as bp
from datetime import datetime
from flask_mail import Message

def send_assignment_email(assignment):
    msg = Message('New Asset Assignment',
                  sender='noreply@demo.com',
                  recipients=[assignment.employee.email])
    msg.body = f'''Dear {assignment.employee.name},

You have been assigned a new asset:
Asset: {assignment.asset.asset_tag}
Type: {assignment.asset.asset_type}
Assigned on: {assignment.assigned_date.strftime('%Y-%m-%d')}

Please log in to the asset management system to view the details.

Thank you,
IT Department
'''
    mail.send(msg)

@bp.route('/')
@login_required
def list_assignments():
    if current_user.role == 'admin':
        assignments = Assignment.query.all()
    else:
        assignments = Assignment.query.filter_by(employee_id=current_user.employee.id).all()
    return render_template('assignments.html', assignments=assignments)

@bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_assignment():
    if current_user.role != 'admin':
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('assignments.list_assignments'))
    if request.method == 'POST':
        asset = Asset.query.get(request.form['asset_id'])
        employee = Employee.query.get(request.form['employee_id'])
        if asset.status != 'Available':
            return jsonify({'error': 'Asset is not available'}), 400

        assignment = Assignment(
            asset_id=request.form['asset_id'],
            employee_id=request.form['employee_id'],
            assigned_date=datetime.utcnow()
        )

        # Update asset status
        asset.status = 'In Use'

        history_log = AssetHistory(
            asset_id=asset.id,
            user_id=current_user.id,
            event_type='Asset Assigned',
            details=f"Assigned to {employee.name}"
        )

        db.session.add(assignment)
        db.session.add(history_log)
        db.session.commit()
        send_assignment_email(assignment)
        return render_template('partials/assignment_row.html', assignment=assignment)

    available_assets = Asset.query.filter_by(status='Available').all()
    employees = Employee.query.all()
    return render_template('add_assignment.html', available_assets=available_assets, employees=employees)

@bp.route('/<int:id>/return', methods=['POST'])
@login_required
def return_asset(id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    assignment = Assignment.query.get_or_404(id)
    asset = Asset.query.get(assignment.asset_id)

    assignment.return_date = datetime.utcnow()
    asset.status = AssetStatus.AVAILABLE.value

    history_log = AssetHistory(
        asset_id=asset.id,
        user_id=current_user.id,
        event_type='Asset Returned',
        details=f"Returned by {assignment.employee.name}"
    )

    db.session.add(history_log)
    db.session.commit()
    return jsonify({'status': 'success'})
