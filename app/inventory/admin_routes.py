from flask import render_template, request, redirect, url_for, session, flash
from flask_login import current_user, login_required
from app.inventory import admin_bp as bp
from app.auth.models import Users, UserCategories
from app.inventory.models import Items
from datetime import datetime, timezone
from app import db
from dotenv import load_dotenv
import os
import re
import json

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


@bp.before_request
def check_admin_authorization():
    '''
    Secure all admin routes with the following checks:
    1. User must be logged in (Flask-Login)
    2. Admin session must be valid
    3. Squad parameter must be valid
    '''
    # Skip if it's a static asset or similar
    if request.endpoint and 'static' in request.endpoint:
        return
        
    # Check if user is logged in
    if not current_user.is_authenticated:
        flash('You must be logged in to access this page.', 'warning')
        return redirect(url_for('auth.login'))
        
    # Get squad parameter
    squad = request.view_args.get('squad')
    if not squad:
        flash('Squad name is required.', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify the squad exists in the database
    user = Users.query.filter_by(display_name=squad).first()
    if user is None:
        flash('Invalid squad name. Please try again.')
        return redirect(url_for('auth.login'))
    
    if user.active is False:
        flash('This squad is now inactive. Please contact support.')
        return redirect(url_for('auth.login'))
        
    # Check admin session validity
    if session.get('admin'):
        now = datetime.now(timezone.utc).timestamp()
        admin_last_active = session.get('admin_last_active')
        
        if not admin_last_active or now - admin_last_active > ADMIN_TIMEOUT_SECONDS:
            session.pop('admin', None)
            session.pop('admin_last_active', None)
            flash('Admin session expired. Please log in with your PIN again.', 'warning')
            return redirect(url_for('guest.index', squad=squad))
            
        # Update last active timestamp
        session['admin_last_active'] = now
    else:
        session.pop('admin', None)
        session.pop('admin_last_active', None)
        flash('Admin session not found. Please log in with PIN.', 'warning')
        return redirect(url_for('guest.index', squad=squad))
    
    # Verify the current user belongs to the requested squad
    if current_user.display_name != squad:
        flash('You do not have permission to access this squad.', 'warning')
        return redirect(url_for('auth.login'))


# Admin dashboard (protected)
@bp.route('/<squad>/admin-panel')
def admin_panel(squad):
    return render_template('admin_panel.html', squad=squad, admin=True)


# Admin item viewing page (protected)
@bp.route('/<squad>/admin-panel/view-items')
def admin_view_items(squad):
    items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
    return render_template('admin_view_items.html', squad=squad, items=items, admin=True)


# Admin help page (protected)
@bp.route('/<squad>/help')
def help_page(squad):
    developer_phone = os.getenv('CONTACT_PHONE', 'UNAVAILABLE')
    return render_template('admin_help.html', squad=squad, contact_phone=developer_phone, admin=True)


# Admin move items page (protected)
@bp.route('/<squad>/admin-panel/move-items')
def move_items(squad):
    return render_template('admin_move_items.html', squad=squad, admin=True)


# Admin recount items page (protected)
@bp.route('/<squad>/admin-panel/recount-items')
def recount_items(squad):
    return render_template('admin_recount_items.html', squad=squad, admin=True)


# Admin edit items in table page (protected)
@bp.route('/<squad>/admin-panel/edit-items', methods=['GET', 'POST'])
def save_items(squad):
    if request.method == 'GET':
        items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
        categories = UserCategories.query.filter_by(user_id=current_user.id).all()
        return render_template('admin_edit_items.html', squad=squad, items=items, categories=categories, admin=True)
    
    # Process the JSON data from the form
    items_data = request.form.get('itemsData')
    if not items_data:
        flash("No item data received", "warning")
        return redirect(url_for('admin.admin_view_items', squad=squad))
    
    try:
        items_list = json.loads(items_data)
    except json.JSONDecodeError:
        flash("Invalid item data format", "warning")
        return redirect(url_for('admin.admin_view_items', squad=squad))
    
    # Keep track of existing items to detect deletions
    existing_ids = set(item.id for item in Items.query.filter_by(user_id=current_user.id).all())
    processed_ids = set()
    new_items = []
    error_items = []
    
    # Process each item
    for item_data in items_list:
        name = item_data.get('name', '').strip()
        if not name:
            continue
            
        # Get other fields
        item_id = item_data.get('id')
        category_id = item_data.get('category_id', '').strip()
        increments = item_data.get('increments', '').strip()
        min_quantity = item_data.get('min_quantity', '').strip()
        max_quantity = item_data.get('max_quantity', '').strip()
        quantity = item_data.get('quantity', '').strip()
        image = item_data.get('image', '').strip()
        
        # Validate required fields
        if not category_id or not min_quantity or not max_quantity:
            error_items.append(name)
            continue
            
        # Validate numeric fields
        try:
            min_qty = int(min_quantity)
            max_qty = int(max_quantity)
            qty = int(quantity) if quantity else None
        except ValueError:
            error_items.append(name)
            continue
            
        # Check min < max
        if min_qty > max_qty:
            error_items.append(name)
            continue
            
        # Validate image URL if provided
        if image and not re.match(r'^(https?://)?[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}(/.*)?$', image):
            error_items.append(name)
            continue
            
        # Process existing items vs new items
        if item_id != 'new' and item_id is not None:
            try:
                item_id = int(item_id)
                processed_ids.add(item_id)
                
                # Update existing item
                item = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
                if not item:
                    error_items.append(name)
                    continue
                    
                item.name = name
                item.category_id = category_id
                item.increments = increments
                item.min_quantity = min_qty
                item.max_quantity = max_qty
                item.quantity = qty
                item.image = image if image else None
            except (ValueError, TypeError):
                error_items.append(name)
                continue
        else:
            # Create new item
            try:
                item = Items(
                    category_id=category_id,
                    increments=increments,
                    name=name,
                    min_quantity=min_qty,
                    max_quantity=max_qty,
                    quantity=qty,
                    image=image if image else None,
                    user_id=current_user.id,
                )
                db.session.add(item)
                new_items.append(item)
            except Exception:
                error_items.append(name)
                continue
    
    # Delete items that were removed from the form
    for item_id in existing_ids - processed_ids:
        item_to_delete = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
        if item_to_delete:
            db.session.delete(item_to_delete)
    
    # Commit all changes
    db.session.commit()
    
    # Generate UPCs for new items
    for item in new_items:
        item.upc = Items.generate_upc_from_id(item.id)
    
    db.session.commit()
    
    if error_items:
        flash(f"Some items were not saved due to invalid data: {', '.join(error_items)}", "warning")
    else:
        flash("All items saved successfully!", "success")
    
    return redirect(url_for('admin.admin_view_items', squad=squad))