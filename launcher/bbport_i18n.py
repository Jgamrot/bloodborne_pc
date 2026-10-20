# SPDX-License-Identifier: GPL-2.0-or-later
"""Launcher translations. The Russian text is the key; English is looked up by it.

ui_language in the launcher settings: "ru", "en" or "" (the system locale: Russian for ru_*,
English otherwise).
"""
import os

EN = {
    # Window, pages, buttons
    "Запустить": "Play",
    "Остановить": "Stop",
    "Настройки": "Settings",
    "Журнал": "Log",
    "Не удалось запустить: {}": "Could not start: {}",
    "\n— игра завершилась (код {}) —\n": "\n— the game exited (code {}) —\n",
    "Предупреждение: не удалось прочитать журнал: {}\n":
        "Warning: could not read the log: {}\n",
    # Launcher language
    "Язык лаунчера": "Launcher language",
    "Как в системе": "System",
    "Применится после перезапуска лаунчера, пока игра запущена":
        "Applies after restarting the launcher while the game is running",
    # Game
    "Игра": "Game",
    "Папка игры (CUSA03173)": "Game folder (CUSA03173)",
    "Выбрать папку с eboot.bin": "Choose the folder with eboot.bin",
    "Открыть в файловом менеджере": "Open in the file manager",
    "Папка сохранений": "Saves folder",
    "Выбрать папку сохранений": "Choose the saves folder",
    "Вернуть папку по умолчанию": "Back to the default folder",
    "Язык системы": "System language",
    "Имя охотника": "Hunter name",
    "Папка DLC": "DLC folder",
    "Выбрать папку DLC": "Choose the DLC folder",
    "Открыть папку DLC": "Open the DLC folder",
    "Вернуть папку DLC по умолчанию": "Back to the default DLC folder",
    "По умолчанию: {}": "Default: {}",
    "Найдены сохранения": "Saves found",
    "Сохранений пока нет: игра создаст их здесь": "No saves yet: the game will create them here",
    "не выбрана": "not chosen",
    "Найден eboot.bin": "eboot.bin found",
    "Нет eboot.bin в папке": "No eboot.bin in the folder",
    "Папка игры (с eboot.bin)": "Game folder (with eboot.bin)",
    # Languages
    "Английский": "English",
    "Русский": "Russian",
    "Японский": "Japanese",
    "Французский": "French",
    "Испанский": "Spanish",
    "Немецкий": "German",
    "Итальянский": "Italian",
    # Controls
    "Управление": "Controls",
    "Схема управления": "Control Scheme",
    "Отображение кнопок и раскладка в игре": "Button prompts and input layout",
    "ПК — клавиатура и мышь": "PC — Keyboard & Mouse",
    "Геймпад Xbox": "Xbox Controller",
    "Геймпад PlayStation": "PlayStation Controller",
    "Клавиатурные подсказки отсутствуют в дистрибутиве": "Keyboard prompt images are missing from this copy of the port",
    "Подсказки Xbox отсутствуют в папке модов": "The Xbox prompts are missing from the mods folder",
    # Mods
    "Моды": "Mods",
    "Распакуйте каждый мод в отдельную папку (с dvdroot_ps4 или сразу с chr/, parts/ и т. п.). "
    "При совпадении файлов побеждает мод ниже в списке. Применяется при запуске.":
        "Extract each mod into its own folder (with dvdroot_ps4, or chr/, parts/, ... directly). "
        "When files collide, the mod lower in the list wins. Applied at start.",
    "Загружать моды": "Load mods",
    "Папка модов": "Mods folder",
    "Выбрать папку модов": "Choose the mods folder",
    "Открыть папку модов": "Open the mods folder",
    "Обновить список": "Refresh the list",
    "Загрузить раньше": "Load earlier",
    "Загрузить позже": "Load later",
    "Модов нет": "No mods",
    # Patches
    "Сторонние патчи": "Third-party patches",
    "XML-патчи в формате shadPS4 для версии 01.09 из папки патчей. Применяются при запуске.":
        "shadPS4-format XML patches for version 01.09 from the patches folder. Applied at start.",
    "Папка патчей": "Patches folder",
    "Выбрать папку патчей": "Choose the patches folder",
    "Открыть папку патчей": "Open the patches folder",
    "Патчей нет": "No patches",
    "Автор: {}": "Author: {}",
    # Screen
    "Экран": "Display",
    "Разрешение вывода": "Output resolution",
    "Апскейлер дорисовывает кадр; Steam Deck — 720p": "The upscaler fills the frame; Steam Deck: 720p",
    "Позиция HUD": "HUD position",
    "Ультраширокие экраны: элементы у краёв или в центре 16:9":
        "Ultrawide screens: HUD elements at the edges or in the centred 16:9 area",
    "У краёв экрана (100%)": "Screen edges (100%)",
    "Посередине (50%)": "Halfway (50%)",
    "По центру (16:9)": "Centred (16:9)",
    "Полноэкранный режим": "Fullscreen",
    "Смена разрешения на лету": "Live resolution changes",
    "Без перезапуска, но медленнее на Steam Deck и старых GPU":
        "No restart needed, but slower on the Steam Deck and older GPUs",
    "Авто (по видеокарте)": "Auto (by GPU)",
    "Выключена (быстрее)": "Off (faster)",
    "Включена": "On",
    "Режим показа кадров": "Present mode",
    "Разрешить HDR": "Allow HDR",
    # Upscaler
    "Апскейлер": "Upscaler",
    "Хранится в bbport.ini; в игре меняется через меню (Insert или L3+R3)":
        "Stored in bbport.ini; in game, change it in the menu (Insert or L3+R3)",
    "TAA (нативное сглаживание)": "TAA (native anti-aliasing)",
    "Выключен": "Off",
    "Пресет": "Preset",
    "Резкость (RCAS)": "Sharpening (RCAS)",
    "Сила резкости": "Sharpness",
    "Векторы движения объектов": "Object motion vectors",
    "Меньше гостинга на персонажах; стоит около 10% FPS": "Less ghosting on characters; costs about 10% FPS",
    "Показывать FPS": "Show FPS",
    "Ассеты найдены": "Assets found",
    "Нет ассетов: tools/fetch_fsr4_assets.sh": "No assets: tools/fetch_fsr4_assets.sh",
    "Нет ассетов (скачайте в строке ниже)": "No assets (download in the row below)",
    "Ассеты FSR 4": "FSR 4 assets",
    "Скачать ассеты": "Download assets",
    "Проверить": "Verify",
    "Не поддерживается": "Unsupported",
    "Загрузка: {} из {}...": "Downloading: {} of {}...",
    "Установлены: {} файлов в fsr4_shaders": "Installed: {} files in fsr4_shaders",
    "Отсутствует {} из {} файлов в fsr4_shaders": "Missing {} of {} files in fsr4_shaders",
    "Видеокарта не поддерживает FSR 4 (требуется INT8 dot product)": "GPU does not support FSR 4 (INT8 dot product required)",
    "Ошибка загрузки FSR 4: {}": "FSR 4 download failed: {}",
    "Ассеты для выбранного режима найдены": "Assets for the selected mode found",
    "{}. Установите полный набор fsr4_411 в {}.": "{}. Install the full fsr4_411 set into {}.",
    "Сглаживание в разрешении вывода без модели FSR": "Anti-aliasing at the output resolution, no FSR model",
    "DLSS работает только на видеокартах NVIDIA GeForce RTX":
        "DLSS only works on NVIDIA GeForce RTX GPUs",
    "Некорректное разрешение вывода": "Invalid output resolution",
    "Нет или повреждён файл {}": "Missing or damaged file {}",
    "Нативное разрешение: {} × {}": "Native resolution: {} × {}",
    "Внутреннее разрешение: {} × {} ({:.1f}×) → вывод {} × {}":
        "Internal resolution: {} × {} ({:.1f}×) → output {} × {}",
    "Внутреннее разрешение: {} × {} (ручной ввод) → вывод {} × {}":
        "Internal resolution: {} × {} (custom) → output {} × {}",
    # Effects
    "Эффекты игры": "Game effects",
    "Патчи игры, применяются при запуске": "Game patches, applied at start",
    "Детализация моделей": "Model detail",
    "Как в игре": "As in the game",
    "Максимальная (-2)": "Highest (-2)",
    "Ниже (1)": "Lower (1)",
    "Минимальная (2)": "Lowest (2)",
    "Хроматическая аберрация": "Chromatic aberration",
    "Глубина резкости (DoF)": "Depth of field (DoF)",
    "Размытие в движении": "Motion blur",
    "Затенение SSAO": "SSAO",
    "Собственное сглаживание игры": "The game's own anti-aliasing",
    "Тени от динамических источников": "Dynamic light shadows",
    "Отражения SSR (не было в игре)": "SSR reflections (not in the original game)",
    "Пропуск заставок при запуске": "Skip the intro videos",
    "Свободная камера (Cross + L3 / Space + Z)": "Free camera (Cross + L3 / Space + Z)",
    "Debug menu (левый touchpad / Tab; нужны шрифты)": "Debug menu (left touchpad / Tab; needs fonts)",
    "Установите DbgFont14h.ccm и DbgFont14h.tpf в dvdroot_ps4/font из мода Nexus #253":
        "Install DbgFont14h.ccm and DbgFont14h.tpf into dvdroot_ps4/font from Nexus mod #253",
    # Enhancements
    "Улучшения (PC)": "PC enhancements",
    "Игровые файлы создаются при запуске; выключено — игра как в оригинале":
        "Game files are made at start; off means the game as it shipped",
    "Зеркало в Сне охотника: смена внешности": "Hunter's Dream mirror: change appearance",
    "Два захватчика в поздних локациях": "Two invaders in the late areas",
    "Перерождение у Алтаря отчаяния": "Rebirth at the Altar of Despair",
    "Фонари: повышение уровня и хранилище": "Lamps: Level Up and Storage",
    "Повторные бои с боссами у фонарей": "Boss rematches at their lamps",
    # Cheats and tweaks
    "Читы и твики": "Cheats and tweaks",
    "Патчи игры 1.09: сложность, физика и камера": "Game patches for 1.09: difficulty, physics and camera",
    "Бессмертие (здоровье не ниже 1 HP)": "Never die (health stays at 1 HP or above)",
    "Враги не видят вас": "Enemies cannot see you",
    "Враги не слышат вас": "Enemies cannot hear you",
    "Rally не угасает": "Rally never decays",
    "Управление выбранным врагом (R3)": "Control the targeted enemy (R3)",
    "Без Rally": "No Rally",
    "Камера дальше от персонажа": "Camera further from the character",
    "Без автоповорота камеры при движении": "No camera auto-rotation while moving",
    "Бег при меньшем наклоне стика": "Run with less stick tilt",
    "Физика тел Dark Souls": "Dark Souls-style ragdoll physics",
    # Frame rate
    "Частота кадров": "Frame rate",
    "Режим": "Mode",
    "Какой патч частоты кадров применить к игре": "Which frame rate patch to apply to the game",
    "Без ограничения (патч)": "Unlocked (patch)",
    "30 (как на PS4)": "30 (as on PS4)",
    "Ограничение FPS": "FPS limit",
    "0 — по частоте экрана (не выше 120 Гц); укажите число, чтобы ограничить иначе":
        "0: the display refresh rate (up to 120 Hz); set a number for another limit",
    # Performance
    "Производительность": "Performance",
    "Двухстадийный конвейер GPU": "Two-stage GPU pipeline",
    "Быстрее на 20–30%; при нестабильности выключите": "20–30% faster; turn off if unstable",
    "Авто (8+ потоков)": "Auto (8+ threads)",
    "Включён": "On",
    "Выключен (стабильнее)": "Off (more stable)",
    "Чтение данных GPU процессором": "GPU data readbacks by the CPU",
    "Relaxed (по умолчанию)": "Relaxed (default)",
    "Выключены": "Off",
    # Redesigned graphics sections & badges
    "1. Рендеринг и разрешение": "1. Rendering and Resolution",
    "Разрешение вывода, режим отображения и синхронизация кадров":
        "Output resolution, display mode, and frame presentation",
    "2. Апскейлинг и реконструкция": "2. Upscaling and Temporal Reconstruction",
    "Реконструкция изображения из пониженного разрешения рендеринга":
        "Image reconstruction from lower internal render resolutions",
    "Предупреждение: FSR 4 на RX 6600M (RDNA 2)": "Warning: FSR 4 on RX 6600M (RDNA 2)",
    "Experimental on this GPU. AMD Radeon RX 6600M is RDNA 2. FSR 4 may run significantly slower or less reliably than FSR 3.1. Performance is not guaranteed. If you experience frame drops, stuttering, or instability, switch to FSR 3.1.":
        "Experimental on this GPU. AMD Radeon RX 6600M is RDNA 2. FSR 4 may run significantly slower or less reliably than FSR 3.1. Performance is not guaranteed. If you experience frame drops, stuttering, or instability, switch to FSR 3.1.",
    "FSR 4 [Experimental ⚠️]": "FSR 4 [Experimental ⚠️]",
    "FSR 4.1.1 [Experimental ⚠️]": "FSR 4.1.1 [Experimental ⚠️]",
    "FSR 3.1 [Рекомендуется]": "FSR 3.1 [Recommended]",
    "FSR 3": "FSR 3.1 [Recommended]",
    "FSR 4": "FSR 4",
    "FSR 4.1.1": "FSR 4.1.1",
    "3. Качество изображения и резкость": "3. Image Quality and Sharpening",
    "Повышение четкости и графические эффекты рендеринга":
        "Sharpening filter and in-game post-processing effects",
    "Резкость (RCAS) [Применяется сразу]": "Sharpening (RCAS) [Immediate]",
    "AMD FidelityFX Robust Contrast Adaptive Sharpening; применяется сразу":
        "AMD FidelityFX Robust Contrast Adaptive Sharpening; applies immediately",
    "Сила резкости [Применяется сразу]": "Sharpness [Immediate]",
    "Коэффициент 0.0–2.0 (по умолчанию 0.50); применяется сразу":
        "Sharpness amount 0.0–2.0 (default 0.50); applies immediately",
    "4. Совместимость и конвейер GPU": "4. Compatibility and GPU Pipeline",
    "Низкоуровневые параметры Vulkan; при нестабильности выключите":
        "Low-level Vulkan pipeline and synchronization settings",
    "5. Производительность и диагностика": "5. Performance and Diagnostics",
    "Ограничение частоты кадров и сбор телеметрии":
        "Frame limiter and telemetry logs",
    "Показывать FPS [Применяется сразу]": "Show FPS [Immediate]",
    "Встроенный счетчик кадров в левом верхнем углу":
        "Built-in overlay frame rate counter",
    "ВНИМАНИЕ: На AMD RX 6000 (RDNA 2) возможен сбой видеочипа (device loss). Оставьте выключенным.":
        "WARNING: On AMD RX 6000 (RDNA 2) GPU device-loss crashes can occur. Keep disabled.",
    # Developer
    "Для разработчика": "Developer",
    "Статистика кадров в журнале": "Frame statistics in the log",
    "Профиль GPU в журнале": "GPU profile in the log",
    "Слои валидации Vulkan": "Vulkan validation layers",
    "Сильно замедляет": "Much slower",
    "Доп. переменные (ИМЯ=значение через пробел)": "Extra variables (NAME=value, space-separated)",
}


def system_language():
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(key, "")
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    return "en"


_language = "ru"


def set_language(choice):
    """choice: "ru", "en" or "" (the system's)."""
    global _language
    _language = choice if choice in ("ru", "en") else system_language()


def language():
    return _language


def tr(text):
    return EN.get(text, text) if _language == "en" else text
