from flask import render_template, abort, session, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.inventory import guest_bp as bp
from app.auth.models import Users
from app.inventory.models import Items
from datetime import datetime, timezone

@bp.before_request
def check_authentication_and_squad():
    """
    Common checks for guest routes:
    1. Reset admin session for guest views
    2. Check if user is logged in for protected routes
    3. Validate squad parameter exists
    """
    # Skip for static assets
    if request.endpoint and 'static' in request.endpoint:
        return
        
    # Reset admin session for all guest routes
    session.pop('admin', None)
    session.pop('admin_last_active', None)
    
    squad = request.view_args.get('squad')
    if not squad:
        flash('Invalid squad name. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    # For all other routes, check login and squad
    if not current_user.is_authenticated:
        flash('You must be logged in to access this page.', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify the squad exists in the database
    user = Users.query.filter_by(display_name=squad).first()
    if user is None:
        flash('Invalid squad name. Please try again.', 'error')
        return redirect(url_for('auth.login'))
    
    if user.active is False:
        flash('This squad is now inactive. Please contact support.', 'warning')
        return redirect(url_for('auth.login'))


@bp.route('/<squad>/')
@login_required
def index(squad):
    '''
    Display the inventory for the given squad to search or scan UPC.
    '''
    # Get the list of items and order them by last_accessed
    items = Items.query.filter_by(user_id=current_user.id).order_by(Items.last_accessed.desc().nullslast()).all()
    return render_template('index.html', items=items, squad=squad, logo_img=current_user.image)


# Admin login page using PIN from Users DB
@bp.route('/<squad>/admin', methods=['GET', 'POST'])
def admin_login(squad):
    if request.method == 'POST':
        password = request.form['password']
        user = Users.query.filter_by(display_name=squad).first()
        correct_password = user.pin

        if user.pin and password == correct_password:
            session['admin'] = True
            session['admin_last_active'] = datetime.now(timezone.utc).timestamp()
            flash('Admin access granted.', 'success')
            return redirect(url_for('admin.admin_panel', squad=squad))
        else:
            flash('Invalid PIN entered. Please try again.', 'error')
            return render_template('admin_login.html', squad=squad, admin=True)
        
    return render_template('admin_login.html', squad=squad, admin=True)
    
