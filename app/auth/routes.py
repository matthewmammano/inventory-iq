from flask import request, render_template, redirect, url_for, flash
from flask_login import login_manager, login_user, logout_user, login_required
from app.auth import bp
from app.auth.models import Users
from app import db


# TODO: update placeholder landing page
@bp.route('/')
def landing_page():
    return 'Welcome to the LANDING PAGE'


# Login route
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = Users.query.filter_by(email=email).first()

        # Check if the user exists
        if user is None:
            flash('Invalid email or password.', 'error')
            return redirect(url_for('auth.login'))

        # Check if password is set yet, ask them to set it if not
        if not user.password:
            flash('Please set your password first.', 'info')
            return redirect(url_for('auth.set_password'))
        
        # Check if password is correct
        if user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('guest.index', squad=user.display_name))
        
        # If the password is incorrect, show an error message
        flash('Invalid email or password.', 'error')
        return redirect(url_for('auth.login'))
    
    return render_template('login.html')


# Set password route (for first-time users AND reset password)
@bp.route('/set-password', methods=['GET', 'POST'])
def set_password():
    if request.method == 'POST':
        email = request.form['email']
        new_password = request.form['password']

        # Find the user by email
        user = Users.query.filter_by(email=email).first()
        if user is None:
            flash('Invalid email', 'error')
            return redirect(url_for('auth.set_password'))
        elif user.password:
            flash('Password already set. Please log in.', 'info')
            return redirect(url_for('auth.login'))
        
        user.set_password(new_password)
        db.session.commit()
        flash('Password set successfully. Please log in now.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('set_password.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('auth.login'))