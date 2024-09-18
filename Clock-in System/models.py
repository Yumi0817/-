from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime
import re

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)  # 保留 username
    email = db.Column(db.String(120), unique=True, nullable=False)  # 新增 email
    password_hash = db.Column(db.String(128))
    name = db.Column(db.String(64))
    role = db.Column(db.String(20))
    hire_date = db.Column(db.Date)
    normal_work_start = db.Column(db.Time)
    normal_work_end = db.Column(db.Time)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def is_valid_email(email):
        pattern = r'^[a-zA-Z0-9._%+-]+@starkorrnell\.org$'
        return re.match(pattern, email) is not None

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'name': self.name,
            'role': self.role,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'normal_work_start': self.normal_work_start.isoformat() if self.normal_work_start else None,
            'normal_work_end': self.normal_work_end.isoformat() if self.normal_work_end else None
        }

class PunchRecord(db.Model):
    __tablename__ = 'punch_records'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    username = db.Column(db.String(64), nullable=False)  # 保留 username
    email = db.Column(db.String(120), nullable=False)  # 新增 email
    punch_type = db.Column(db.String(20), nullable=False)
    punch_time = db.Column(db.DateTime(timezone=True), nullable=False)
    local_time = db.Column(db.DateTime, nullable=False)
    user = db.relationship('User', backref='punch_records')

    # 删除email的唯一约束
    __table_args__ = (
        db.UniqueConstraint('user_id', 'punch_type', 'punch_time', name='_user_punch_type_time_uc'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'punch_type': self.punch_type,
            'punch_time': self.punch_time.isoformat(),
            'local_time': self.local_time.isoformat()
        }

class HistoryLog(db.Model):
    __tablename__ = 'history_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='history_logs')

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    leave_type = db.Column(db.String(20), nullable=False)
    start_datetime = db.Column(db.DateTime(timezone=True))
    end_datetime = db.Column(db.DateTime(timezone=True))
    reason = db.Column(db.Text)
    hr_approval = db.Column(db.Integer, default=0)
    manager_approval = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    duration_days = db.Column(db.Float)
    duration_str = db.Column(db.String(20))
    deputy_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    handover_notes = db.Column(db.Text)
    deputy_confirmation = db.Column(db.Boolean, default=False)
    user = db.relationship('User', foreign_keys=[user_id], backref='leave_requests')
    deputy = db.relationship('User', foreign_keys=[deputy_id], backref='deputy_requests')

    @property
    def status(self):
        if self.hr_approval == 1 and self.manager_approval == 1:
            return 'approved'
        elif self.hr_approval == 2 or self.manager_approval == 2:
            return 'rejected'
        else:
            return 'pending'

    @status.setter
    def status(self, value):
        if value == 'approved':
            self.hr_approval = 1
            self.manager_approval = 1
        elif value == 'rejected':
            self.hr_approval = 2
            self.manager_approval = 2
        else:
            self.hr_approval = 0
            self.manager_approval = 0

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'leave_type': self.leave_type,
            'start_datetime': self.start_datetime.isoformat(),
            'end_datetime': self.end_datetime.isoformat(),
            'reason': self.reason,
            'hr_approval': self.hr_approval,
            'manager_approval': self.manager_approval,
            'created_at': self.created_at.isoformat(),
            'duration_days': self.duration_days,
            'duration_str': self.duration_str,
            'deputy_id': self.deputy_id,
            'handover_notes': self.handover_notes,
            'deputy_confirmation': self.deputy_confirmation
        }


