# app/routes/assets.py
from flask import render_template, request, jsonify, flash
from app.models import Asset, AssetStatus, AssetType
from app import db
from app.routes import assets_bp as bp
import qrcode
from io import BytesIO
import base64

@bp.route('/')
def list_assets():
    assets = Asset.query.all()
    return render_template('assets.html', assets=assets)

@bp.route('/add', methods=['GET', 'POST'])
def add_asset():
    if request.method == 'POST':
        try:
            asset = Asset(
                asset_type=request.form['asset_type'],
                asset_tag=request.form['asset_tag']
            )
            db.session.add(asset)
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
def get_asset_qr(asset_tag):
    # Find asset case-insensitively
    asset = Asset.query.filter(Asset.asset_tag.ilike(asset_tag)).first_or_404()
    
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
def view_asset(asset_tag):
    # Find asset case-insensitively
    asset = Asset.query.filter(Asset.asset_tag.ilike(asset_tag)).first_or_404()
    return render_template('asset_details.html', asset=asset)