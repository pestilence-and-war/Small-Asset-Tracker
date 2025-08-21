from flask import render_template, Blueprint, make_response
from flask_login import login_required
from app import db
from app.models import Asset, AssetStatus, AssetType
from sqlalchemy import func
import io
import csv

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def dashboard():
    total_assets = db.session.query(func.count(Asset.id)).scalar()

    assets_by_status = db.session.query(Asset.status, func.count(Asset.id)).group_by(Asset.status).all()

    assets_by_type = db.session.query(Asset.asset_type, func.count(Asset.id)).group_by(Asset.asset_type).all()

    recent_assets = Asset.query.order_by(Asset.id.desc()).limit(5).all()

    return render_template('dashboard.html',
                           title='Dashboard',
                           total_assets=total_assets,
                           assets_by_status=assets_by_status,
                           assets_by_type=assets_by_type,
                           recent_assets=recent_assets)

@dashboard_bp.route('/download_report')
@login_required
def download_report():
    assets = Asset.query.all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['Asset Tag', 'Type', 'Status', 'Assigned To'])

    for asset in assets:
        assigned_to = asset.assignments[0].employee.name if asset.assignments else ''
        writer.writerow([asset.asset_tag, asset.asset_type, asset.status, assigned_to])

    output.seek(0)

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=asset_report.csv"
    response.headers["Content-type"] = "text/csv"

    return response
