# app/routes/maintenance.py
from flask import Blueprint, render_template, request, jsonify
from app.models import MaintenanceRecord, MaintenanceSchedule, ServiceProvider
from app import db
from app.models.asset import Asset

bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

@bp.route('/')
def list_maintenance():
    records = MaintenanceRecord.query.order_by(MaintenanceRecord.service_date.desc()).all()
    return render_template('maintenance/list.html', records=records)

@bp.route('/schedule', methods=['GET', 'POST'])
def schedule_maintenance():
    if request.method == 'POST':
        try:
            schedule = MaintenanceSchedule(
                asset_id=request.form['asset_id'],
                maintenance_type=request.form['maintenance_type'],
                frequency=int(request.form['frequency'])
            )
            db.session.add(schedule)
            db.session.commit()
            return jsonify({'status': 'success'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
            
    assets = Asset.query.all()
    return render_template('maintenance/schedule.html', assets=assets)

@bp.route('/record', methods=['GET', 'POST'])
def record_maintenance():
    if request.method == 'POST':
        try:
            record = MaintenanceRecord(
                asset_id=request.form['asset_id'],
                maintenance_type=request.form['maintenance_type'],
                service_provider=request.form['provider'],
                description=request.form['description'],
                cost=request.form.get('cost', 0)
            )
            db.session.add(record)
            
            # Update asset maintenance dates
            asset = Asset.query.get(request.form['asset_id'])
            asset.last_maintenance_date = record.service_date
            
            # Update schedule if exists
            schedule = MaintenanceSchedule.query.filter_by(
                asset_id=asset.id,
                maintenance_type=record.maintenance_type
            ).first()
            if schedule:
                schedule.update_schedule(record)
                asset.next_maintenance_date = schedule.next_maintenance
                
            db.session.commit()
            return render_template('maintenance/partials/record_row.html', record=record)
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
            
    assets = Asset.query.all()
    providers = ServiceProvider.query.all()
    return render_template('maintenance/record.html', assets=assets, providers=providers)

@bp.route('/providers', methods=['GET', 'POST'])
def manage_providers():
    if request.method == 'POST':
        try:
            provider = ServiceProvider(
                name=request.form['name'],
                contact_person=request.form['contact'],
                email=request.form['email'],
                phone=request.form['phone'],
                specializations=request.form.getlist('specializations')
            )
            db.session.add(provider)
            db.session.commit()
            return render_template('maintenance/partials/provider_row.html', provider=provider)
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
            
    providers = ServiceProvider.query.all()
    return render_template('maintenance/providers.html', providers=providers)