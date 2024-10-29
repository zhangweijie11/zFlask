# blueprints/auth.py
from flask import Blueprint, render_template, request, redirect, url_for

auth_bp = Blueprint('auth', __name__, template_folder='templates',url_prefix="/auth")


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 处理登录逻辑
        return redirect(url_for('home'))
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 处理注册逻辑
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html')
