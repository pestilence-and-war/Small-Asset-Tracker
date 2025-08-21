# app/routes/assets.py
from flask import render_template, request, jsonify, flash
from flask_login import login_required, current_user
from app.models import Asset, AssetStatus, AssetType, Assignment
from app.models.asset_history import AssetHistory
from app.models.custom_field import CustomField, CustomFieldValue
from app import db
from app.routes import assets_bp as bp
import qrcode
from io import BytesIO
import base64

@bp.route('/')
@login_required
def list_assets():
    query = request.args.get('q', '')
    asset_type = request.args.get('asset_type', '')
    status = request.args.get('status', '')

    if current_user.role == 'admin':
        assets_query = Asset.query
    else:
        assets_query = Asset.query.join(Assignment).filter(Assignment.employee_id == current_user.employee.id)

    if query:
        assets_query = assets_query.filter(Asset.asset_tag.ilike(f'%{query}%'))

    if asset_type:
        assets_query = assets_query.filter_by(asset_type=asset_type)

    if status:
        assets_query = assets_query.filter_by(status=status)

    assets = assets_query.all()

    asset_types = [t.value for t in AssetType]
    asset_statuses = [s.value for s in AssetStatus]

    if request.headers.get('HX-Request'):
        return render_template('partials/asset_table.html', assets=assets)

    return render_template('assets.html', assets=assets, asset_types=asset_types, asset_statuses=asset_statuses)

@bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_asset():
    if request.method == 'POST':
        try:
            asset = Asset(
                asset_type=request.form['asset_type'],
                asset_tag=request.form['asset_tag']
            )
            db.session.add(asset)
            db.session.flush()  # Flush to get the asset ID

            for key, value in request.form.items():
                if key.startswith('custom_field_'):
                    field_id = key.split('_')[-1]
                    custom_field_value = CustomFieldValue(
                        asset_id=asset.id,
                        field_id=field_id,
                        value=value
                    )
                    db.session.add(custom_field_value)

            history_log = AssetHistory(
                asset_id=asset.id,
                user_id=current_user.id,
                event_type='Asset Created',
                details=f"Asset {asset.asset_tag} created."
            )
            db.session.add(history_log)
            db.session.commit()
            return render_template('partials/asset_row.html', asset=asset)
        except ValueError as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': 'An error occurred while creating the asset'}), 500

    # For GET requests, pass the valid asset types to the template
    return render_template('add_asset.html', asset_types=[t.value for t in AssetType])

@bp.route('/qr/<asset_tag>')
@login_required
def get_asset_qr(asset_tag):
    # Find asset case-insensitively
    asset = Asset.query.filter(Asset.asset_tag.ilike(asset_tag)).first_or_404()

    if current_user.role != 'admin':
        is_assigned_to_user = False
        for assignment in asset.assignments:
            if assignment.employee_id == current_user.employee.id:
                is_assigned_to_user = True
                break
        if not is_assigned_to_user:
            return jsonify({'error': 'Unauthorized'}), 403

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )

    qr_data = {
        'asset_tag': asset.asset_tag,
        'type': asset.asset_type,
        'details': asset.details,
        'url': f'/assets/{asset.asset_tag}'
    }
    qr.add_data(str(qr_data))
    qr.make(fit=True)

    img_buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(img_buffer, format='PNG')
    img_str = base64.b64encode(img_buffer.getvalue()).decode()

    return render_template('partials/qr_code.html',
                         asset=asset,
                         qr_code=img_str)

@bp.route('/<asset_tag>')
@login_required
def view_asset(asset_tag):
    # Find asset case-insensitively
    asset = Asset.query.filter(Asset.asset_tag.ilike(asset_tag)).first_or_404()

    if current_user.role != 'admin':
        is_assigned_to_user = False
        for assignment in asset.assignments:
            if assignment.employee_id == current_user.employee.id:
                is_assigned_to_user = True
                break
        if not is_assigned_to_user:
            flash('You do not have permission to view this asset.', 'danger')
            return redirect(url_for('assets.list_assets'))

    return render_template('asset_details.html', asset=asset)