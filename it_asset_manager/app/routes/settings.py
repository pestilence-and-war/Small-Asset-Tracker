import os
from flask import render_template, request, jsonify, flash, Blueprint, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models.custom_field import CustomField
from app.forms import CustomFieldForm, EmailSettingsForm

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))

    custom_field_form = CustomFieldForm()
    email_form = EmailSettingsForm()

    if email_form.validate_on_submit() and 'email_submit' in request.form:
        # This is a simplified way to update the .env file.
        # In a real application, you would want a more robust solution.
        with open('.env', 'r') as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if line.startswith('MAIL_SERVER='):
                new_lines.append(f"MAIL_SERVER={email_form.mail_server.data}\n")
            elif line.startswith('MAIL_PORT='):
                new_lines.append(f"MAIL_PORT={email_form.mail_port.data}\n")
            elif line.startswith('MAIL_USE_TLS='):
                new_lines.append(f"MAIL_USE_TLS={'True' if email_form.mail_use_tls.data else 'False'}\n")
            elif line.startswith('MAIL_USERNAME='):
                new_lines.append(f"MAIL_USERNAME={email_form.mail_username.data}\n")
            elif line.startswith('MAIL_PASSWORD='):
                new_lines.append(f"MAIL_PASSWORD={email_form.mail_password.data}\n")
            else:
                new_lines.append(line)

        with open('.env', 'w') as f:
            f.writelines(new_lines)

        flash('Email settings updated successfully. Please restart the application for the changes to take effect.', 'success')
        return redirect(url_for('settings.settings'))

    if request.method == 'GET':
        email_form.mail_server.data = os.environ.get('MAIL_SERVER')
        email_form.mail_port.data = os.environ.get('MAIL_PORT')
        email_form.mail_use_tls.data = os.environ.get('MAIL_USE_TLS') == 'True'
        email_form.mail_username.data = os.environ.get('MAIL_USERNAME')
        email_form.mail_password.data = os.environ.get('MAIL_PASSWORD')

    fields = CustomField.query.all()
    return render_template('settings.html', title='Settings', fields=fields,
                           custom_field_form=custom_field_form, email_form=email_form)

@settings_bp.route('/custom_fields/add', methods=['POST'])
@login_required
def add_custom_field():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    form = CustomFieldForm()
    if form.validate_on_submit():
        field = CustomField(name=form.name.data, type=form.type.data)
        db.session.add(field)
        db.session.commit()
        flash('Custom field created successfully.', 'success')
        return redirect(url_for('settings.settings'))

    fields = CustomField.query.all()
    return render_template('settings.html', title='Settings', fields=fields, form=form)

@settings_bp.route('/custom_fields/<int:id>/edit', methods=['POST'])
@login_required
def edit_custom_field(id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    field = CustomField.query.get_or_404(id)
    form = CustomFieldForm()
    if form.validate_on_submit():
        field.name = form.name.data
        field.type = form.type.data
        db.session.commit()
        flash('Custom field updated successfully.', 'success')
        return redirect(url_for('settings.settings'))

    fields = CustomField.query.all()
    return render_template('settings.html', title='Settings', fields=fields, form=form)

@settings_bp.route('/custom_fields/<int:id>/delete', methods=['POST'])
@login_required
def delete_custom_field(id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    field = CustomField.query.get_or_404(id)
    db.session.delete(field)
    db.session.commit()
    flash('Custom field deleted successfully.', 'success')
    return redirect(url_for('settings.settings'))
