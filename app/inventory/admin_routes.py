from flask import render_template, request, redirect, url_for, session
from app.inventory import bp
from app.auth.models import User
from app.inventory.models import get_squad_models
from datetime import datetime, timezone
from app import db
from app.utils import generate_upc_from_id

USER_TIMEOUT_SECONDS = 86400  # 24 hours
ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


@bp.before_request
def check_squad_validity():
    '''
    Check if the user squad account is logged in and if the session is still valid.
    Also, check if the user is an admin and if the session is still valid.
    If the session is invalid, redirect to appropriate page.
    '''
    squad = request.view_args.get('squad')  # Get the squad from the URL

    if not squad: return

    user_id = session.get(f'user_id:{squad}')  # Get the user ID from the session
    last_active = session.get(f'last_active:{squad}')  # Get the last active timestamp from the session
    now = datetime.now(timezone.utc).timestamp()

    if not user_id or not last_active or now - last_active > USER_TIMEOUT_SECONDS:
        session.clear()
        return redirect(url_for('auth.login'))

    session[f'last_active:{squad}'] = now  # Update the last active timestamp

    user = User.query.get(user_id)
    if not user or user.username != squad:
        session.clear()
        return redirect(url_for('auth.login'))

    if not user.password:
        return redirect(url_for('auth.set_password'))

    if session.get(f'admin:{squad}'):  # Check if the there is an admin session for the squad
        last_active = session.get('admin_last_active:{squad}')

        if not last_active or now - last_active > ADMIN_TIMEOUT_SECONDS:
            session.pop(f'admin:{squad}', None)
            session.pop(f'admin_last_active:{squad}', None)
            return redirect(url_for('inventory.index', squad=squad))

        session[f'admin_last_active:{squad}'] = now


@bp.route('/<squad>/admin', methods=['GET', 'POST'])
def admin_login(squad):
    if request.method == 'POST':
        password = request.form['password']
        if password == '1234':  # ✅ Hardcoded for now
            session[f'admin:{squad}'] = True
            session[f'admin_last_active:{squad}'] = datetime.now(timezone.utc).timestamp()
            return redirect(url_for('inventory.admin_panel', squad=squad))
        else:
            return render_template('inventory/admin_login.html', squad=squad, error='Wrong password')
    return render_template('inventory/admin_login.html', squad=squad)


# Admin dashboard (protected)
@bp.route('/<squad>/admin-panel')
def admin_panel(squad):
    if not session.get('admin'):
        return redirect(url_for('inventory.index', squad=squad))
    return render_template('inventory/admin_panel.html', squad=squad)


@bp.route('/<squad>/admin-panel/items')
def admin_items(squad):
    if not session.get(f'admin:{squad}'):
        return redirect(url_for('inventory.admin_login', squad=squad))

    Item, _ = get_squad_models(squad)
    items = Item.query.order_by(Item.name).all()
    return render_template('inventory/admin_items.html', squad=squad, items=items)


# Help page
@bp.route('/<squad>/help')
def help_page(squad):
    return render_template('inventory/help.html', squad=squad)


@bp.route('/<squad>/admin-panel/edit-items')
def edit_items(squad):
    if not session.get(f'admin:{squad}'):
        return redirect(url_for('inventory.admin_login', squad=squad))

    Item, _ = get_squad_models(squad)
    items = Item.query.order_by(Item.name).all()
    return render_template(
        'inventory/admin_edit_items.html',
        squad=squad,
        items=items)


@bp.route('/<squad>/admin-panel/move-items')
def move_items(squad):
    if not session.get(f'admin:{squad}'):
        return redirect(url_for('inventory.admin_login', squad=squad))
    return render_template('inventory/move_items.html', squad=squad)


@bp.route('/<squad>/admin-panel/recount-items')
def recount_items(squad):
    if not session.get(f'admin:{squad}'):
        return redirect(url_for('inventory.admin_login', squad=squad))
    return render_template('inventory/recount_items.html', squad=squad)


# ADMIN EDITING FEATURES ONLY --------------------
@bp.route('/<squad>/admin-panel/edit-items', methods=['POST'])
def save_items(squad):
    form = request.form
    count = len(form.getlist('name'))

    if count == 0 or form.getlist('name')[0].strip() == '':
        return redirect(url_for('inventory.admin_items', squad=squad))

    Item, _ = get_squad_models(squad)

    # 1. Delete all existing items
    db.session.query(Item).delete()
    db.session.commit()

    # 2. Recreate all items from the form
    new_items = []

    for i in range(count):
        name = form.getlist('name')[i].strip()
        category = form.getlist('category')[i].strip()
        increments = form.getlist('increments')[i].strip()
        image = form.getlist('image')[i].strip()
        threshold = form.getlist('threshold')[i]

        if not (name and category and increments and image and threshold):
            continue  # skip incomplete rows

        item = Item(
            name=name,
            category=category,
            increments=increments,
            image=image,
            threshold=int(threshold)
        )
        db.session.add(item)
        new_items.append(item)

    db.session.commit()  # Assign IDs

    # 3. Generate and assign new UPCs
    for item in new_items:
        item.upc = generate_upc_from_id(item.id)

    db.session.commit()

    return redirect(url_for('inventory.admin_items', squad=squad))
