import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
    SQLALCHEMY_DATABASE_URI = 'mysql://root:milo1034596@localhost:3306/employee_db'
    SQLALCHEMY_BINDS = {
        'employee_db': 'mysql://root:milo1034596@localhost:3306/employee_db',

    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True  # 開啟 SQL 查詢日誌
    
    # 郵件設置
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = 'nzpttr@gmail.com'
    MAIL_PASSWORD = 'jmznigfnjefancsi'  # 替換為您的實際應用程式密碼，不包含空格
    MAIL_DEFAULT_SENDER = ('康乃薾幼兒園打卡出缺勤系統', 'nzpttr@gmail.com')
