
import customtkinter as ctk
import pyodbc
from tkinter import messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Авторизация | АРМ Выпускники")
        self.geometry("400x320")
        self.resizable(False, False)

        self.conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=localhost;"
            "DATABASE=GraduateSystem;"
            "Trusted_Connection=yes;"
        )

        self.label_title = ctk.CTkLabel(self, text="Вход в систему АРМ", font=ctk.CTkFont(size=20, weight="bold"))
        self.label_title.pack(pady=25)

        self.entry_username = ctk.CTkEntry(self, placeholder_text="Логин (например, admin)", width=260, height=35)
        self.entry_username.pack(pady=10)

        self.entry_password = ctk.CTkEntry(self, placeholder_text="Пароль", show="*", width=260, height=35)
        self.entry_password.pack(pady=10)

        self.btn_login = ctk.CTkButton(self, text="Войти", width=260, height=35, command=self.authenticate)
        self.btn_login.pack(pady=20)

    def authenticate(self):
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()

        if not username or not password:
            messagebox.showwarning("Внимание", "Введите логин и пароль!")
            return

        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            query = "SELECT u.UserID, u.FullName, r.RoleName FROM Users u JOIN Roles r ON u.RoleID = r.RoleID WHERE u.Username = ? AND u.PasswordHash = ?"
            cursor.execute(query, (username, password))
            user = cursor.fetchone()
            cursor.close()
            conn.close()

            if user:
                user_id, full_name, role_name = user
                messagebox.showinfo("Успех", f"Добро пожаловать, {full_name}!\nРоль: {role_name}")
                self.destroy()
                
                app = GraduateMainApp()
                app.mainloop()
            else:
                messagebox.showerror("Ошибка", "Неверный логин или пароль!")
        except Exception as e:
            messagebox.showerror("Ошибка БД", f"Не удалось подключиться к базе данных:\n{e}")


class GraduateMainApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("АРМ: Автоматизированная система специалистов-выпускников")
        self.geometry("1050x750")

        self.conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=localhost;"
            "DATABASE=GraduateSystem;"
            "Trusted_Connection=yes;"
        )

        self.groups_dict = {}
        self.create_layout()

    def create_layout(self):
        # Создание системы вкладок
        self.tabview = ctk.CTkTabview(self, width=1000, height=700)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)

        self.tab_students = self.tabview.add("Студенты")
        self.tab_groups = self.tabview.add("Справочник групп")
        self.tab_diplomas = self.tabview.add("Дипломы и Труд.")
        self.tab_analytics = self.tabview.add("Аналитика и Графики")

        # Инициализация содержимого вкладок
        self.init_students_tab()
        self.init_groups_tab()
        self.init_diplomas_tab()
        self.init_analytics_tab()

    # --- Вкладка 1: Студенты ---
    def init_students_tab(self):
        self.title_lbl = ctk.CTkLabel(self.tab_students, text="База данных выпускников", font=ctk.CTkFont(size=18, weight="bold"))
        self.title_lbl.pack(pady=10)

        self.student_textbox = ctk.CTkTextbox(self.tab_students, width=960, height=280, font=("Courier", 11))
        self.student_textbox.pack(pady=5)

        self.btn_refresh_stu = ctk.CTkButton(self.tab_students, text="Обновить список", command=self.load_students)
        self.btn_refresh_stu.pack(pady=5)

        # Форма добавления студента
        form_frame = ctk.CTkFrame(self.tab_students, width=960, height=200)
        form_frame.pack(pady=10, fill="x", padx=10)

        ctk.CTkLabel(form_frame, text="Добавить нового студента", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=3, pady=5)

        self.e_last = ctk.CTkEntry(form_frame, placeholder_text="Фамилия", width=300)
        self.e_last.grid(row=1, column=0, padx=10, pady=5)

        self.e_first = ctk.CTkEntry(form_frame, placeholder_text="Имя", width=300)
        self.e_first.grid(row=1, column=1, padx=10, pady=5)

        self.e_middle = ctk.CTkEntry(form_frame, placeholder_text="Отчество", width=300)
        self.e_middle.grid(row=1, column=2, padx=10, pady=5)

        self.e_iin = ctk.CTkEntry(form_frame, placeholder_text="ИИН (12 цифр)", width=300)
        self.e_iin.grid(row=2, column=0, padx=10, pady=5)

        self.e_form = ctk.CTkEntry(form_frame, placeholder_text="Форма (Очная/Заочная)", width=300)
        self.e_form.grid(row=2, column=1, padx=10, pady=5)

        self.combo_groups = ctk.CTkComboBox(form_frame, values=["Загрузка..."], width=300, state="readonly")
        self.combo_groups.grid(row=2, column=2, padx=10, pady=5)

        self.btn_add_stu = ctk.CTkButton(form_frame, text="Добавить студента", fg_color="green", hover_color="darkgreen", command=self.add_student)
        self.btn_add_stu.grid(row=3, column=0, columnspan=3, pady=10)

        self.load_groups_combo()
        self.load_students()

    def load_groups_combo(self):
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("SELECT GroupID, GroupName FROM Academic_Groups")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            self.groups_dict = {row.GroupName: row.GroupID for row in rows}
            g_names = list(self.groups_dict.keys())
            if g_names:
                self.combo_groups.configure(values=g_names)
                self.combo_groups.set(g_names[0])
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить группы: {e}")

    def load_students(self):
        self.student_textbox.delete("0.1", "end")
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.StudentID, s.LastName, s.FirstName, s.MiddleName, s.IIN, s.StudyForm, g.GroupName
                FROM Students s LEFT JOIN Academic_Groups g ON s.GroupID = g.GroupID
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            header = f"{'ID':<4} | {'Фамилия':<15} | {'Имя':<15} | {'Отчество':<15} | {'ИИН':<13} | {'Форма':<9} | {'Группа':<10}\n"
            header += "-" * 92 + "\n"
            self.student_textbox.insert("end", header)

            for r in rows:
                mid = r.MiddleName if r.MiddleName else ""
                grp = r.GroupName if r.GroupName else ""
                line = f"{r.StudentID:<4} | {r.LastName:<15} | {r.FirstName:<15} | {str(mid):<15} | {r.IIN:<13} | {r.StudyForm:<9} | {str(grp):<10}\n"
                self.student_textbox.insert("end", line)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка загрузки студентов: {e}")

    def add_student(self):
        last = self.e_last.get().strip()
        first = self.e_first.get().strip()
        middle = self.e_middle.get().strip()
        iin = self.e_iin.get().strip()
        form = self.e_form.get().strip()
        g_name = self.combo_groups.get()

        if not last or not first or not iin:
            messagebox.showwarning("Внимание", "Заполните Фамилию, Имя и ИИН!")
            return

        g_id = self.groups_dict.get(g_name)
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Students (LastName, FirstName, MiddleName, IIN, StudyForm, GroupID)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (last, first, middle if middle else None, iin, form if form else 'Очная', g_id))
            conn.commit()
            cursor.close()
            conn.close()

            messagebox.showinfo("Успех", "Студент успешно добавлен!")
            self.e_last.delete(0, 'end')
            self.e_first.delete(0, 'end')
            self.e_middle.delete(0, 'end')
            self.e_iin.delete(0, 'end')
            self.e_form.delete(0, 'end')
            self.load_students()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось добавить студента: {e}")

    # --- Вкладка 2: Справочник групп (Исправлено) ---
    def init_groups_tab(self):
        ctk.CTkLabel(self.tab_groups, text="Управление академическими группами", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        
        self.group_textbox = ctk.CTkTextbox(self.tab_groups, width=960, height=320, font=("Courier", 12))
        self.group_textbox.pack(pady=5)

        btn_g_ref = ctk.CTkButton(self.tab_groups, text="Обновить список групп", command=self.load_groups_list)
        btn_g_ref.pack(pady=5)

        f_frame = ctk.CTkFrame(self.tab_groups, width=960, height=150)
        f_frame.pack(pady=10, fill="x", padx=10)

        self.e_gname = ctk.CTkEntry(f_frame, placeholder_text="Название группы (например, ИС-2201)", width=300)
        self.e_gname.pack(pady=10)

        self.btn_add_group = ctk.CTkButton(f_frame, text="Добавить группу в справочник", fg_color="green", hover_color="darkgreen", command=self.add_group_to_db)
        self.btn_add_group.pack(pady=5)

        self.load_groups_list()

    def load_groups_list(self):
        self.group_textbox.delete("0.1", "end")
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("SELECT GroupID, GroupName FROM Academic_Groups")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            header = f"{'ID':<5} | {'Название группы':<25}\n"
            header += "-" * 35 + "\n"
            self.group_textbox.insert("end", header)

            for r in rows:
                line = f"{r.GroupID:<5} | {r.GroupName:<25}\n"
                self.group_textbox.insert("end", line)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить группы: {e}")

    def add_group_to_db(self):
        gname = self.e_gname.get().strip()
        if not gname:
            messagebox.showwarning("Внимание", "Введите название группы!")
            return
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Academic_Groups (GroupName) VALUES (?)", (gname,))
            conn.commit()
            cursor.close()
            conn.close()

            messagebox.showinfo("Успех", "Группа успешно добавлена!")
            self.e_gname.delete(0, 'end')
            self.load_groups_list()
            self.load_groups_combo()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось добавить группу: {e}")

    # --- Вкладка 3: Дипломы и Трудоустройство ---
    def init_diplomas_tab(self):
        ctk.CTkLabel(self.tab_diplomas, text="Учет дипломных работ и трудоустройства", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        
        self.diploma_textbox = ctk.CTkTextbox(self.tab_diplomas, width=960, height=400, font=("Courier", 11))
        self.diploma_textbox.pack(pady=10)

        btn_dip_ref = ctk.CTkButton(self.tab_diplomas, text="Обновить данные по дипломам", command=self.load_diplomas_data)
        btn_dip_ref.pack(pady=5)
        self.load_diplomas_data()

    def load_diplomas_data(self):
        self.diploma_textbox.delete("0.1", "end")
        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.LastName, s.FirstName, 
                       ISNULL(d.DiplomaTopic, 'Тема не назначена') AS Topic,
                       ISNULL(t.EmploymentStatus, 'Не указано') AS Status
                FROM Students s
                LEFT JOIN Diplomas d ON s.StudentID = d.StudentID
                LEFT JOIN Employment t ON s.StudentID = t.StudentID
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            header = f"{'Фамилия Имя':<25} | {'Тема дипломного проекта':<50} | {'Статус трудоустройства':<20}\n"
            header += "-" * 102 + "\n"
            self.diploma_textbox.insert("end", header)

            for r in rows:
                name = f"{r.LastName} {r.FirstName}"
                line = f"{name:<25} | {str(r.Topic):<50} | {str(r.Status):<20}\n"
                self.diploma_textbox.insert("end", line)
        except Exception as e:
            self.diploma_textbox.insert("end", f"Таблицы дипломов пока пусты или настраиваются. Детали:\n{e}")

    # --- Вкладка 4: Аналитика и Графики ---
    def init_analytics_tab(self):
        ctk.CTkLabel(self.tab_analytics, text="Аналитические отчеты и визуализация", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        
        self.btn_draw = ctk.CTkButton(self.tab_analytics, text="Построить диаграмму распределения", command=self.draw_chart)
        self.btn_draw.pack(pady=5)

        self.chart_frame = ctk.CTkFrame(self.tab_analytics, width=950, height=500)
        self.chart_frame.pack(pady=10, fill="both", expand=True)

    def draw_chart(self):
        for widget in self.chart_frame.winfo_children():
            widget.destroy()

        try:
            conn = pyodbc.connect(self.conn_str)
            cursor = conn.cursor()
            cursor.execute("SELECT StudyForm, COUNT(*) FROM Students GROUP BY StudyForm")
            data = cursor.fetchall()
            cursor.close()
            conn.close()

            forms = [row[0] for row in data] if data else ["Очная"]
            counts = [row[1] for row in data] if data else [0]

            fig, ax = plt.subplots(figsize=(6, 4), dpi=100)
            ax.bar(forms, counts, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
            ax.set_title("Распределение студентов по формам обучения")
            ax.set_ylabel("Количество человек")

            canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(pady=10, fill="both", expand=True)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось построить график: {e}")

if __name__ == "__main__":
    login_app = LoginWindow()
    login_app.mainloop()

