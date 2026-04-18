"""Скрипт добавляет переводы tgbot-строк в locale/en и locale/kk.
Запускается один раз: python _bot_translations.py
После — обязательно compilemessages.
"""
import re
from pathlib import Path

EN = {
    # Middleware — уведомление о смене языка
    "🔄 Язык интерфейса обновлён.":
        "🔄 Interface language updated.",

    # Хендлеры привязки / /start
    "ℹ️ Данный аккаунт уже привязан к вашему Telegram.":
        "ℹ️ This account is already linked to your Telegram.",
    "👤 Аккаунт: <b>{username}</b>":
        "👤 Account: <b>{username}</b>",
    "ℹ️ Ваш Telegram уже привязан к аккаунту <b>{username}</b>.":
        "ℹ️ Your Telegram is already linked to <b>{username}</b>.",
    "✅ <b>Аккаунт успешно привязан!</b>":
        "✅ <b>Account linked successfully!</b>",
    "📱 Telegram: @{name}":
        "📱 Telegram: @{name}",
    "Теперь вы будете получать уведомления с сайта прямо сюда! 🎉":
        "You will now receive notifications from the site right here! 🎉",
    "👋 Привет, <b>{name}</b>!":
        "👋 Hello, <b>{name}</b>!",
    "Я — бот для получения уведомлений с сайта отслеживания.":
        "I am a bot for receiving tracking notifications from the site.",
    "✅ Ваш аккаунт успешно подключён. Вы будете получать уведомления здесь.":
        "✅ Your account is successfully connected. You will receive notifications here.",
    "🔗 <b>Как привязать аккаунт:</b>":
        "🔗 <b>How to link your account:</b>",
    "Зайдите на сайт в раздел «Профиль» и нажмите кнопку «Привязать Telegram» — ссылка автоматически откроет этого бота и привяжет ваш аккаунт.":
        "Go to the site, open «Profile» and click «Link Telegram» — the link will automatically open this bot and link your account.",
    "Воспользуйтесь меню ниже для управления.":
        "Use the menu below to navigate.",
    "❌ Ссылка недействительна. Сгенерируйте новую на сайте.":
        "❌ The link is invalid. Generate a new one on the site.",
    "❌ Эта ссылка уже использована. Сгенерируйте новую.":
        "❌ This link has already been used. Generate a new one.",
    "❌ Ссылка истекла. Сгенерируйте новую на сайте.":
        "❌ The link has expired. Generate a new one on the site.",
    "⚠️ К вашему аккаунту уже привязан другой Telegram.":
        "⚠️ Another Telegram is already linked to your account.",

    # Главное меню — кнопки
    "🌐 Открыть сайт": "🌐 Open site",
    "💰 Мои чеки": "💰 My receipts",
    "🔔 Уведомления": "🔔 Notifications",
    "🚫 Ограничения": "🚫 Restrictions",
    "ℹ️ Помощь": "ℹ️ Help",
    "🔗 Привязать": "🔗 Link",
    "📊 Статус": "📊 Status",
    "📬 Уведомления": "📬 Notifications",
    "👨‍✈️ Админ-панель": "👨‍✈️ Admin panel",

    # Открыть сайт
    "Перейти на сайт": "Go to site",
    "🌐 <b>Наш официальный сайт</b>": "🌐 <b>Our official website</b>",
    "Нажмите кнопку ниже, чтобы перейти на сайт.":
        "Click the button below to go to the site.",

    # Привязка (уже подключён)
    "ℹ️ Ваш аккаунт уже подключён.": "ℹ️ Your account is already connected.",
    "Аккаунт: <b>{username}</b>": "Account: <b>{username}</b>",
    "📊 Проверить привязку": "📊 Check linking",
    "🔗 Чтобы привязать аккаунт, зайдите на сайт в раздел «Профиль» и нажмите кнопку «Привязать Telegram».\n\nСсылка автоматически откроет этого бота и привяжет аккаунт.":
        "🔗 To link your account, open the site, go to «Profile» and click «Link Telegram».\n\nThe link will automatically open this bot and link the account.",

    # /status
    "❌ Ваш Telegram не привязан к аккаунту.":
        "❌ Your Telegram is not linked to any account.",
    "Зайдите на сайт → Профиль → «Привязать Telegram».":
        "Go to the site → Profile → «Link Telegram».",
    "📊 <b>Статус привязки:</b>": "📊 <b>Linking status:</b>",
    "📱 Telegram: @{tg}": "📱 Telegram: @{tg}",
    "📅 Привязан: {at}": "📅 Linked: {at}",
    "Уведомления: {state}": "Notifications: {state}",
    "📬 Всего уведомлений: {total}": "📬 Total notifications: {total}",
    "✅ Отправлено: {sent}": "✅ Sent: {sent}",
    "неизвестно": "unknown",
    "не указан": "not specified",
    "активны": "active",
    "отключены": "disabled",

    # /notifications
    "❌ Сначала привяжите аккаунт.": "❌ Please link your account first.",
    "📭 У вас пока нет уведомлений.": "📭 You have no notifications yet.",
    "📋 <b>Последние уведомления:</b>": "📋 <b>Recent notifications:</b>",

    # Catch-all
    "🤔 Неизвестная команда.": "🤔 Unknown command.",
    "Воспользуйтесь меню кнопок внизу.": "Use the button menu below.",

    # Settings (уведомления)
    "🔔 <b>Настройки уведомлений</b>": "🔔 <b>Notification settings</b>",
    "Выберите режим уведомлений:": "Choose notification mode:",
    "• <b>Все статусы</b> — вы будете получать каждое изменение.":
        "• <b>All statuses</b> — you will receive every status change.",
    "• <b>Только ПВЗ</b> — только когда посылка готова к выдаче.":
        "• <b>Pickup point only</b> — only when the parcel is ready for pickup.",
    "• <b>Выборочно</b> — выберите нужные этапы вручную.":
        "• <b>Selective</b> — choose the stages manually.",
    "<i>Уведомление о прибытии на ПВЗ является обязательным.</i>":
        "<i>The pickup-point arrival notification is mandatory.</i>",
    "✅ Все статусы": "✅ All statuses",
    "📦 Только ПВЗ": "📦 Pickup point only",
    "⚙️ Выборочно": "⚙️ Selective",
    "─── Настройка статусов ───": "─── Status configuration ───",
    "Китай (Отправлено)": "China (Shipped)",
    "Сортировочный склад": "Sorting warehouse",
    "В доставке до ПВЗ": "In delivery to pickup point",
    "ℹ️ Доставка на ПВЗ — всегда ВКЛ": "ℹ️ Pickup-point delivery — always ON",

    # Prohibited items
    "🚫 <b>Запрещённые товары к перевозке:</b>":
        "🚫 <b>Items prohibited for transportation:</b>",
    "• Взрывоопасные, радиоактивные, горючие, инфекционные, ядовитые вещества":
        "• Explosive, radioactive, flammable, infectious, toxic substances",
    "• Холодное оружие, включая макеты, пневматику, арбалеты и др.":
        "• Cold weapons, including replicas, air guns, crossbows, etc.",
    "• Психотропные и наркотические средства, алкоголь, сигареты":
        "• Psychotropic and narcotic substances, alcohol, cigarettes",
    "• Скоропортящиеся и жидкие продукты (за исключением сухих и продуктов в вакуумных упаковках)":
        "• Perishable and liquid products (except dry and vacuum-packed ones)",
    "• Животные": "• Animals",
    "• Техника, мобильные телефоны, ноутбуки (под свою ответственность)":
        "• Electronics, mobile phones, laptops (at your own risk)",
    "• Дроны": "• Drones",
    "• Хрупкие, стеклянные товары (либо просите продавца надёжную упаковку)":
        "• Fragile, glass items (or ask the seller for secure packaging)",
    "<i>⚠️ Для заказа тяжёлых или хрупких товаров рекомендуем предварительно связаться с менеджером. В случае несоблюдения списка, Inter Cargo освобождается от ответственности за товар.</i>":
        "<i>⚠️ For heavy or fragile items we recommend contacting a manager in advance. If the list is not respected, Inter Cargo is released from liability for the item.</i>",

    # FAQ
    "ℹ️ <b>Центр поддержки пользователей</b>": "ℹ️ <b>User support center</b>",
    "Выберите интересующий вас вопрос ниже, чтобы получить быстрый ответ.":
        "Choose your question below to get a quick answer.",
    "Как оплатить чек": "How to pay a receipt",
    "Перейдите в раздел «Мои чеки», выберите нужный чек и нажмите «Оплатить».":
        "Go to «My receipts», select the receipt and click «Pay».",
    "После оплаты сохраните чек, чтобы показать его на пункте выдачи.":
        "After payment, keep the receipt to show at the pickup point.",
    "⚠️ Привяжите аккаунт, чтобы увидеть информацию о вашем ПВЗ.":
        "⚠️ Link your account to see information about your pickup point.",
    "📍 <b>Адрес и график ПВЗ</b>":
        "📍 <b>Pickup point address and schedule</b>",
    "Ваш пункт выдачи:": "Your pickup point:",
    "🕒 График работы: <b>{hours}</b>": "🕒 Working hours: <b>{hours}</b>",
    "⚠️ У вас пока не выбран пункт выдачи в профиле на сайте.":
        "⚠️ You have not selected a pickup point in your profile yet.",
    "информация уточняется": "information pending",

    # Receipts
    "❌ Ваш аккаунт не привязан. Используйте «🔗 Привязать».":
        "❌ Your account is not linked. Use «🔗 Link».",
    "✅ У вас нет невыданных чеков.": "✅ You have no unclaimed receipts.",
    "📄 <b>Чек №{num}</b>": "📄 <b>Receipt #{num}</b>",
    "Статус: <b>{status}</b>": "Status: <b>{status}</b>",
    "📦 Количество посылок: <b>{count}</b>": "📦 Parcels: <b>{count}</b>",
    "⚖️ Общий вес: <b>{weight:.3f} кг</b>": "⚖️ Total weight: <b>{weight:.3f} kg</b>",
    "💰 Сумма к оплате: <b>{price} ₸</b>": "💰 Amount due: <b>{price} ₸</b>",
    "📍 Пункт выдачи: <b>{pickup}</b>": "📍 Pickup point: <b>{pickup}</b>",
    "🕒 Время работы: <b>{hours}</b>": "🕒 Working hours: <b>{hours}</b>",
    "Нажмите для оплаты": "Click to pay",
    "Не указан": "Not specified",
    "⚠️ <i>Кнопка оплаты не добавлена из-за некорректной ссылки.</i>":
        "⚠️ <i>Payment button not added due to an invalid link.</i>",
    "Доставлено на сортировочный склад": "Delivered to sorting warehouse",
    "Доставлено на ПВЗ": "Delivered to pickup point",
    "ожидает получение": "awaiting delivery",

    # Delivery notifications (bot)
    "<b>📦 Ваши посылки доставлены на ПВЗ!</b>":
        "<b>📦 Your parcels have been delivered to the pickup point!</b>",
    "• <code>{code}</code> — {weight:.3f} кг — {cost} ₸":
        "• <code>{code}</code> — {weight:.3f} kg — {cost} ₸",
    "📊 <b>Итого: {n} посылок</b>": "📊 <b>Total: {n} parcels</b>",
    "💰 Общая стоимость: <b>{price} ₸</b>": "💰 Total cost: <b>{price} ₸</b>",
    "📍 Пункт выдачи: <b>{address} ({name})</b>":
        "📍 Pickup point: <b>{address} ({name})</b>",
    "Оплатить": "Pay",

    # Reminders
    "📦 <b>Напоминание</b>": "📦 <b>Reminder</b>",
    "У вас {n} посылок на пункте выдачи.":
        "You have {n} parcels at the pickup point.",
    "Пожалуйста, заберите их.": "Please pick them up.",
    "📍 Пункт выдачи: <b>{name}</b>": "📍 Pickup point: <b>{name}</b>",
}


KK = {
    # Middleware — уведомление о смене языка
    "🔄 Язык интерфейса обновлён.":
        "🔄 Интерфейс тілі жаңартылды.",

    # Хендлеры привязки / /start
    "ℹ️ Данный аккаунт уже привязан к вашему Telegram.":
        "ℹ️ Бұл аккаунт сіздің Telegram-ыңызға бұрыннан байланысты.",
    "👤 Аккаунт: <b>{username}</b>":
        "👤 Аккаунт: <b>{username}</b>",
    "ℹ️ Ваш Telegram уже привязан к аккаунту <b>{username}</b>.":
        "ℹ️ Сіздің Telegram-ыңыз <b>{username}</b> аккаунтына байланысқан.",
    "✅ <b>Аккаунт успешно привязан!</b>":
        "✅ <b>Аккаунт сәтті байланыстырылды!</b>",
    "📱 Telegram: @{name}": "📱 Telegram: @{name}",
    "Теперь вы будете получать уведомления с сайта прямо сюда! 🎉":
        "Енді сіз сайттан хабарламаларды осында аласыз! 🎉",
    "👋 Привет, <b>{name}</b>!":
        "👋 Сәлем, <b>{name}</b>!",
    "Я — бот для получения уведомлений с сайта отслеживания.":
        "Мен — бақылау сайтынан хабарламалар алатын ботпын.",
    "✅ Ваш аккаунт успешно подключён. Вы будете получать уведомления здесь.":
        "✅ Аккаунтыңыз сәтті қосылды. Хабарламаларды осы жерде аласыз.",
    "🔗 <b>Как привязать аккаунт:</b>":
        "🔗 <b>Аккаунтты қалай байланыстыру керек:</b>",
    "Зайдите на сайт в раздел «Профиль» и нажмите кнопку «Привязать Telegram» — ссылка автоматически откроет этого бота и привяжет ваш аккаунт.":
        "Сайтқа кіріп «Профиль» бөліміне өтіп, «Telegram-ды байланыстыру» батырмасын басыңыз — сілтеме автоматты түрде осы ботты ашып, аккаунтыңызды байланыстырады.",
    "Воспользуйтесь меню ниже для управления.":
        "Басқару үшін төмендегі мәзірді пайдаланыңыз.",
    "❌ Ссылка недействительна. Сгенерируйте новую на сайте.":
        "❌ Сілтеме жарамсыз. Сайтта жаңасын жасаңыз.",
    "❌ Эта ссылка уже использована. Сгенерируйте новую.":
        "❌ Бұл сілтеме пайдаланылған. Жаңасын жасаңыз.",
    "❌ Ссылка истекла. Сгенерируйте новую на сайте.":
        "❌ Сілтеменің мерзімі біткен. Сайтта жаңасын жасаңыз.",
    "⚠️ К вашему аккаунту уже привязан другой Telegram.":
        "⚠️ Сіздің аккаунтыңызға басқа Telegram байланыстырылған.",

    # Главное меню — кнопки
    "🌐 Открыть сайт": "🌐 Сайтты ашу",
    "💰 Мои чеки": "💰 Менің чектерім",
    "🔔 Уведомления": "🔔 Хабарламалар",
    "🚫 Ограничения": "🚫 Шектеулер",
    "ℹ️ Помощь": "ℹ️ Көмек",
    "🔗 Привязать": "🔗 Байланыстыру",
    "📊 Статус": "📊 Күй",
    "📬 Уведомления": "📬 Хабарламалар",
    "👨‍✈️ Админ-панель": "👨‍✈️ Әкімші панелі",

    # Открыть сайт
    "Перейти на сайт": "Сайтқа өту",
    "🌐 <b>Наш официальный сайт</b>": "🌐 <b>Біздің ресми сайт</b>",
    "Нажмите кнопку ниже, чтобы перейти на сайт.":
        "Сайтқа өту үшін төмендегі батырманы басыңыз.",

    # Привязка (уже подключён)
    "ℹ️ Ваш аккаунт уже подключён.": "ℹ️ Аккаунтыңыз әлдеқашан қосылған.",
    "Аккаунт: <b>{username}</b>": "Аккаунт: <b>{username}</b>",
    "📊 Проверить привязку": "📊 Байланысты тексеру",
    "🔗 Чтобы привязать аккаунт, зайдите на сайт в раздел «Профиль» и нажмите кнопку «Привязать Telegram».\n\nСсылка автоматически откроет этого бота и привяжет аккаунт.":
        "🔗 Аккаунтты байланыстыру үшін сайтқа кіріп «Профиль» бөліміне өтіп, «Telegram-ды байланыстыру» батырмасын басыңыз.\n\nСілтеме осы ботты автоматты түрде ашып, аккаунтты байланыстырады.",

    # /status
    "❌ Ваш Telegram не привязан к аккаунту.":
        "❌ Сіздің Telegram-ыңыз аккаунтқа байланыстырылмаған.",
    "Зайдите на сайт → Профиль → «Привязать Telegram».":
        "Сайтқа кіріңіз → Профиль → «Telegram-ды байланыстыру».",
    "📊 <b>Статус привязки:</b>": "📊 <b>Байланыс күйі:</b>",
    "📱 Telegram: @{tg}": "📱 Telegram: @{tg}",
    "📅 Привязан: {at}": "📅 Байланысқан: {at}",
    "Уведомления: {state}": "Хабарламалар: {state}",
    "📬 Всего уведомлений: {total}": "📬 Барлық хабарламалар: {total}",
    "✅ Отправлено: {sent}": "✅ Жіберілді: {sent}",
    "неизвестно": "белгісіз",
    "не указан": "көрсетілмеген",
    "активны": "белсенді",
    "отключены": "өшірілген",

    # /notifications
    "❌ Сначала привяжите аккаунт.": "❌ Алдымен аккаунтты байланыстырыңыз.",
    "📭 У вас пока нет уведомлений.": "📭 Әзірге хабарламалар жоқ.",
    "📋 <b>Последние уведомления:</b>": "📋 <b>Соңғы хабарламалар:</b>",

    # Catch-all
    "🤔 Неизвестная команда.": "🤔 Белгісіз команда.",
    "Воспользуйтесь меню кнопок внизу.": "Төмендегі батырмалар мәзірін пайдаланыңыз.",

    # Settings (уведомления)
    "🔔 <b>Настройки уведомлений</b>": "🔔 <b>Хабарлама параметрлері</b>",
    "Выберите режим уведомлений:": "Хабарлама режимін таңдаңыз:",
    "• <b>Все статусы</b> — вы будете получать каждое изменение.":
        "• <b>Барлық күйлер</b> — әр өзгерісті аласыз.",
    "• <b>Только ПВЗ</b> — только когда посылка готова к выдаче.":
        "• <b>Тек ТБН</b> — жіберілім алуға дайын болғанда ғана.",
    "• <b>Выборочно</b> — выберите нужные этапы вручную.":
        "• <b>Таңдамалы</b> — қажетті кезеңдерді қолмен таңдаңыз.",
    "<i>Уведомление о прибытии на ПВЗ является обязательным.</i>":
        "<i>ТБН-ге келу туралы хабарлама міндетті.</i>",
    "✅ Все статусы": "✅ Барлық күйлер",
    "📦 Только ПВЗ": "📦 Тек ТБН",
    "⚙️ Выборочно": "⚙️ Таңдамалы",
    "─── Настройка статусов ───": "─── Күйлерді баптау ───",
    "Китай (Отправлено)": "Қытай (Жіберілді)",
    "Сортировочный склад": "Сұрыптау қоймасы",
    "В доставке до ПВЗ": "ТБН-ге жеткізу жолында",
    "ℹ️ Доставка на ПВЗ — всегда ВКЛ": "ℹ️ ТБН-ге жеткізу — әрқашан ҚОСУЛЫ",

    # Prohibited
    "🚫 <b>Запрещённые товары к перевозке:</b>":
        "🚫 <b>Тасымалдауға тыйым салынған заттар:</b>",
    "• Взрывоопасные, радиоактивные, горючие, инфекционные, ядовитые вещества":
        "• Жарылғыш, радиоактивті, жанғыш, жұқпалы, улы заттар",
    "• Холодное оружие, включая макеты, пневматику, арбалеты и др.":
        "• Суық қару, соның ішінде модельдер, пневматика, арбалеттер және т.б.",
    "• Психотропные и наркотические средства, алкоголь, сигареты":
        "• Психотропты және есірткі заттары, алкоголь, темекі",
    "• Скоропортящиеся и жидкие продукты (за исключением сухих и продуктов в вакуумных упаковках)":
        "• Тез бұзылатын және сұйық өнімдер (құрғақ және вакуумдық қаптамадағылардан басқа)",
    "• Животные": "• Жануарлар",
    "• Техника, мобильные телефоны, ноутбуки (под свою ответственность)":
        "• Техника, ұялы телефондар, ноутбуктер (өз жауапкершілігіңізде)",
    "• Дроны": "• Дрондар",
    "• Хрупкие, стеклянные товары (либо просите продавца надёжную упаковку)":
        "• Сынғыш, шыны заттар (немесе сатушыдан сенімді қаптамасын сұраңыз)",
    "<i>⚠️ Для заказа тяжёлых или хрупких товаров рекомендуем предварительно связаться с менеджером. В случае несоблюдения списка, Inter Cargo освобождается от ответственности за товар.</i>":
        "<i>⚠️ Ауыр немесе сынғыш заттарды тапсырыс беру үшін алдын ала менеджермен байланысуды ұсынамыз. Тізім сақталмаса, Inter Cargo зат үшін жауапкершіліктен босатылады.</i>",

    # FAQ
    "ℹ️ <b>Центр поддержки пользователей</b>": "ℹ️ <b>Пайдаланушыларды қолдау орталығы</b>",
    "Выберите интересующий вас вопрос ниже, чтобы получить быстрый ответ.":
        "Жылдам жауап алу үшін төмендегі сұрақты таңдаңыз.",
    "Как оплатить чек": "Чекті қалай төлеу керек",
    "Перейдите в раздел «Мои чеки», выберите нужный чек и нажмите «Оплатить».":
        "«Менің чектерім» бөліміне өтіп, керекті чекті таңдап, «Төлеу» батырмасын басыңыз.",
    "После оплаты сохраните чек, чтобы показать его на пункте выдачи.":
        "Төлегеннен кейін чекті тапсыру пунктіне көрсету үшін сақтаңыз.",
    "⚠️ Привяжите аккаунт, чтобы увидеть информацию о вашем ПВЗ.":
        "⚠️ ТБН туралы ақпаратты көру үшін аккаунтты байланыстырыңыз.",
    "📍 <b>Адрес и график ПВЗ</b>":
        "📍 <b>ТБН мекенжайы мен кестесі</b>",
    "Ваш пункт выдачи:": "Сіздің тапсыру пунктіңіз:",
    "🕒 График работы: <b>{hours}</b>": "🕒 Жұмыс кестесі: <b>{hours}</b>",
    "⚠️ У вас пока не выбран пункт выдачи в профиле на сайте.":
        "⚠️ Әзірге сайттағы профильде тапсыру пункті таңдалмаған.",
    "информация уточняется": "ақпарат нақтылануда",

    # Receipts
    "❌ Ваш аккаунт не привязан. Используйте «🔗 Привязать».":
        "❌ Аккаунтыңыз байланыстырылмаған. «🔗 Байланыстыру» пайдаланыңыз.",
    "✅ У вас нет невыданных чеков.": "✅ Берілмеген чектеріңіз жоқ.",
    "📄 <b>Чек №{num}</b>": "📄 <b>Чек №{num}</b>",
    "Статус: <b>{status}</b>": "Күйі: <b>{status}</b>",
    "📦 Количество посылок: <b>{count}</b>": "📦 Жіберілімдер саны: <b>{count}</b>",
    "⚖️ Общий вес: <b>{weight:.3f} кг</b>": "⚖️ Жалпы салмағы: <b>{weight:.3f} кг</b>",
    "💰 Сумма к оплате: <b>{price} ₸</b>": "💰 Төлем сомасы: <b>{price} ₸</b>",
    "📍 Пункт выдачи: <b>{pickup}</b>": "📍 Тапсыру пункті: <b>{pickup}</b>",
    "🕒 Время работы: <b>{hours}</b>": "🕒 Жұмыс уақыты: <b>{hours}</b>",
    "Нажмите для оплаты": "Төлеу үшін басыңыз",
    "Не указан": "Көрсетілмеген",
    "⚠️ <i>Кнопка оплаты не добавлена из-за некорректной ссылки.</i>":
        "⚠️ <i>Төлем батырмасы жарамсыз сілтеме себебінен қосылмады.</i>",
    "Доставлено на сортировочный склад": "Сұрыптау қоймасына жеткізілді",
    "Доставлено на ПВЗ": "ТБН-ге жеткізілді",
    "ожидает получение": "алуды күтуде",

    # Delivery notifications (bot)
    "<b>📦 Ваши посылки доставлены на ПВЗ!</b>":
        "<b>📦 Жіберілімдеріңіз ТБН-ге жеткізілді!</b>",
    "• <code>{code}</code> — {weight:.3f} кг — {cost} ₸":
        "• <code>{code}</code> — {weight:.3f} кг — {cost} ₸",
    "📊 <b>Итого: {n} посылок</b>": "📊 <b>Барлығы: {n} жіберілім</b>",
    "💰 Общая стоимость: <b>{price} ₸</b>": "💰 Жалпы құны: <b>{price} ₸</b>",
    "📍 Пункт выдачи: <b>{address} ({name})</b>":
        "📍 Тапсыру пункті: <b>{address} ({name})</b>",
    "Оплатить": "Төлеу",

    # Reminders
    "📦 <b>Напоминание</b>": "📦 <b>Еске салу</b>",
    "У вас {n} посылок на пункте выдачи.":
        "Тапсыру пунктінде {n} жіберілім бар.",
    "Пожалуйста, заберите их.": "Оларды алуыңызды өтінеміз.",
    "📍 Пункт выдачи: <b>{name}</b>": "📍 Тапсыру пункті: <b>{name}</b>",
}


def _escape_po(s):
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def _split_msgid(content, msgid):
    """Ищет блок msgid и возвращает (before, block, after). Поддерживает многострочные msgid."""
    esc = _escape_po(msgid)
    # Собираем паттерн для msgid "..." (возможно многострочный) + msgstr "..." (возможно пустой)
    pattern = re.compile(
        r'(msgid "' + re.escape(esc) + r'"\n(?:"[^"]*"\n)*)(msgstr "(?:[^"\\]|\\.)*"\n(?:"[^"]*"\n)*)',
        re.MULTILINE,
    )
    return pattern


def _unquote_po_block(lines):
    """Склеивает многострочные msgid/msgstr обратно в единую строку без кавычек."""
    s = ''
    for line in lines:
        line = line.strip()
        if not line.startswith('"') or not line.endswith('"'):
            continue
        body = line[1:-1]
        body = body.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\').replace('\\t', '\t')
        s += body
    return s


def apply_translations(po_path: Path, translations: dict):
    text = po_path.read_text(encoding='utf-8')
    lines = text.split('\n')
    # Разбиваем на блоки по пустым строкам
    i = 0
    updated = 0
    skipped = 0
    not_found_set = set(translations.keys())

    out_lines = []
    while i < len(lines):
        # копируем до начала msgid
        block_start = i
        # collect until next blank line
        block = []
        while i < len(lines) and lines[i] != '':
            block.append(lines[i])
            i += 1

        # analyse block
        # find msgid (possibly multi-line) and msgstr (possibly multi-line)
        msgid_idx = None
        msgstr_idx = None
        for j, ln in enumerate(block):
            if ln.startswith('msgid ') and msgid_idx is None:
                msgid_idx = j
            elif ln.startswith('msgstr ') and msgstr_idx is None:
                msgstr_idx = j
                break

        modified = False
        if msgid_idx is not None and msgstr_idx is not None:
            # собрать msgid
            first_id = block[msgid_idx][len('msgid '):]  # '"..."'
            id_lines = [first_id] + [block[k] for k in range(msgid_idx + 1, msgstr_idx)]
            msgid_value = _unquote_po_block(id_lines)

            # собрать msgstr
            first_str = block[msgstr_idx][len('msgstr '):]
            str_lines = [first_str]
            k = msgstr_idx + 1
            while k < len(block) and block[k].startswith('"'):
                str_lines.append(block[k])
                k += 1
            msgstr_value = _unquote_po_block(str_lines)

            if msgid_value in translations:
                not_found_set.discard(msgid_value)
                desired = translations[msgid_value]
                if msgstr_value != desired:
                    # форсированно заменить msgstr на правильный перевод
                    new_msgstr_line = f'msgstr "{_escape_po(desired)}"'
                    new_block = block[:msgstr_idx] + [new_msgstr_line] + block[k:]
                    block = new_block
                    updated += 1
                    modified = True
                else:
                    skipped += 1

        out_lines.extend(block)
        # добавим пустую строку/конец файла
        if i < len(lines):
            out_lines.append(lines[i])
            i += 1

    po_path.write_text('\n'.join(out_lines), encoding='utf-8')
    not_found = sorted(not_found_set)
    report = [f'{po_path}: updated={updated}, skipped={skipped}, not_found={len(not_found)}']
    for nf in not_found:
        report.append(f'  NOT FOUND: {nf!r}')
    report_txt = '\n'.join(report)
    (po_path.parent / '_translation_report.txt').write_text(report_txt, encoding='utf-8')
    try:
        print(report_txt)
    except UnicodeEncodeError:
        print(report_txt.encode('ascii', 'backslashreplace').decode('ascii'))


if __name__ == '__main__':
    base = Path(__file__).parent / 'locale'
    apply_translations(base / 'en' / 'LC_MESSAGES' / 'django.po', EN)
    apply_translations(base / 'kk' / 'LC_MESSAGES' / 'django.po', KK)
    # Русский — исходный язык: msgstr должен совпадать с msgid для всех наших строк,
    # чтобы gettext не подхватывал fuzzy-матчи на похожие старые msgid.
    RU = {key: key for key in set(EN.keys()) | set(KK.keys())}
    apply_translations(base / 'ru' / 'LC_MESSAGES' / 'django.po', RU)
