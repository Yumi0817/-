from flask import Flask, redirect, url_for, flash, render_template, request, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from pytz import timezone
from sqlalchemy import func, case, text
from config import Config
from models import db, User, PunchRecord, LeaveRequest
import re
from datetime import datetime, timedelta
from flask_migrate import Migrate
from markupsafe import Markup

taiwan_tz = timezone('Asia/Taipei')

# 在文件顶部定义这些字典
punch_type_names = {
    'in': '上班',
    'out': '下班',
    'leave': '外出',
    'return': '返回'
}

leave_type_names = {
    'sick': '病假',
    'personal': '事假',
    'compensatory': '補休',
    'annual': '特休',
    'overtime': '加班',
    'parental': '育嬰假'
}

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate = Migrate(app, db)
    
    # 添加自定義過濾器
    @app.template_filter('format_datetime')
    def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
        if value is None:
            return ""
        return value.strftime(format)

    login_manager = LoginManager(app)
    login_manager.login_view = 'login'

    # 配置郵件發送
    mail = Mail(app)

    # 添加 send_email 函數
    def send_email(to, subject, template, **kwargs):
        msg = Message(subject,
                      sender=app.config['MAIL_DEFAULT_SENDER'],
                      recipients=[to] if to else [])
        kwargs['now'] = datetime.now(taiwan_tz)
        msg.body = render_template(template + '.txt', **kwargs)
        msg.html = render_template(template + '.html', **kwargs)
        
        # 檢查並設置默認值
        if not msg.subject:
            msg.subject = "無主題"
        if not msg.sender:
            msg.sender = app.config['MAIL_DEFAULT_SENDER']
        if not msg.recipients:
            app.logger.warning("No recipients specified for email")
            return  # 如果沒有收件人，就不發送郵件
        
        try:
            mail.send(msg)
        except Exception as e:
            app.logger.error(f"Failed to send email: {str(e)}")

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.role in ['admin', '人事', '主管']:
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('punch'))
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                flash('登入成功！')
                # 發送登入通知郵件
                send_email(user.email, '登入通知', 'mail/login_notification', user=user)
                return redirect(url_for('index'))
            flash('無效的電子郵件或密碼')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))


    @app.route('/attendance_query', methods=['GET', 'POST'])
    @login_required
    def attendance_query():
        if request.method == 'POST':
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            selected_leave_type = request.form.get('leave_type', 'all')
        else:
            today = datetime.now(taiwan_tz)
            start_date = today.replace(day=1).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
            selected_leave_type = 'all'

        # 將日期字符串轉換為 datetime 對象
        start_datetime = taiwan_tz.localize(datetime.strptime(start_date, '%Y-%m-%d'))
        end_datetime = taiwan_tz.localize(datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

        # 查詢打卡記錄
        punch_records = PunchRecord.query.filter_by(user_id=current_user.id).filter(
            PunchRecord.punch_time.between(start_datetime, end_datetime)
        ).order_by(PunchRecord.punch_time.desc()).all()

        # 查詢請假記錄
        leave_records_query = LeaveRequest.query.filter_by(user_id=current_user.id).filter(
            db.or_(
                db.and_(LeaveRequest.start_datetime >= start_datetime, LeaveRequest.start_datetime <= end_datetime),
                db.and_(LeaveRequest.end_datetime >= start_datetime, LeaveRequest.end_datetime <= end_datetime)
            )
        )

        if selected_leave_type != 'all':
            leave_records_query = leave_records_query.filter(LeaveRequest.leave_type == selected_leave_type)

        leave_records = leave_records_query.order_by(LeaveRequest.start_datetime.desc()).all()

        return render_template('attendance_query.html',
                               punch_records=punch_records,
                               leave_records=leave_records,
                               punch_type_names=punch_type_names,
                               leave_type_names=leave_type_names,
                               start_date=start_date,
                               end_date=end_date,
                               selected_leave_type=selected_leave_type)










    @app.route('/punch', methods=['GET', 'POST'])
    @login_required
    def punch():
        now = datetime.now(taiwan_tz)
        today = now.date()

        if request.method == 'POST':
            punch_type = request.form.get('punch_type')

            # 检查是否已经打过相同类型的卡
            existing_punch = PunchRecord.query.filter(
                PunchRecord.user_id == current_user.id,
                PunchRecord.punch_type == punch_type,
                db.func.date(PunchRecord.punch_time) == today
            ).first()

            if existing_punch:
                flash(f'您今天已經打過{punch_type_names.get(punch_type, punch_type)}卡了,一天只能打一次。')
                return redirect(url_for('punch'))

            # 外出和返回的時間限制
            if punch_type == 'leave' and (now.hour < 12 or now.hour >= 14):
                flash('外出打卡只能在中午12點到下午2點之間進行')
                return redirect(url_for('punch'))

            if punch_type == 'return' and (now.hour < 12 or now.hour > 14):
                flash('返回打卡必須在下午2點前完成')
                return redirect(url_for('punch'))

            new_punch = PunchRecord(
                user_id=current_user.id,
                username=current_user.username,  # 使用 username
                email=current_user.email,  # 同時記錄 email
                punch_type=punch_type,
                punch_time=now,
                local_time=now
            )
            db.session.add(new_punch)
            db.session.commit()

            flash(f'打卡成功！類型：{punch_type_names.get(punch_type, punch_type)}')
            
            # 發送打卡通知郵件
            send_email(current_user.email, '打卡通知', 'mail/punch_notification', user=current_user, punch_type=punch_type, punch_time=now, punch_type_names=punch_type_names)

        # 獲取今天的打卡記錄
        today_punches = PunchRecord.query.filter(
            PunchRecord.user_id == current_user.id,
            db.func.date(PunchRecord.punch_time) == today
        ).all()

        punched_types = [p.punch_type for p in today_punches]

        return render_template('punch.html', name=current_user.name, punched_types=punched_types, punch_type_names=punch_type_names)
    @app.route('/history')
    @login_required
    def history():
        logs = PunchRecord.query.filter_by(user_id=current_user.id).order_by(PunchRecord.punch_time.desc()).all()
        return render_template('history.html', logs=logs, punch_type_names=punch_type_names)

    @app.route('/add_user', methods=['GET', 'POST'])
    @login_required
    def add_user():
        if current_user.role not in ['管理員', '人事']:
            flash('只有管理員或人事可以新增使用者')
            return redirect(url_for('index'))

        role_mapping = {
            'employee': '員工',
            'manager': '主管',
            'hr': '人事',
            'admin': '管理員'
        }

        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')  # 新增獲取密碼
            name = request.form.get('name')
            role = request.form.get('role')
            hire_date = datetime.strptime(request.form.get('hire_date'), '%Y-%m-%d').date()
            normal_work_start = datetime.strptime(request.form.get('normal_work_start'), '%H:%M').time()
            normal_work_end = datetime.strptime(request.form.get('normal_work_end'), '%H:%M').time()

            if not User.is_valid_email(email):
                flash('無效的電子郵件地址，必須使用 @starkorrnell.org 域名')
            elif User.query.filter_by(email=email).first() or User.query.filter_by(username=username).first():
                flash('該電子郵件地址或用戶名已被使用')
            else:
                chinese_role = role_mapping.get(role, role)
                new_user = User(
                    username=username,
                    email=email,
                    name=name,
                    role=chinese_role,
                    hire_date=hire_date,
                    normal_work_start=normal_work_start,
                    normal_work_end=normal_work_end
                )
                new_user.set_password(password)  # 使用 set_password 方法設置密碼
                db.session.add(new_user)
                db.session.commit()
                flash('新使用者已成功創建')
                return redirect(url_for('admin'))

        return render_template('add_user.html', role_options=role_mapping)


    taiwan_tz = timezone('Asia/Taipei')


    from flask import request, render_template
    from sqlalchemy import or_


    @app.route('/admin', methods=['GET', 'POST'])
    @login_required
    def admin():
        if current_user.role not in ['管理員', '人事', '主管']:
            flash('您沒有權限訪問此頁面。')
            return redirect(url_for('index'))

        page = request.args.get('page', 1, type=int)
        per_page = 10  # 每頁顯示的記錄數

        # 獲取篩選參數
        employee_id = request.args.get('employee', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        # 查詢打卡記錄
        records_query = PunchRecord.query

        if employee_id:
            records_query = records_query.filter(PunchRecord.user_id == employee_id)
        if start_date:
            records_query = records_query.filter(PunchRecord.punch_time >= datetime.strptime(start_date, '%Y-%m-%d'))
        if end_date:
            records_query = records_query.filter(PunchRecord.punch_time <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

        # 添加排序功能
        sort_by = request.args.get('sort_by', 'punch_time')
        sort_order = request.args.get('sort_order', 'desc')
        
        if sort_by == 'punch_time':
            if sort_order == 'asc':
                records_query = records_query.order_by(PunchRecord.punch_time.asc())
            else:
                records_query = records_query.order_by(PunchRecord.punch_time.desc())
        elif sort_by == 'user':
            if sort_order == 'asc':
                records_query = records_query.join(User).order_by(User.name.asc())
            else:
                records_query = records_query.join(User).order_by(User.name.desc())
        
        records_pagination = records_query.paginate(page=page, per_page=per_page, error_out=False)

        # 查詢請假記錄
        leave_requests_query = LeaveRequest.query

        if employee_id:
            leave_requests_query = leave_requests_query.filter(LeaveRequest.user_id == employee_id)
        if start_date:
            leave_requests_query = leave_requests_query.filter(LeaveRequest.start_datetime >= datetime.strptime(start_date, '%Y-%m-%d'))
        if end_date:
            leave_requests_query = leave_requests_query.filter(LeaveRequest.end_datetime <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

        leave_requests_pagination = leave_requests_query.order_by(LeaveRequest.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

        users = User.query.all()

        return render_template('admin.html',
                               users=users,
                               records=records_pagination.items,
                               records_pagination=records_pagination,
                               leave_requests=leave_requests_pagination.items,
                               leave_requests_pagination=leave_requests_pagination,
                               selected_employee=employee_id,
                               start_date=start_date,
                               end_date=end_date,
                               punch_type_names=punch_type_names,
                               leave_type_names=leave_type_names,
                               taiwan_tz=taiwan_tz,
                               sort_by=sort_by,
                               sort_order=sort_order)



    @app.route('/approve_leave/<int:request_id>/<approver_type>', methods=['POST'])
    @login_required
    def approve_leave(request_id, approver_type):
        if current_user.role not in ['管理員', '人事', '主管']:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('admin'))

        leave_request = LeaveRequest.query.get_or_404(request_id)

        if approver_type == 'hr' and current_user.role in ['管理員', '人事']:
            leave_request.hr_approval = 1
        elif approver_type == 'manager' and current_user.role in ['管理員', '主管']:
            leave_request.manager_approval = 1
        else:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('admin'))

        db.session.commit()
        flash('請假申請已批准。')
        return redirect(url_for('admin'))


    @app.route('/reject_leave/<int:request_id>/<approver_type>', methods=['POST'])
    @login_required
    def reject_leave(request_id, approver_type):
        if current_user.role not in ['管理員', '人事', '主管']:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('admin'))

        leave_request = LeaveRequest.query.get_or_404(request_id)

        if approver_type == 'hr' and current_user.role in ['管理員', '人事']:
            leave_request.hr_approval = 2
        elif approver_type == 'manager' and current_user.role in ['管理員', '主管']:
            leave_request.manager_approval = 2
        elif approver_type == 'admin' and current_user.role == 'admin':
            leave_request.hr_approval = 2
            leave_request.manager_approval = 2
        else:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('admin'))

        db.session.commit()

        if approver_type == 'admin':
            flash('請假申請已被管理員駁回。')
        else:
            flash('請假申請已駁回。')

        return redirect(url_for('admin'))




    @app.route('/edit_record/<int:record_id>', methods=['POST'])
    @login_required
    def edit_record(record_id):
        if current_user.role not in ['admin', '人事']:
            flash('只有管理員或人事可以編輯記錄')
            return redirect(url_for('index'))
        record = PunchRecord.query.get_or_404(record_id)
        new_time = request.form.get('new_time')
        if new_time:
            new_time = taiwan_tz.localize(datetime.strptime(new_time, '%Y-%m-%dT%H:%M'))
            record.punch_time = new_time
            db.session.commit()
            flash('記錄已更新')
        return redirect(url_for('admin'))

    @app.route('/delete_record/<int:record_id>', methods=['POST'])
    @login_required
    def delete_record(record_id):
        if current_user.role not in ['admin', '人事','主管']:
            flash('只有管理員或人事可以刪除記錄')
            return redirect(url_for('index'))
        record = PunchRecord.query.get_or_404(record_id)
        db.session.delete(record)
        db.session.commit()
        flash('記錄已刪除')
        return redirect(url_for('admin'))


    from datetime import time


    @app.route('/leave_request', methods=['GET', 'POST'])
    @login_required
    def leave_request():
        if request.method == 'POST':
            leave_type = request.form.get('leave_type')
            start_datetime = taiwan_tz.localize(datetime.strptime(request.form.get('start_datetime'), '%Y-%m-%dT%H:%M'))
            end_datetime = taiwan_tz.localize(datetime.strptime(request.form.get('end_datetime'), '%Y-%m-%dT%H:%M'))
            reason = request.form.get('reason')

            # 檢查日期時間是否有效
            if end_datetime <= start_datetime:
                flash('請輸入正確的日期時間。結束時間必須晚於開始時間。')
                return redirect(url_for('leave_request'))

            # 獲取用戶的正常工作時間，如果未設置則使用默認值
            normal_work_start = current_user.normal_work_start or time(8, 0)  # 默認上班時間 8:00
            normal_work_end = current_user.normal_work_end or time(18, 0)    # 默認下班時間 18:00

            # 計算請假時數
            duration = timedelta()
            current_date = start_datetime.date()
            while current_date <= end_datetime.date():
                if leave_type == 'overtime':
                    # 如果是加班，直接計算整段時間
                    day_start = start_datetime if current_date == start_datetime.date() else taiwan_tz.localize(datetime.combine(current_date, time(0, 0)))
                    day_end = end_datetime if current_date == end_datetime.date() else taiwan_tz.localize(datetime.combine(current_date, time(23, 59, 59)))
                    duration += day_end - day_start
                else:
                    # 其他類型的請假
                    day_start = max(taiwan_tz.localize(datetime.combine(current_date, normal_work_start)), start_datetime)
                    day_end = min(taiwan_tz.localize(datetime.combine(current_date, normal_work_end)), end_datetime)

                    if day_start < day_end:
                        # 扣除中午休息時間
                        lunch_start = taiwan_tz.localize(datetime.combine(current_date, time(12, 0)))
                        lunch_end = taiwan_tz.localize(datetime.combine(current_date, time(14, 0)))

                        if day_start < lunch_start and day_end > lunch_end:
                            # 跨越整個午休時間
                            duration += (lunch_start - day_start) + (day_end - lunch_end)
                        elif day_start < lunch_end and day_end > lunch_end:
                            # 開始時間在午休時間內
                            duration += day_end - lunch_end
                        elif day_start < lunch_start and day_end > lunch_start:
                            # 結束時間在午休時間內
                            duration += lunch_start - day_start
                        else:
                            # 不跨越午休時間
                            duration += day_end - day_start

                current_date += timedelta(days=1)

            duration_hours = duration.total_seconds() / 3600

            # 計算請假天數和小時數
            duration_days = int(duration_hours // 8)
            remaining_hours = duration_hours % 8

            # 格式化請假時間
            if duration_days > 0:
                if remaining_hours > 0:
                    duration_str = f"{duration_days}天{remaining_hours:.1f}小時"
                else:
                    duration_str = f"{duration_days}天"
            else:
                duration_str = f"{duration_hours:.1f}小時"

            deputy_id = request.form.get('deputy')
            handover_notes = request.form.get('handover_notes')

            new_request = LeaveRequest(
                user_id=current_user.id,
                leave_type=leave_type,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                reason=reason,
                duration_days=duration_hours / 8,
                duration_str=duration_str,
                hr_approval=0,
                manager_approval=0,
                deputy_id=deputy_id,
                handover_notes=handover_notes
            )
            db.session.add(new_request)
            db.session.commit()

            # 發送郵件通知
            if current_user.email:
                send_email(current_user.email, '請假申請已提交', 'mail/leave_request_notification',
                           user=current_user, leave_request=new_request, leave_type_names=leave_type_names)

            # 發送郵件給人事
            hr_users = User.query.filter(User.role == '人事').all()
            for hr_user in hr_users:
                if hr_user.email:
                    send_email(hr_user.email, '新的請假申請待審核', 'mail/leave_request_hr_notification',
                               user=current_user, leave_request=new_request, leave_type_names=leave_type_names)

            # 發送郵件給主管
            manager_users = User.query.filter(User.role == '主管').all()
            for manager_user in manager_users:
                if manager_user.email:
                    send_email(manager_user.email, '新的請假申請待審核', 'mail/leave_request_manager_notification',
                               user=current_user, leave_request=new_request, leave_type_names=leave_type_names)

            # 發送郵件給職務代理人
            if deputy_id:
                deputy = User.query.get(deputy_id)
                if deputy and deputy.email:
                    send_email(deputy.email, '您被指定為職務代理人', 'mail/leave_request_deputy_notification',
                               user=current_user, leave_request=new_request, leave_type_names=leave_type_names)

            flash(f'請假申請已提交，等待審核。請假時間：{duration_str}')
            return redirect(url_for('index'))

        users = User.query.filter(User.id != current_user.id).all()
        return render_template('leave_request.html', leave_type_names=leave_type_names, users=users)

    @app.route('/approve_leave/<int:request_id>', methods=['POST'])
    @login_required
    def approve_leave_admin(request_id):
        if current_user.role not in ['admin', '人事', '主管']:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('index'))

        leave_request = LeaveRequest.query.get_or_404(request_id)
        leave_request.status = 'approved'
        db.session.commit()
        flash('請假申請已批准。')
        return redirect(url_for('admin'))

    @app.route('/reject_leave/<int:request_id>', methods=['POST'])
    @login_required
    def reject_leave_admin(request_id):
        if current_user.role not in ['admin', '人事', '主管']:
            flash('您沒有權限執行此操作。')
            return redirect(url_for('index'))

        leave_request = LeaveRequest.query.get_or_404(request_id)
        leave_request.status = 'rejected'
        db.session.commit()
        flash('請假申請已駁回。')
        return redirect(url_for('admin'))


    @app.route('/leave_history')
    @login_required
    def leave_history():
        leave_requests = LeaveRequest.query.filter_by(user_id=current_user.id).order_by(LeaveRequest.created_at.desc()).all()
        return render_template('leave_history.html', leave_requests=leave_requests, leave_type_names=leave_type_names)

    @app.route('/deputy_confirmation')
    @login_required
    def deputy_confirmation():
        deputy_requests = LeaveRequest.query.filter_by(deputy_id=current_user.id, deputy_confirmation=False).all()
        return render_template('deputy_confirmation.html', deputy_requests=deputy_requests, leave_type_names=leave_type_names)

    @app.route('/confirm_deputy/<int:request_id>', methods=['POST'])
    @login_required
    def confirm_deputy(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.deputy_id == current_user.id:
            leave_request.deputy_confirmation = True
            db.session.commit()
            flash('您已確認職務代理。')
        return redirect(url_for('deputy_confirmation'))

    @app.template_filter('max')
    def max_filter(a, b):
        return max(a, b)


    from sqlalchemy import func, case, literal
    from datetime import datetime, timedelta

    @app.route('/leave_statistics', methods=['GET', 'POST'])
    @login_required
    def leave_statistics():
        # 獲取當前日期
        today = datetime.now(taiwan_tz)
        
        # 獲取篩選參數，如果沒有提供，則使用當月第一天和最後一天
        start_date = request.args.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', (today.replace(day=1, month=today.month+1) - timedelta(days=1)).strftime('%Y-%m-%d'))
        selected_leave_type = request.args.get('leave_type', '')
        selected_user_id = request.args.get('user_id', '')

        # 構建 SQLAlchemy 查詢
        query = db.session.query(
            LeaveRequest.user_id,
            LeaveRequest.leave_type,
            func.sum(
                case(
                    (func.lower(LeaveRequest.leave_type) == 'overtime',
                     func.timestampdiff(text('HOUR'), LeaveRequest.start_datetime, LeaveRequest.end_datetime)),
                    else_=func.greatest(
                        func.timestampdiff(text('HOUR'), LeaveRequest.start_datetime, LeaveRequest.end_datetime) -
                        func.greatest(
                            func.least(
                                func.timestampdiff(text('HOUR'),
                                                   func.greatest(LeaveRequest.start_datetime,
                                                                 func.cast(
                                                                     func.concat(func.date(LeaveRequest.start_datetime),
                                                                                 ' 12:00:00'),
                                                                     db.DateTime)),
                                                   func.least(LeaveRequest.end_datetime,
                                                              func.cast(func.concat(func.date(LeaveRequest.end_datetime),
                                                                                ' 14:00:00'),
                                                                        db.DateTime))
                                                   ),
                                2
                            ),
                            0
                        ),
                        0
                    )
                )
            ).label('total_hours')
        ).filter(LeaveRequest.hr_approval == 1, LeaveRequest.manager_approval == 1)

        if current_user.role not in ['管理員', '人事', '主管']:
            query = query.filter(LeaveRequest.user_id == current_user.id)
        elif selected_user_id:
            query = query.filter(LeaveRequest.user_id == selected_user_id)

        query = query.filter(LeaveRequest.start_datetime >= datetime.strptime(start_date, '%Y-%m-%d'))
        query = query.filter(LeaveRequest.end_datetime <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

        if selected_leave_type:
            query = query.filter(LeaveRequest.leave_type == selected_leave_type)

        query = query.group_by(LeaveRequest.user_id, LeaveRequest.leave_type)

        # 執行查詢
        results = query.all()

        # 整理結果
        statistics = {}
        user_names = {}

        for result in results:
            user_id = result.user_id
            leave_type = result.leave_type
            total_hours = float(result.total_hours)

            if user_id not in statistics:
                statistics[user_id] = {lt: 0 for lt in leave_type_names.keys()}
                user = User.query.get(user_id)
                user_names[user_id] = user.name if user else f"使用者 {user_id}"

            statistics[user_id][leave_type] = total_hours

        # 獲取所有用戶（僅管理員、人事和主管可見）
        if current_user.role in ['管理員', '人事', '主管']:
            all_users = User.query.all()
        else:
            all_users = [current_user]

        return render_template('leave_statistics.html',
                               statistics=statistics,
                               user_names=user_names,
                               leave_type_names=leave_type_names,
                               users=all_users,
                               selected_user_id=selected_user_id,
                               start_date=start_date,
                               end_date=end_date,
                               selected_leave_type=selected_leave_type)


    @app.route('/reset_password/<int:user_id>', methods=['GET', 'POST'])
    @login_required
    def reset_password(user_id):
        if current_user.role not in ['管理員', '人事']:
            flash('只有管理員或人事可以重置密碼')
            return redirect(url_for('admin'))

        user = User.query.get_or_404(user_id)

        if request.method == 'POST':
            new_password = request.form.get('new_password')
            if new_password:
                user.set_password(new_password)
                db.session.commit()
                flash(f'{user.name} 的密碼已成功重置')
                return redirect(url_for('admin'))

        return render_template('reset_password.html', user=user)


    @app.route('/user_management')
    @login_required
    def user_management():
        if current_user.role != '管理員':
            flash('只有管理員可以訪問用戶管理頁面')
            return redirect(url_for('index'))
        
        users = User.query.all()
        return render_template('user_management.html', users=users)


    @app.route('/api/dashboard_stats')
    @login_required
    def dashboard_stats():
        today = datetime.now(taiwan_tz).date()
        
        # 獲取今日打卡人數（只計算上班打卡）
        today_punch_count = db.session.query(PunchRecord.user_id).filter(
            db.func.date(PunchRecord.punch_time) == today,
            PunchRecord.punch_type == 'in'
        ).distinct().count()
        
        # 獲取待審核的請假申請數量
        pending_leave_requests = LeaveRequest.query.filter(
            (LeaveRequest.hr_approval == 0) | (LeaveRequest.manager_approval == 0)
        ).count()
        
        # 獲取本月累計請假時數
        first_day_of_month = today.replace(day=1)
        total_leave_hours = db.session.query(db.func.sum(LeaveRequest.duration_days * 8)).filter(
            LeaveRequest.start_datetime >= first_day_of_month,
            LeaveRequest.hr_approval == 1,
            LeaveRequest.manager_approval == 1
        ).scalar() or 0
        
        return jsonify({
            'today_punch_count': today_punch_count,
            'pending_leave_requests': pending_leave_requests,
            'total_leave_hours': float(total_leave_hours)
        })

    @app.route('/api/leave_stats')
    @login_required
    def leave_stats():
        # 獲取過去12個月的請假統計
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        stats = db.session.query(
            func.date_trunc('month', LeaveRequest.start_datetime).label('month'),
            func.sum(LeaveRequest.duration_days).label('total_days')
        ).filter(
            LeaveRequest.start_datetime >= start_date,
            LeaveRequest.start_datetime <= end_date,
            LeaveRequest.status == 'approved'
        ).group_by('month').order_by('month').all()
        
        return jsonify([{'month': s.month.strftime('%Y-%m'), 'days': float(s.total_days)} for s in stats])

    @app.route('/api/punch_stats')
    @login_required
    def punch_stats():
        # 獲取過去7天的打卡統計
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        stats = db.session.query(
            func.date(PunchRecord.punch_time).label('date'),
            func.count(distinct(PunchRecord.user_id)).label('user_count')
        ).filter(
            PunchRecord.punch_time >= start_date,
            PunchRecord.punch_time <= end_date
        ).group_by('date').order_by('date').all()
        
        return jsonify([{'date': s.date.strftime('%Y-%m-%d'), 'count': s.user_count} for s in stats])

    @app.route('/bulk_approve_leave', methods=['POST'])
    @login_required
    def bulk_approve_leave():
        if current_user.role not in ['管理員', '人事', '主管']:
            return jsonify({'status': 'error', 'message': '沒有權限執行此操作'}), 403
        
        request_ids = request.json.get('request_ids', [])
        approver_type = request.json.get('approver_type')
        
        for request_id in request_ids:
            leave_request = LeaveRequest.query.get(request_id)
            if leave_request:
                if approver_type == 'hr' and current_user.role in ['管理員', '人事']:
                    leave_request.hr_approval = 1
                elif approver_type == 'manager' and current_user.role in ['管理員', '主管']:
                    leave_request.manager_approval = 1
        
        db.session.commit()
        return jsonify({'status': 'success', 'message': '批量審批成功'})

    def render_pagination(pagination, endpoint, **kwargs):
        if not pagination.pages:
            return ''

        pages = []
        for page in pagination.iter_pages(left_edge=2, left_current=2, right_current=3, right_edge=2):
            if page:
                if page == pagination.page:
                    pages.append('<li class="active"><span>{}</span></li>'.format(page))
                else:
                    url = url_for(endpoint, page=page, **kwargs)
                    pages.append('<li><a href="{}">{}</a></li>'.format(url, page))
            else:
                pages.append('<li class="disabled"><span>...</span></li>')

        return Markup('''
        <nav aria-label="Page navigation">
            <ul class="pagination">
                {}
            </ul>
        </nav>
        '''.format(''.join(pages)))

    app.jinja_env.globals['render_pagination'] = render_pagination

    return app

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        admin_user = User.query.filter((User.email == 'admin@starkorrnell.org') | (User.username == 'admin')).first()
        if not admin_user:
            admin_user = User(username='admin', email='admin@starkorrnell.org', name='管理員', role='admin')
            admin_user.set_password('admin')  # 請更改為安全的密碼
            db.session.add(admin_user)
            try:
                db.session.commit()
                print("管理員使用者已創建")
            except IntegrityError:
                db.session.rollback()
                print("管理員使用者已存在")
        else:
            print("管理員使用者已存在")

    app.run(debug=True)
