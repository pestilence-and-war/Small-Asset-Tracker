from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from app.models import Employee, Assignment
from app import db
from app.routes import employees_bp as bp
from datetime import datetime

@bp.route('/')
@login_required
def list_employees():
    if current_user.role != 'admin':
        employees = [current_user.employee]
    else:
        employees = Employee.query.all()
    return render_template('employees.html', employees=employees)

@bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_employee():
    if request.method == 'POST':
        employee = Employee(
            name=request.form['name'],
            email=request.form['email'],
            department=request.form['department']
        )
        db.session.add(employee)
        db.session.commit()
        return render_template('partials/employee_row.html', employee=employee)
    return render_template('add_employee.html')

@bp.route('/<int:id>')
@login_required
def view_employee(id):
    if current_user.role != 'admin' and current_user.employee.id != id:
        flash('You do not have permission to view this page.', 'danger')
        return redirect(url_for('employees.list_employees'))
    employee = Employee.query.get_or_404(id)
    return render_template('employee_details.html', employee=employee)

@bp.route('/<int:id>/history')
@login_required
def employee_history(id):
    if current_user.role != 'admin' and current_user.employee.id != id:
        return jsonify({'error': 'Unauthorized'}), 403
    employee = Employee.query.get_or_404(id)
    # Explicitly filter and sort assignments with return dates
    past_assignments = [a for a in employee.assignments if a.return_date is not None]
    past_assignments.sort(key=lambda x: x.return_date or datetime.min, reverse=True)

    return render_template('partials/employee_history.html', assignments=past_assignments)
