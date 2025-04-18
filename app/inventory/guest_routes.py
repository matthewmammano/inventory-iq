from flask import render_template, abort, request, redirect, url_for, session
from app.inventory import bp
from app.auth.models import User
from app.inventory.models import get_squad_models
from datetime import datetime, timezone

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


@bp.route('/<squad>/')
def index(squad):
    user = User.query.filter_by(username=squad).first()
    if user is None:
        abort(404)
    Item, _ = get_squad_models(squad)
    items = Item.query.order_by(Item.last_accessed.desc().nullslast()).all()
    return render_template('inventory/index.html', items=items, squad=squad)
