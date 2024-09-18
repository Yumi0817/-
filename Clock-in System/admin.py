from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models import db, User, PunchRecord, LeaveRequest
from datetime import datetime, timedelta
from sqlalchemy import func
from utils import send_email

admin = Blueprint('admin', __name__)


@admin.route('/dashboard')
@login_required
def dashboard():
    if current_user.role not in ['admin', '人事', '主管']:
        flash('您沒有權限訪問此頁面')
        return redirect(url_for('main.index'))
    return render_template('admin.html')


@admin.route('/user_management')
@login_required
def user_management():
    if current_user.role != 'admin':
        flash('只有管理員可以訪問用戶管理頁面')
        return redirect(url_for('main.index'))

    users = User.query.all()
    return render_template('admin/user_management.html', users=users)


@admin.route('/leave_approval')
@login_required
def leave_approval():
    if current_user.role not in ['admin', '人事', '主管']:
        flash('您沒有權限訪問此頁面')
        return redirect(url_for('main.index'))

    pending_requests = LeaveRequest.query.filter(
        (LeaveRequest.hr_approval == 0) | (LeaveRequest.manager_approval == 0)
    ).all()

    return render_template('admin/leave_approval.html', pending_requests=pending_requests)


@admin.route('/approve_leave/<int:request_id>/<approver_type>', methods=['POST'])
@login_required
def approve_leave(request_id, approver_type):
    if current_user.role not in ['admin', '人事', '主管']:
        flash('您沒有權限執行此操作')
        return redirect(url_for('main.index'))

    leave_request = LeaveRequest.query.get_or_404(request_id)

    if approver_type == 'hr' and current_user.role in ['admin', '人事']:
        leave_request.hr_approval = 1
    elif approver_type == 'manager' and current_user.role in ['admin', '主管']:
        leave_request.manager_approval = 1
    else:
        flash('您沒有權限執行此操作')
        return redirect(url_for('admin.leave_approval'))

    db.session.commit()
    flash('請假申請已批准')
    return redirect(url_for('admin.leave_approval'))


@admin.route('/reject_leave/<int:request_id>/<approver_type>', methods=['POST'])
@login_required
def reject_leave(request_id, approver_type):
    # 駁回請假申請的邏輯...
    pass


@admin.route('/api/dashboard_stats')
@login_required
def dashboard_stats():
    # 獲取儀表板統計數據的邏輯...
    pass

# 其他管理功能路由...
