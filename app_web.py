from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import pyodbc
import pandas as pd
import io
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = 'secret_key_for_diploma'

conn_str = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=GraduateSystem;"
    "Trusted_Connection=yes;"
)

# Папка для временного хранения файлов при импорте
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db_connection():
    return pyodbc.connect(conn_str)

# Проверка прав администратора
def is_admin():
    role = session.get('role', '')
    return 'admin' in role.lower() or 'админ' in role.lower()

# Функция логирования действий
def log_action(user_id, action_description):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Audit_Logs (UserID, Action, ActionDate)
            VALUES (?, ?, GETDATE())
        """, (user_id, action_description))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка логирования: {e}")

# Алгоритмическая проверка казахстанского ИИН (12 цифр, дата рождения, контрольный разряд)
def validate_iin(iin: str) -> bool:
    if not iin or not iin.isdigit() or len(iin) != 12:
        return False
    
    year = int(iin[0:2])
    month = int(iin[2:4])
    day = int(iin[4:6])
    century_code = int(iin[6])
    
    if century_code not in [1, 2, 3, 4, 5, 6]:
        return False
        
    if month < 1 or month > 12 or day < 1 or day > 31:
        return False

    weights_1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    s1 = sum(int(iin[i]) * weights_1[i] for i in range(11))
    control_digit = s1 % 11
    
    if control_digit == 10:
        weights_2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]
        s2 = sum(int(iin[i]) * weights_2[i] for i in range(11))
        control_digit = s2 % 11
        if control_digit == 10:
            return False
            
    return control_digit == int(iin[11])

# Авторизация
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.UserID, u.FullName, r.RoleName 
                FROM Users u 
                JOIN Roles r ON u.RoleID = r.RoleID 
                WHERE u.Username = ? AND u.PasswordHash = ?
            """, (username, password))
            user = cursor.fetchone()
            cursor.close()
            conn.close()

            if user:
                session['user_id'] = user[0]
                session['full_name'] = user[1]
                session['role'] = user[2]
                log_action(user[0], f"Успешный вход в систему (Роль: {user[2]})")
                return redirect(url_for('index'))
            else:
                flash('Неверный логин или пароль!', 'danger')
        except Exception as e:
            flash(f'Ошибка БД: {e}', 'danger')

    return render_template('login.html')

# Регистрация
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form['fullname'].strip()
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        if not fullname or not username or not password:
            flash('Заполните все поля!', 'warning')
            return redirect(url_for('register'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT UserID FROM Users WHERE Username = ?", (username,))
            if cursor.fetchone():
                flash('Пользователь с таким логином уже существует!', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('register'))

            cursor.execute("SELECT TOP 1 RoleID FROM Roles WHERE RoleName LIKE '%User%' OR RoleName LIKE '%Operator%' ORDER BY RoleID DESC")
            role_row = cursor.fetchone()
            role_id = role_row[0] if role_row else 2

            cursor.execute("""
                INSERT INTO Users (Username, PasswordHash, FullName, RoleID)
                VALUES (?, ?, ?, ?)
            """, (username, password, fullname, role_id))
            conn.commit()
            cursor.close()
            conn.close()

            flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Ошибка при регистрации: {e}', 'danger')

    return render_template('register.html')

# Главная страница (Студенты + Сводная фильтрация и поиск)
@app.route('/index')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    search_query = request.args.get('q', '').strip()
    group_filter = request.args.get('group_id', '').strip()
    form_filter = request.args.get('study_form', '').strip()
    diploma_filter = request.args.get('diploma_status', '').strip()
    employment_filter = request.args.get('employment_status', '').strip()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            SELECT DISTINCT 
                s.StudentID, s.LastName, s.FirstName, s.MiddleName, s.IIN, s.StudyForm, 
                ISNULL(g.GroupName, 'Нет') AS GroupName,
                ISNULL(d.DiplomaNumber, 'Не выдан') AS DiplomaNumber,
                ISNULL(d.GPA, 0.0) AS GPA,
                CASE 
                    WHEN d.DiplomaNumber IS NULL THEN 'Не выдан'
                    WHEN d.GPA >= 3.5 THEN 'С отличием'
                    ELSE 'Обычный'
                END AS DiplomaStatus,
                CASE 
                    WHEN e.EmploymentID IS NOT NULL THEN 'Трудоустроен'
                    ELSE 'Не трудоустроен'
                END AS EmploymentStatus
            FROM Students s 
            LEFT JOIN Academic_Groups g ON s.GroupID = g.GroupID
            LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
            LEFT JOIN Employment e ON s.StudentID = e.StudentID
            WHERE 1=1
        """
        params = []
        
        if search_query:
            sql += " AND (s.LastName LIKE ? OR s.FirstName LIKE ? OR s.IIN LIKE ?)"
            like_q = f"%{search_query}%"
            params.extend([like_q, like_q, like_q])
            
        if group_filter:
            sql += " AND s.GroupID = ?"
            params.append(int(group_filter))
            
        if form_filter:
            sql += " AND s.StudyForm = ?"
            params.append(form_filter)
            
        if diploma_filter:
            if diploma_filter == 'honors':
                sql += " AND d.GPA >= 3.5 AND d.DiplomaNumber IS NOT NULL"
            elif diploma_filter == 'standard':
                sql += " AND d.GPA < 3.5 AND d.DiplomaNumber IS NOT NULL"
            elif diploma_filter == 'none':
                sql += " AND d.DiplomaNumber IS NULL"
                
        if employment_filter:
            if employment_filter == 'emp':
                sql += " AND e.EmploymentID IS NOT NULL"
            elif employment_filter == 'unemp':
                sql += " AND e.EmploymentID IS NULL"

        sql += " ORDER BY s.StudentID DESC"
        
        cursor.execute(sql, params)
        students = cursor.fetchall()
        
        cursor.execute("SELECT GroupID, GroupName FROM Academic_Groups")
        groups = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM Students")
        total_students = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM Academic_Groups")
        total_groups = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return render_template('index.html', 
                               students=students, 
                               groups=groups, 
                               name=session.get('full_name'),
                               role=session.get('role'),
                               is_admin=is_admin(),
                               total_students=total_students,
                               total_groups=total_groups,
                               search_query=search_query,
                               group_filter=group_filter,
                               form_filter=form_filter,
                               diploma_filter=diploma_filter,
                               employment_filter=employment_filter)
    except Exception as e:
        flash(f'Ошибка фильтрации данных: {e}', 'danger')
        return render_template('index.html', students=[], groups=[], name=session.get('full_name'), role=session.get('role'), is_admin=False, total_students=0, total_groups=0, search_query='')

# Добавление студента с валидацией ИИН
@app.route('/add_student', methods=['POST'])
def add_student():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('index'))

    last = request.form['last_name'].strip()
    first = request.form['first_name'].strip()
    middle = request.form.get('middle_name', '').strip()
    iin = request.form['iin'].strip()
    form = request.form['study_form']
    group_id = request.form['group_id']

    if not validate_iin(iin):
        flash('Ошибка: Введен некорректный ИИН! Проверьте правильность 12 цифр и контрольного разряда.', 'danger')
        return redirect(url_for('index'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT StudentID FROM Students WHERE IIN = ?", (iin,))
        if cursor.fetchone():
            flash('Студент с таким ИИН уже зарегистрирован в базе!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('index'))

        cursor.execute("""
            INSERT INTO Students (LastName, FirstName, MiddleName, IIN, StudyForm, GroupID)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (last, first, middle if middle else None, iin, form, int(group_id)))
        conn.commit()
        cursor.close()
        conn.close()
        
        log_action(session.get('user_id'), f"Добавлен новый студент: {last} {first} (ИИН: {iin})")
        flash('Студент успешно добавлен!', 'success')
    except Exception as e:
        flash(f'Ошибка добавления: {e}', 'danger')

    return redirect(url_for('index'))

# Массовый импорт студентов из Excel
@app.route('/import_excel', methods=['POST'])
def import_excel():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав для выполнения импорта!', 'danger')
        return redirect(url_for('index'))

    if 'excel_file' not in request.files:
        flash('Файл не выбран!', 'warning')
        return redirect(url_for('index'))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash('Файл не выбран!', 'warning')
        return redirect(url_for('index'))

    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        try:
            df = pd.read_excel(filepath)
            conn = get_db_connection()
            cursor = conn.cursor()
            
            success_count = 0
            for index, row in df.iterrows():
                last_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
                first_name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
                middle_name = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) and str(row.iloc[2]) != 'nan' else None
                iin = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''
                study_form = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else 'Очная'
                
                try:
                    group_id = int(row.iloc[5]) if pd.notna(row.iloc[5]) else 1
                except:
                    group_id = 1

                if last_name and first_name and validate_iin(iin):
                    cursor.execute("""
                        INSERT INTO Students (LastName, FirstName, MiddleName, IIN, StudyForm, GroupID)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (last_name, first_name, middle_name, iin, study_form, group_id))
                    success_count += 1

            conn.commit()
            cursor.close()
            conn.close()

            if os.path.exists(filepath):
                os.remove(filepath)

            log_action(session.get('user_id'), f"Массовый импорт из Excel: добавлено студентов: {success_count}")
            flash(f'Импорт завершен успешно! Добавлено студентов: {success_count}', 'success')

        except Exception as e:
            flash(f'Ошибка обработки Excel файла: {e}', 'danger')
    else:
        flash('Неверный формат файла. Загрузите файл формата .xlsx', 'warning')

    return redirect(url_for('index'))

# Редактирование студента с валидацией ИИН
@app.route('/edit_student/<int:student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав для редактирования!', 'danger')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        last = request.form['last_name'].strip()
        first = request.form['first_name'].strip()
        middle = request.form.get('middle_name', '').strip()
        iin = request.form['iin'].strip()
        form = request.form['study_form']
        group_id = request.form['group_id']

        if not validate_iin(iin):
            flash('Ошибка: Введен некорректный ИИН при редактировании!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('edit_student', student_id=student_id))

        try:
            cursor.execute("""
                UPDATE Students 
                SET LastName = ?, FirstName = ?, MiddleName = ?, IIN = ?, StudyForm = ?, GroupID = ?
                WHERE StudentID = ?
            """, (last, first, middle if middle else None, iin, form, int(group_id), student_id))
            conn.commit()
            
            log_action(session.get('user_id'), f"Отредактированы данные студента ID: {student_id} ({last} {first})")
            flash('Данные студента успешно обновлены!', 'success')
        except Exception as e:
            flash(f'Ошибка обновления: {e}', 'danger')
        
        cursor.close()
        conn.close()
        return redirect(url_for('index'))

    cursor.execute("SELECT StudentID, LastName, FirstName, MiddleName, IIN, StudyForm, GroupID FROM Students WHERE StudentID = ?", (student_id,))
    student = cursor.fetchone()
    
    cursor.execute("SELECT GroupID, GroupName FROM Academic_Groups")
    groups = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('edit_student.html', student=student, groups=groups, name=session.get('full_name'), role=session.get('role'), is_admin=is_admin())

# Удаление студента
@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав для удаления!', 'danger')
        return redirect(url_for('index'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Diplomas WHERE StudentID = ?", (student_id,))
        cursor.execute("DELETE FROM Employment WHERE StudentID = ?", (student_id,))
        cursor.execute("DELETE FROM Students WHERE StudentID = ?", (student_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        log_action(session.get('user_id'), f"Удален студент с ID: {student_id}")
        flash('Студент успешно удален из системы.', 'success')
    except Exception as e:
        flash(f'Ошибка удаления: {e}', 'danger')

    return redirect(url_for('index'))

# Журнал аудита действий (Администратор)
@app.route('/audit')
def audit_log():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав для просмотра журнала аудита!', 'danger')
        return redirect(url_for('index'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.LogID, 
                ISNULL(u.FullName, 'Система / Гость') AS FullName, 
                a.Action, 
                a.ActionDate
            FROM Audit_Logs a
            LEFT JOIN Users u ON a.UserID = u.UserID
            ORDER BY a.ActionDate DESC
        """)
        logs = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        logs = []
        flash(f'Ошибка загрузки логов: {e}', 'danger')

    return render_template('audit.html', logs=logs, name=session.get('full_name'), role=session.get('role'), is_admin=is_admin())

# Управление пользователями (Администратор)
@app.route('/users')
def manage_users():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав для просмотра этой страницы!', 'danger')
        return redirect(url_for('index'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.UserID, u.Username, u.FullName, r.RoleName, r.RoleID, u.PasswordHash
            FROM Users u
            JOIN Roles r ON u.RoleID = r.RoleID
            ORDER BY u.UserID ASC
        """)
        users_list = cursor.fetchall()

        cursor.execute("SELECT RoleID, RoleName FROM Roles")
        roles_list = cursor.fetchall()

        cursor.close()
        conn.close()
    except Exception as e:
        users_list = []
        roles_list = []
        flash(f'Ошибка загрузки пользователей: {e}', 'danger')

    return render_template('users.html', 
                           users=users_list, 
                           roles=roles_list, 
                           name=session.get('full_name'), 
                           role=session.get('role'), 
                           is_admin=is_admin())

# Изменение роли пользователя
@app.route('/update_user_role/<int:user_id>', methods=['POST'])
def update_user_role(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('index'))

    new_role_id = request.form.get('role_id')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET RoleID = ? WHERE UserID = ?", (new_role_id, user_id))
        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Изменена роль для пользователя ID: {user_id} на роль ID: {new_role_id}")
        flash('Роль пользователя успешно обновлена!', 'success')
    except Exception as e:
        flash(f'Ошибка при обновлении роли: {e}', 'danger')

    return redirect(url_for('manage_users'))

# Удаление пользователя
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('index'))

    if user_id == session.get('user_id'):
        flash('Вы не можете удалить собственную учетную запись во время сеанса!', 'warning')
        return redirect(url_for('manage_users'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Users WHERE UserID = ?", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Удален пользователь с ID: {user_id}")
        flash('Учетная запись пользователя успешно удалена.', 'success')
    except Exception as e:
        flash(f'Ошибка удаления пользователя: {e}', 'danger')

    return redirect(url_for('manage_users'))

# Личный кабинет и смена пароля
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not current_password or not new_password or not confirm_password:
            flash('Заполните все поля для смены пароля!', 'warning')
            return redirect(url_for('profile'))
            
        if new_password != confirm_password:
            flash('Новый пароль и подтверждение не совпадают!', 'danger')
            return redirect(url_for('profile'))
            
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT UserID FROM Users WHERE UserID = ? AND PasswordHash = ?", (user_id, current_password))
            if not cursor.fetchone():
                flash('Указан неверный текущий пароль!', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('profile'))
                
            cursor.execute("UPDATE Users SET PasswordHash = ? WHERE UserID = ?", (new_password, user_id))
            conn.commit()
            cursor.close()
            conn.close()
            
            log_action(user_id, "Успешно изменен пароль учетной записи")
            flash('Пароль успешно обновлен!', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            flash(f'Ошибка при смене пароля: {e}', 'danger')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.Username, u.FullName, r.RoleName 
            FROM Users u 
            JOIN Roles r ON u.RoleID = r.RoleID 
            WHERE u.UserID = ?
        """, (user_id,))
        user_info = cursor.fetchone()
        
        cursor.execute("""
            SELECT Action, ActionDate 
            FROM Audit_Logs 
            WHERE UserID = ? 
            ORDER BY ActionDate DESC
        """, (user_id,))
        user_logs = cursor.fetchall()
        
        cursor.close()
        conn.close()
    except Exception as e:
        user_info = None
        user_logs = []
        flash(f'Ошибка загрузки профиля: {e}', 'danger')

    return render_template('profile.html', 
                           user_info=user_info, 
                           user_logs=user_logs, 
                           name=session.get('full_name'), 
                           role=session.get('role'), 
                           is_admin=is_admin())

# Печать справки выпускника (веб-версия)
@app.route('/print_student/<int:student_id>')
def print_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                s.StudentID, s.LastName, s.FirstName, s.MiddleName, s.IIN, s.StudyForm,
                ISNULL(g.GroupName, 'Не указана') AS GroupName,
                ISNULL(d.DiplomaNumber, 'Не выдан') AS DiplomaNumber,
                ISNULL(CAST(d.GPA AS VARCHAR), '—') AS GPA,
                CASE WHEN d.IsHonors = 1 THEN 'С отличием' ELSE 'Стандартный' END AS HonorsType,
                ISNULL(e.Companyname, 'Не трудоустроен') AS CompanyName,
                ISNULL(e.Position, '—') AS Position
            FROM Students s
            LEFT JOIN Academic_Groups g ON s.GroupID = g.GroupID
            LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
            LEFT JOIN Employment e ON s.StudentID = e.StudentID
            WHERE s.StudentID = ?
        """, (student_id,))
        student = cursor.fetchone()
        cursor.close()
        conn.close()

        if not student:
            flash('Студент не найден!', 'danger')
            return redirect(url_for('index'))

        return render_template('print_student.html', s=student, name=session.get('full_name'))
    except Exception as e:
        flash(f'Ошибка генерации справки: {e}', 'danger')
        return redirect(url_for('index'))

# Генерация официальной справки выпускника в формате PDF
@app.route('/download_pdf/<int:student_id>')
def download_pdf(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                s.StudentID, s.LastName, s.FirstName, s.MiddleName, s.IIN, s.StudyForm,
                ISNULL(g.GroupName, 'Не указана') AS GroupName,
                ISNULL(d.DiplomaNumber, 'Не выдан') AS DiplomaNumber,
                ISNULL(CAST(d.GPA AS VARCHAR), '—') AS GPA,
                CASE WHEN d.IsHonors = 1 THEN 'С отличием' ELSE 'Стандартный' END AS HonorsType,
                ISNULL(e.Companyname, 'Не трудоустроен') AS CompanyName,
                ISNULL(e.Position, '—') AS Position
            FROM Students s
            LEFT JOIN Academic_Groups g ON s.GroupID = g.GroupID
            LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
            LEFT JOIN Employment e ON s.StudentID = e.StudentID
            WHERE s.StudentID = ?
        """, (student_id,))
        student = cursor.fetchone()
        cursor.close()
        conn.close()

        if not student:
            flash('Студент не найден!', 'danger')
            return redirect(url_for('index'))

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
        elements = []

        font_path = "C:/Windows/Fonts/arial.ttf"
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('Arial', font_path))
            font_name = 'Arial'
        else:
            font_name = 'Helvetica'

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontName=font_name,
            fontSize=16,
            alignment=1,
            spaceAfter=20
        )
        
        body_style = ParagraphStyle(
            'BodyStyle',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=12,
            leading=18
        )

        elements.append(Paragraph("<b>АВТОМАТИЗИРОВАННАЯ ИНФОРМАЦИОННАЯ СИСТЕМА</b>", title_style))
        elements.append(Paragraph("<b>ВЫПУСКНИКИ УНИВЕРСИТЕТА</b>", title_style))
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("<b>ОФИЦИАЛЬНАЯ ВЫПИСКА ИЗ БАЗЫ ДАННЫХ ВЫПУСКНИКОВ</b>", title_style))
        elements.append(Spacer(1, 15))

        data = [
            [Paragraph("<b>ФИО студента:</b>", body_style), Paragraph(f"{student[1]} {student[2]} {student[3] if student[3] else ''}", body_style)],
            [Paragraph("<b>ИИН:</b>", body_style), Paragraph(f"{student[4]}", body_style)],
            [Paragraph("<b>Форма обучения:</b>", body_style), Paragraph(f"{student[5]}", body_style)],
            [Paragraph("<b>Академическая группа:</b>", body_style), Paragraph(f"{student[6]}", body_style)],
            [Paragraph("<b>Номер диплома:</b>", body_style), Paragraph(f"{student[7]}", body_style)],
            [Paragraph("<b>Средний балл (GPA):</b>", body_style), Paragraph(f"{student[8]}", body_style)],
            [Paragraph("<b>Тип диплома:</b>", body_style), Paragraph(f"{student[9]}", body_style)],
            [Paragraph("<b>Трудоустройство:</b>", body_style), Paragraph(f"{student[10]} ({student[11]})", body_style)],
        ]

        t = Table(data, colWidths=[150, 350])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#94a3b8')),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))

        elements.append(t)
        elements.append(Spacer(1, 40))
        
        current_date_str = datetime.now().strftime('%d.%m.%Y')
        elements.append(Paragraph(f"<b>Дата формирования:</b> {current_date_str}", body_style))
        elements.append(Paragraph(f"<b>Ответственный оператор:</b> {session.get('full_name')} ({session.get('role')})", body_style))
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>М.П.</b> _______________________ (подпись)", body_style))

        doc.build(elements)
        buffer.seek(0)

        filename = f"Student_Certificate_{student[1]}.pdf"
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'Ошибка генерации PDF: {e}', 'danger')
        return redirect(url_for('index'))

# Экспорт в Excel
@app.route('/export_excel/<report_type>')
def export_excel(report_type):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        sql = ""
        filename = "report.xlsx"
        
        if report_type == 'students':
            sql = """
                SELECT s.StudentID AS ID, s.LastName AS Фамилия, s.FirstName AS Имя, 
                       s.MiddleName AS Отчество, s.IIN AS ИИН, s.StudyForm AS [Форма обучения], 
                       ISNULL(g.GroupName, 'Нет') AS Группа
                FROM Students s 
                LEFT JOIN Academic_Groups g ON s.GroupID = g.GroupID
            """
            filename = "Students_Report.xlsx"
        elif report_type == 'groups':
            sql = "SELECT GroupID AS [ID группы], GroupName AS [Название группы], AdmissionYear AS [Год поступления], GraduationYear AS [Год выпуска] FROM Academic_Groups"
            filename = "Groups_Report.xlsx"
        elif report_type == 'programs':
            sql = "SELECT ProgramID AS ID, ProgramCode AS [Шифр], ProgramName AS [Название программы], Qualification AS [Квалификация] FROM Programs"
            filename = "Programs_Report.xlsx"
        elif report_type == 'diplomas':
            sql = """
                SELECT s.LastName AS Фамилия, s.FirstName AS Имя, 
                       ISNULL(d.DiplomaNumber, 'Нет') AS [Номер диплома], 
                       ISNULL(CAST(d.GPA AS VARCHAR), '-') AS [GPA]
                FROM Students s
                LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
            """
            filename = "Diplomas_Report.xlsx"
        elif report_type == 'employment':
            sql = """
                SELECT s.LastName AS Фамилия, s.FirstName AS Имя, 
                       ISNULL(e.Companyname, 'Не трудоустроен') AS [Компания], 
                       ISNULL(e.Position, '-') AS [Должность]
                FROM Students s
                LEFT JOIN Employment e ON s.StudentID = e.StudentID
            """
            filename = "Employment_Report.xlsx"
        else:
            flash('Неизвестный тип отчета', 'danger')
            return redirect(url_for('index'))

        df = pd.read_sql(sql, conn)
        conn.close()

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Отчет')
        output.seek(0)

        return send_file(
            output, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, 
            download_name=filename
        )
    except Exception as e:
        flash(f'Ошибка экспорта: {e}', 'danger')
        return redirect(url_for('index'))

# Страница групп
@app.route('/groups')
def groups():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    search_query = request.args.get('q', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if search_query:
            cursor.execute("SELECT GroupID, GroupName, AdmissionYear, GraduationYear FROM Academic_Groups WHERE GroupName LIKE ?", (f"%{search_query}%",))
        else:
            cursor.execute("SELECT GroupID, GroupName, AdmissionYear, GraduationYear FROM Academic_Groups")
        groups_list = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception:
        groups_list = []
    return render_template('groups.html', groups=groups_list, name=session.get('full_name'), role=session.get('role'), is_admin=is_admin(), search_query=search_query)

# Создание новой группы
@app.route('/add_group', methods=['POST'])
def add_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('groups'))

    group_name = request.form.get('group_name', '').strip()
    admission_year = request.form.get('admission_year', '').strip()
    graduation_year = request.form.get('graduation_year', '').strip()

    if not group_name or not admission_year or not graduation_year:
        flash('Заполните название группы, год поступления и год выпуска!', 'warning')
        return redirect(url_for('groups'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT GroupID FROM Academic_Groups WHERE GroupName = ?", (group_name,))
        if cursor.fetchone():
            flash('Группа с таким названием уже существует!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('groups'))

        cursor.execute("""
            INSERT INTO Academic_Groups (GroupName, AdmissionYear, GraduationYear) 
            VALUES (?, ?, ?)
        """, (group_name, int(admission_year), int(graduation_year)))
        
        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Создана новая академическая группа: {group_name} (Поступление: {admission_year}, Выпуск: {graduation_year})")
        flash('Академическая группа успешно создана!', 'success')
    except Exception as e:
        flash(f'Ошибка создания группы: {e}', 'danger')

    return redirect(url_for('groups'))

# Редактирование академической группы
@app.route('/edit_group/<int:group_id>', methods=['POST'])
def edit_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('groups'))

    group_name = request.form.get('group_name', '').strip()
    admission_year = request.form.get('admission_year', '').strip()
    graduation_year = request.form.get('graduation_year', '').strip()

    if not group_name or not admission_year or not graduation_year:
        flash('Заполните все поля группы!', 'warning')
        return redirect(url_for('groups'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Academic_Groups 
            SET GroupName = ?, AdmissionYear = ?, GraduationYear = ?
            WHERE GroupID = ?
        """, (group_name, int(admission_year), int(graduation_year), group_id))
        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Отредактирована группа ID: {group_id} (Название: {group_name})")
        flash('Группа успешно обновлена!', 'success')
    except Exception as e:
        flash(f'Ошибка обновления группы: {e}', 'danger')

    return redirect(url_for('groups'))

# Удаление академической группы
@app.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('groups'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM Students WHERE GroupID = ?", (group_id,))
        count = cursor.fetchone()[0]
        
        if count > 0:
            flash(f'Нельзя удалить группу, так как в ней состоят студенты ({count} чел.)!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('groups'))

        cursor.execute("DELETE FROM Academic_Groups WHERE GroupID = ?", (group_id,))
        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Удалена академическая группа ID: {group_id}")
        flash('Группа успешно удалена.', 'success')
    except Exception as e:
        flash(f'Ошибка удаления группы: {e}', 'danger')

    return redirect(url_for('groups'))

# Программы
@app.route('/programs')
def programs():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    search_query = request.args.get('q', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if search_query:
            cursor.execute("SELECT ProgramID, ProgramCode, ProgramName, Qualification FROM Programs WHERE ProgramCode LIKE ? OR ProgramName LIKE ?", (f"%{search_query}%", f"%{search_query}%"))
        else:
            cursor.execute("SELECT ProgramID, ProgramCode, ProgramName, Qualification FROM Programs")
        prog_list = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception:
        prog_list = []
    return render_template('programs.html', programs=prog_list, name=session.get('full_name'), role=session.get('role'), is_admin=is_admin(), search_query=search_query)

# Дипломы с автоматическим определением статуса (с отличием / стандартный)
@app.route('/diplomas')
def diplomas():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    search_query = request.args.get('q', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if search_query:
            cursor.execute("""
                SELECT s.StudentID, s.LastName, s.FirstName, 
                       ISNULL(d.DiplomaNumber, 'Не выдан') AS DiplomaNumber, 
                       ISNULL(d.GPA, 0.0) AS GPA
                FROM Students s 
                LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
                WHERE s.LastName LIKE ? OR s.FirstName LIKE ? OR d.DiplomaNumber LIKE ?
            """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
        else:
            cursor.execute("""
                SELECT s.StudentID, s.LastName, s.FirstName, 
                       ISNULL(d.DiplomaNumber, 'Не выдан') AS DiplomaNumber, 
                       ISNULL(d.GPA, 0.0) AS GPA
                FROM Students s 
                LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
            """)
        
        raw_diplomas = cursor.fetchall()
        
        diplomas_list = []
        for row in raw_diplomas:
            student_id, last_name, first_name, dip_number, gpa = row
            status = "С отличием" if gpa >= 3.5 and dip_number != 'Не выдан' else ("Не выдан" if dip_number == 'Не выдан' else "Стандартный")
            diplomas_list.append((student_id, last_name, first_name, dip_number, gpa, status))

        cursor.close()
        conn.close()
    except Exception as e:
        diplomas_list = []
        flash(f'Ошибка загрузки дипломов: {e}', 'danger')

    return render_template('diplomas.html', 
                           diplomas=diplomas_list, 
                           name=session.get('full_name'), 
                           role=session.get('role'), 
                           is_admin=is_admin(), 
                           search_query=search_query)

# Обновление или добавление диплома студента
@app.route('/update_diploma/<int:student_id>', methods=['POST'])
def update_diploma(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('diplomas'))

    diploma_number = request.form.get('diploma_number', '').strip()
    gpa_str = request.form.get('gpa', '0').strip().replace(',', '.')

    try:
        gpa = float(gpa_str)
        if not (0.0 <= gpa <= 4.0):
            raise ValueError("GPA должен быть в диапазоне от 0.0 до 4.0")
    except ValueError:
        flash('Ошибка: Некорректное значение GPA (введите число от 0.0 до 4.0)', 'danger')
        return redirect(url_for('diplomas'))

    is_honors = 1 if gpa >= 3.5 else 0
    current_date = datetime.now().strftime('%Y-%m-%d')
    reg_number = f"REG-{student_id}-{datetime.now().strftime('%Y')}"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DiplomaID FROM Diplomas WHERE StudentID = ?", (student_id,))
        dip = cursor.fetchone()

        if dip:
            if diploma_number:
                cursor.execute("""
                    UPDATE Diplomas 
                    SET DiplomaNumber = ?, GPA = ?, IsHonors = ?, RegistrationNumber = ISNULL(RegistrationNumber, ?), IssueDate = ISNULL(IssueDate, ?)
                    WHERE StudentID = ?
                """, (diploma_number, gpa, is_honors, reg_number, current_date, student_id))
            else:
                cursor.execute("DELETE FROM Diplomas WHERE StudentID = ?", (student_id,))
        else:
            if diploma_number:
                cursor.execute("""
                    INSERT INTO Diplomas (StudentID, DiplomaNumber, RegistrationNumber, IssueDate, GPA, IsHonors)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (student_id, diploma_number, reg_number, current_date, gpa, is_honors))

        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Обновлен диплом для студента ID: {student_id} (GPA: {gpa})")
        flash('Данные диплома успешно обновлены!', 'success')
    except Exception as e:
        flash(f'Ошибка сохранения диплома: {e}', 'danger')

    return redirect(url_for('diplomas'))

# Трудоустройство
@app.route('/employment')
def employment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    search_query = request.args.get('q', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if search_query:
            cursor.execute("""
                SELECT s.StudentID, s.LastName, s.FirstName, 
                       ISNULL(e.Companyname, 'Не трудоустроен'), 
                       ISNULL(e.Position, '-')
                FROM Students s 
                LEFT JOIN Employment e ON s.StudentID = e.StudentID
                WHERE s.LastName LIKE ? OR s.FirstName LIKE ? OR e.Companyname LIKE ?
            """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
        else:
            cursor.execute("""
                SELECT s.StudentID, s.LastName, s.FirstName, 
                       ISNULL(e.Companyname, 'Не трудоустроен'), 
                       ISNULL(e.Position, '-')
                FROM Students s 
                LEFT JOIN Employment e ON s.StudentID = e.StudentID
            """)
        employment_list = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception:
        employment_list = []
        
    return render_template('employment.html', employment=employment_list, name=session.get('full_name'), role=session.get('role'), is_admin=is_admin(), search_query=search_query)

# Обновление трудоустройства
@app.route('/update_employment/<int:student_id>', methods=['POST'])
def update_employment(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if not is_admin():
        flash('Недостаточно прав!', 'danger')
        return redirect(url_for('employment'))

    company = request.form.get('company', '').strip()
    position = request.form.get('position', '').strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT EmploymentID FROM Employment WHERE StudentID = ?", (student_id,))
        emp = cursor.fetchone()

        if emp:
            if company:
                cursor.execute("""
                    UPDATE Employment 
                    SET Companyname = ?, Position = ? 
                    WHERE StudentID = ?
                """, (company, position if position else '-', student_id))
            else:
                cursor.execute("DELETE FROM Employment WHERE StudentID = ?", (student_id,))
        else:
            if company:
                cursor.execute("""
                    INSERT INTO Employment (StudentID, Companyname, Position)
                    VALUES (?, ?, ?)
                """, (student_id, company, position if position else '-'))

        conn.commit()
        cursor.close()
        conn.close()

        log_action(session.get('user_id'), f"Обновлено трудоустройство для студента ID: {student_id} (Компания: {company})")
        flash('Данные о трудоустройстве успешно обновлены!', 'success')
    except Exception as e:
        flash(f'Ошибка обновления трудоустройства: {e}', 'danger')

    return redirect(url_for('employment'))

# Статистика и графики
@app.route('/statistics')
def statistics():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM Students")
        total_stu = cursor.fetchone()[0]
        
        cursor.execute("SELECT StudyForm, COUNT(*) FROM Students GROUP BY StudyForm")
        form_stats = [list(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT 
                CASE WHEN e.EmploymentID IS NOT NULL THEN 'Трудоустроены' ELSE 'Не трудоустроены' END AS EmpStatus,
                COUNT(s.StudentID)
            FROM Students s
            LEFT JOIN Employment e ON s.StudentID = e.StudentID
            GROUP BY CASE WHEN e.EmploymentID IS NOT NULL THEN 'Трудоустроены' ELSE 'Не трудоустроены' END
        """)
        emp_stats = [list(row) for row in cursor.fetchall()]

        cursor.execute("SELECT COUNT(*) FROM Diplomas")
        total_dip = cursor.fetchone()[0]

        cursor.execute("""
            SELECT 
                SUM(CASE WHEN GPA >= 3.5 THEN 1 ELSE 0 END) as honors,
                SUM(CASE WHEN GPA >= 3.0 AND GPA < 3.5 THEN 1 ELSE 0 END) as good,
                SUM(CASE WHEN GPA >= 2.5 AND GPA < 3.0 THEN 1 ELSE 0 END) as satisfactory,
                SUM(CASE WHEN GPA < 2.5 THEN 1 ELSE 0 END) as low
            FROM Diplomas
        """)
        gpa_row = cursor.fetchone()
        gpa_stats = [gpa_row[0] or 0, gpa_row[1] or 0, gpa_row[2] or 0, gpa_row[3] or 0] if gpa_row else [0, 0, 0, 0]
        
        cursor.close()
        conn.close()
    except Exception:
        total_stu = 0
        form_stats = []
        emp_stats = []
        total_dip = 0
        gpa_stats = [0, 0, 0, 0]

    return render_template('statistics.html', 
                           total_stu=total_stu, 
                           form_stats=form_stats, 
                           emp_stats=emp_stats,
                           total_dip=total_dip,
                           gpa_stats=gpa_stats,
                           name=session.get('full_name'), 
                           role=session.get('role'), 
                           is_admin=is_admin())

# Выход из системы
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)