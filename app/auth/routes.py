from flask import request, render_template, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from app.auth import bp
from app.auth.models import User
from app import db
from datetime import datetime, timezone

@bp.route('/')
def hi():
    return 'LANDING PAGE'

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and not user.password:
            return redirect(url_for('auth.set_password'))

        if user is None or not user.password or not check_password_hash(user.password, password):
            flash('Invalid email or password.')
            return redirect(url_for('auth.login'))

        session[f'user_id:{user.username}'] = user.id
        session[f'last_active:{user.username}'] = datetime.now(timezone.utc).timestamp()

        flash('Logged in successfully.')

        return redirect(url_for('inventory.index', squad=user.username))

    return render_template('auth/login.html')

@bp.route('/set-password', methods=['GET', 'POST'])
def set_password():
    if request.method == 'POST':
        email = request.form['email']
        new_password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if user is None:
            flash('Invalid email')
        elif user.password:
            flash('Password already set. Please log in.')
        else:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password set. Please log in.')
            return redirect(url_for('auth.login'))

    return render_template('auth/set_password.html')

@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form['email']
        new_password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('Email not found.')
        else:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password reset. Please log in.')
            return redirect(url_for('auth.login'))
        
    return render_template('auth/reset_password.html')