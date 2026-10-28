import threading
import webview
from app_web import app  # Импортируем наше Flask-приложение из файла app_web.py

def run_server():
    # Запускаем Flask на локальном порту в фоновом потоке
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Запускаем сервер в отдельном потоке, чтобы он не блокировал интерфейс
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    # Создаем нативное окно приложения, которое открывает наш локальный сайт
    webview.create_window(
        title="АРМ: Автоматизированная система специалистов-выпускников",
        url="http://127.0.0.1:5000/",
        width=1150,
        height=800,
        resizable=True
    )
    
    # Запуск графического цикла приложения
    webview.start()