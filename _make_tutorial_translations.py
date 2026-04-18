# -*- coding: utf-8 -*-
"""Generate tutorial.en.js and tutorial.kk.js from tutorial.js by
replacing Russian UI strings with English/Kazakh equivalents."""
import os, re

SRC = r'd:\cargo\InterCargoWeb\mainview\static\scripts\tutorial.js'
OUT_EN = r'd:\cargo\InterCargoWeb\mainview\static\scripts\tutorial.en.js'
OUT_KK = r'd:\cargo\InterCargoWeb\mainview\static\scripts\tutorial.kk.js'

# (Russian, English, Kazakh)
TRANSLATIONS = [
    # Tutorial names
    ('Как добавить трек-коды', 'How to add track codes', 'Трек-кодтарды қалай қосу керек'),
    ('Как посмотреть чеки', 'How to view receipts', 'Чектерді қалай көру керек'),
    ('Как получить и оплатить посылки', 'How to receive and pay for parcels', 'Посылкаларды қалай алу және төлеу керек'),
    ('Как зарегистрироваться', 'How to register', 'Қалай тіркелу керек'),
    ('Как войти на сайт', 'How to log in', 'Сайтқа қалай кіру керек'),
    ('Как начать заказывать', 'How to start ordering', 'Тапсырыс беруді қалай бастау керек'),
    ('Приёмка товара', 'Goods acceptance', 'Тауар қабылдау'),
    ('Выдача посылок', 'Parcel extradition', 'Посылкаларды беру'),
    ('Склад ПВЗ', 'Pickup point warehouse', 'ПВЗ қоймасы'),
    ('Реструктуризация склада', 'Warehouse restructuring', 'Қойманы қайта құрылымдау'),

    # UI buttons & labels
    ('Назад', 'Back', 'Артқа'),
    ('Далее', 'Next', 'Келесі'),
    ('Перейти', 'Go', 'Өту'),
    ('Готово', 'Done', 'Дайын'),
    ('Закрыть', 'Close', 'Жабу'),
    ('Обучение по сайту', 'Site tutorials', 'Сайтты үйрету'),
    ('Выберите тему для интерактивного обучения:', 'Select a topic for interactive tutorial:', 'Интерактивті үйрену тақырыбын таңдаңыз:'),
    ('Для сотрудников ПВЗ', 'For pickup point employees', 'ПВЗ қызметкерлеріне'),

    # Validation errors
    ('Обучение не найдено.', 'Tutorial not found.', 'Үйрету табылмады.'),
    ('Нет доступных шагов для этого обучения.', 'No available steps for this tutorial.', 'Бұл үйрету үшін қолжетімді қадамдар жоқ.'),
    ('Мобильная навигация не найдена. Пожалуйста, обновите страницу.', 'Mobile navigation not found. Please refresh the page.', 'Мобильді навигация табылмады. Бетті жаңартыңыз.'),
    ('Элемент интерфейса для первого шага не найден. Попробуйте обновить страницу.', 'The interface element for the first step was not found. Try refreshing the page.', 'Бірінші қадамға арналған интерфейс элементі табылмады. Бетті жаңартып көріңіз.'),

    # --- Step texts: add_track ---
    ('Нажмите на иконку меню, чтобы открыть боковую панель навигации.',
     'Tap the menu icon to open the side navigation panel.',
     'Бүйірлік навигация тақтасын ашу үшін мәзір белгішесін басыңыз.'),
    ('Перейдите в раздел "Трек-коды" в боковом меню для управления вашими трек-кодами.',
     'Go to the "Track codes" section in the side menu to manage your track codes.',
     'Трек-кодтарыңызды басқару үшін бүйірлік мәзірдегі "Трек-кодтар" бөліміне өтіңіз.'),
    ('Нажмите кнопку "Добавить" чтобы открыть форму добавления нового трек-кода.',
     'Click the "Add" button to open the form for adding a new track code.',
     'Жаңа трек-код қосу нысанын ашу үшін "Қосу" түймесін басыңыз.'),
    ('Введите ваш трек-код в это поле. Трек-код вы получаете от продавца после оплаты товара.',
     'Enter your track code in this field. You get the track code from the seller after paying for the goods.',
     'Трек-кодты осы өріске енгізіңіз. Трек-кодты сатушыдан тауарды төлегеннен кейін аласыз.'),
    ('Добавьте описание посылки (необязательно). Например: "Куртка зимняя" — это поможет вам не путать посылки.',
     'Add a parcel description (optional). For example: "Winter jacket" — this will help you not to confuse parcels.',
     'Посылканың сипаттамасын қосыңыз (міндетті емес). Мысалы: "Қысқы куртка" — бұл посылкаларды шатастырмауға көмектеседі.'),
    ('Нажмите "Сохранить" для добавления трек-кода. После этого вы сможете отслеживать статус вашей посылки.',
     'Click "Save" to add the track code. After that you will be able to track the status of your parcel.',
     'Трек-кодты қосу үшін "Сақтау" түймесін басыңыз. Одан кейін посылканың күйін бақылай аласыз.'),
    ('Нажмите на вкладку "Посылки" в нижней панели навигации.',
     'Tap the "Parcels" tab in the bottom navigation panel.',
     'Төменгі навигация тақтасындағы "Посылкалар" қойындысын басыңыз.'),
    ('Нажмите кнопку "Добавить трек-код" чтобы открыть форму добавления.',
     'Tap the "Add track code" button to open the add form.',
     'Қосу нысанын ашу үшін "Трек-код қосу" түймесін басыңыз.'),

    # view_receipts
    ('Перейдите в раздел "Чеки" в боковом меню для просмотра ваших чеков.',
     'Go to the "Receipts" section in the side menu to view your receipts.',
     'Чектеріңізді көру үшін бүйірлік мәзірдегі "Чектер" бөліміне өтіңіз.'),
    ('Здесь отображаются ваши чеки. Каждый чек содержит информацию о дате, весе и стоимости посылок.',
     'Your receipts are displayed here. Each receipt contains information about the date, weight and cost of parcels.',
     'Мұнда сіздің чектеріңіз көрсетіледі. Әр чекте посылкалардың күні, салмағы және құны туралы ақпарат бар.'),
    ('Нажмите на заголовок чека, чтобы развернуть подробности — список трек-кодов, вес и стоимость каждой посылки.',
     'Click on the receipt header to expand details — list of track codes, weight and cost of each parcel.',
     'Әр посылканың трек-кодтарының тізімін, салмағын және құнын көру үшін чек тақырыбын басыңыз.'),
    ('В развёрнутом чеке вы увидите таблицу с трек-кодами, весом и ценой каждой посылки, а также итоговую сумму и пункт выдачи.',
     'In the expanded receipt you will see a table with track codes, weight and price of each parcel, as well as the total amount and pickup point.',
     'Ашылған чекте трек-кодтардың, әр посылканың салмағы мен бағасының кестесін, сондай-ақ жалпы сомасы мен алу пунктін көресіз.'),
    ('Чтобы посмотреть чеки, перейдите в раздел "Меню" в нижней навигации.',
     'To view receipts, go to the "Menu" section in the bottom navigation.',
     'Чектерді көру үшін төменгі навигациядағы "Мәзір" бөліміне өтіңіз.'),
    ('Нажмите на иконку "Чеки" для перехода к вашим чекам.',
     'Tap the "Receipts" icon to go to your receipts.',
     'Чектеріңізге өту үшін "Чектер" белгішесін басыңыз.'),

    # receive_parcels
    ('Перейдите на главную страницу профиля для получения посылок.',
     'Go to the main profile page to receive parcels.',
     'Посылкаларды алу үшін профильдің басты бетіне өтіңіз.'),
    ('Здесь отображается статистика ваших трек-кодов по статусам. Когда посылки прибудут на ПВЗ, статус изменится на "Прибыло (ПВЗ)".',
     'This displays statistics of your track codes by status. When parcels arrive at the pickup point, the status will change to "Arrived (PP)".',
     'Мұнда трек-кодтарыңыздың статустар бойынша статистикасы көрсетіледі. Посылкалар ПВЗ-ға келгенде, статус "Келді (ПВЗ)" болып өзгереді.'),
    ('Когда посылки доставлены на ПВЗ, появится зелёная кнопка "Получить посылки". Нажмите её, чтобы начать процесс получения.',
     'When parcels are delivered to the pickup point, a green "Receive parcels" button will appear. Click it to start the receiving process.',
     'Посылкалар ПВЗ-ға жеткізілгенде, жасыл "Посылкаларды алу" түймесі пайда болады. Алу процесін бастау үшін оны басыңыз.'),
    ('После нажатия вам будет показано количество посылок для подтверждения. Проверьте и нажмите "Окей".',
     'After clicking, the number of parcels will be shown for confirmation. Check and click "OK".',
     'Басқаннан кейін растау үшін посылкалар саны көрсетіледі. Тексеріп, "Жарайды" түймесін басыңыз.'),
    ('Далее на экране появится QR-код. Покажите его сотруднику пункта выдачи — он отсканирует код и выдаст ваши посылки.',
     'Then a QR code will appear on the screen. Show it to the pickup point employee — they will scan the code and issue your parcels.',
     'Содан кейін экранда QR-код пайда болады. Оны алу пунктінің қызметкеріне көрсетіңіз — ол кодты сканерлеп, посылкаларыңызды береді.'),
    ('Оплату вы можете произвести на месте в пункте выдачи. Готово — ваши посылки получены!',
     'You can make the payment on-site at the pickup point. Done — your parcels have been received!',
     'Төлемді алу пунктінде орнында жасай аласыз. Дайын — посылкаларыңыз алынды!'),
    ('Нажмите на кнопку "QR" в нижней панели навигации.',
     'Tap the "QR" button in the bottom navigation panel.',
     'Төменгі навигация тақтасындағы "QR" түймесін басыңыз.'),

    # guest_register
    ('Добро пожаловать! Сейчас мы покажем, как зарегистрироваться на сайте Inter Cargo. Нажмите "Далее" чтобы начать.',
     'Welcome! Now we will show you how to register on the Inter Cargo website. Click "Next" to begin.',
     'Қош келдіңіз! Қазір Inter Cargo сайтында қалай тіркелетінін көрсетеміз. Бастау үшін "Келесі" түймесін басыңыз.'),
    ('Введите логин латинскими буквами. Этот логин будет использоваться для входа на сайт и для идентификации ваших посылок.',
     'Enter your login in Latin letters. This login will be used to log in to the site and to identify your parcels.',
     'Логинді латын әріптерімен енгізіңіз. Бұл логин сайтқа кіру және посылкаларыңызды анықтау үшін қолданылады.'),
    ('Укажите ваш номер телефона. По нему вы также сможете входить на сайт.',
     'Enter your phone number. You can also use it to log in to the site.',
     'Телефон нөміріңізді енгізіңіз. Ол арқылы сайтқа да кіре аласыз.'),
    ('Укажите ваш email. На него будут приходить уведомления о статусе посылок.',
     'Enter your email. Notifications about parcel status will be sent to it.',
     'Email-іңізді көрсетіңіз. Посылка күйі туралы хабарландырулар оған келеді.'),
    ('Выберите удобный для вас пункт выдачи (ПВЗ), где вы будете получать свои посылки.',
     'Choose a convenient pickup point (PP) where you will receive your parcels.',
     'Посылкаларыңызды алатын қолайлы алу пунктін (ПВЗ) таңдаңыз.'),
    ('Придумайте надёжный пароль. Минимум 8 символов, используйте буквы и цифры.',
     'Create a strong password. Minimum 8 characters, use letters and digits.',
     'Сенімді құпия сөз ойлап табыңыз. Ең кемі 8 таңба, әріптер мен цифрларды қолданыңыз.'),
    ('После заполнения всех полей нажмите кнопку "Зарегистрироваться". Готово!',
     'After filling in all fields, click the "Register" button. Done!',
     'Барлық өрістерді толтырғаннан кейін "Тіркелу" түймесін басыңыз. Дайын!'),

    # guest_login
    ('Сейчас мы покажем, как войти в свой аккаунт. Вы можете войти по логину, телефону или email.',
     'Now we will show you how to log in to your account. You can log in using login, phone or email.',
     'Қазір аккаунтыңызға қалай кіру керектігін көрсетеміз. Логин, телефон немесе email арқылы кіре аласыз.'),
    ('Выберите способ входа: по логину, по номеру телефона или по email. Нажмите на нужную вкладку.',
     'Choose the login method: by login, phone number or email. Click the desired tab.',
     'Кіру әдісін таңдаңыз: логин, телефон нөмірі немесе email бойынша. Керекті қойындыны басыңыз.'),
    ('Введите пароль, который вы указали при регистрации, и нажмите "Войти".',
     'Enter the password you specified during registration and click "Log in".',
     'Тіркелу кезінде көрсеткен құпия сөзіңізді енгізіп, "Кіру" түймесін басыңыз.'),

    # guest_how_to_order
    ('Хотите начать заказывать товары из Китая? Вот порядок действий. Нажмите "Далее".',
     'Want to start ordering goods from China? Here is the procedure. Click "Next".',
     'Қытайдан тауарларға тапсырыс бергіңіз келе ме? Мынау — тәртіп. "Келесі" түймесін басыңыз.'),
    ('1. Напишите менеджеру Inter Cargo в WhatsApp. Он расскажет о тарифах, условиях доставки и ответит на ваши вопросы.',
     '1. Write to the Inter Cargo manager on WhatsApp. They will tell you about tariffs, delivery conditions and answer your questions.',
     '1. Inter Cargo менеджеріне WhatsApp арқылы жазыңыз. Ол тарифтер, жеткізу шарттары туралы айтады және сұрақтарыңызға жауап береді.'),
    ('2. Получите от менеджера инструкции: адрес склада в Китае и правила оформления заказа.',
     '2. Get instructions from the manager: the warehouse address in China and the order placement rules.',
     '2. Менеджерден нұсқаулық алыңыз: Қытайдағы қойма мекенжайы және тапсырысты ресімдеу ережелері.'),
    ('3. Зарегистрируйтесь на нашем сайте — это необходимо для отслеживания посылок и получения чеков.',
     '3. Register on our site — this is required to track parcels and receive receipts.',
     '3. Сайтымызда тіркеліңіз — посылкаларды бақылау және чектерді алу үшін қажет.'),
    ('4. Оформите заказ на китайской торговой площадке (Taobao, Pinduoduo, 1688 и др.).',
     '4. Place an order on a Chinese marketplace (Taobao, Pinduoduo, 1688, etc.).',
     '4. Қытайлық сауда алаңында тапсырыс беріңіз (Taobao, Pinduoduo, 1688 т.б.).'),
    ('5. При оформлении укажите адрес нашего склада в Китае и ваш логин с сайта — так мы определим, чья это посылка.',
     '5. When placing the order, specify our warehouse address in China and your login from the site — this way we will identify whose parcel it is.',
     '5. Тапсырыс беру кезінде Қытайдағы қоймамыздың мекенжайын және сайттағы логиніңізді көрсетіңіз — осылайша біз посылканың иесін анықтаймыз.'),
    ('6. Добавьте трек-код посылки в личном кабинете. Отслеживайте статус доставки — от Китая до вашего ПВЗ.',
     '6. Add the parcel track code in your personal account. Track the delivery status — from China to your pickup point.',
     '6. Посылканың трек-кодын жеке кабинетке қосыңыз. Жеткізу күйін Қытайдан ПВЗ-ға дейін бақылаңыз.'),
    ('Готово! Когда посылка прибудет на ПВЗ, вы получите уведомление. Приходите, оплатите и заберите.',
     'Done! When the parcel arrives at the pickup point, you will receive a notification. Come, pay and pick it up.',
     'Дайын! Посылка ПВЗ-ға келгенде, сізге хабарландыру келеді. Келіңіз, төлеңіз және алыңыз.'),

    # pp_acceptance_tutorial
    ('Нажмите на иконку меню, чтобы открыть боковую панель.',
     'Tap the menu icon to open the side panel.',
     'Бүйірлік тақтаны ашу үшін мәзір белгішесін басыңыз.'),
    ('Перейдите в раздел "Приёмка товара" в боковом меню.',
     'Go to the "Goods acceptance" section in the side menu.',
     'Бүйірлік мәзірдегі "Тауар қабылдау" бөліміне өтіңіз.'),
    ('Здесь отображаются ожидающие приёмки доставки. Каждая карточка — одна доставка от водителя с количеством чеков.',
     'Here deliveries awaiting acceptance are displayed. Each card is one delivery from a driver with a number of receipts.',
     'Мұнда қабылдауды күтіп тұрған жеткізулер көрсетіледі. Әр карточка — чектер санымен бір жүргізушіден келген жеткізу.'),
    ('Когда водитель нажимает "Начать выдачу" — на карточке появляется кнопка "Приёмка". Нажмите её, чтобы начать принимать посылки.',
     'When the driver clicks "Start delivery" — the "Acceptance" button appears on the card. Click it to start accepting parcels.',
     'Жүргізуші "Беруді бастау" түймесін басқанда, карточкада "Қабылдау" түймесі пайда болады. Посылкаларды қабылдауды бастау үшін оны басыңыз.'),
    ('Отсканируйте QR-код каждого чека сканером или камерой. Система автоматически проверит чек и отметит его как принятый.',
     'Scan the QR code of each receipt with a scanner or camera. The system will automatically check the receipt and mark it as accepted.',
     'Әр чектің QR-кодын сканермен немесе камерамен сканерлеңіз. Жүйе чекті автоматты түрде тексеріп, оны қабылданды деп белгілейді.'),
    ('После приёмки всех чеков нажмите "Завершить сессию". Посылки переместятся на склад вашего ПВЗ.',
     'After accepting all receipts, click "Finish session". The parcels will be moved to your pickup point warehouse.',
     'Барлық чектерді қабылдағаннан кейін "Сессияны аяқтау" түймесін басыңыз. Посылкалар сіздің ПВЗ қоймасына жылжытылады.'),
    ('Перейдите в раздел "Меню" в нижней навигации.',
     'Go to the "Menu" section in the bottom navigation.',
     'Төменгі навигациядағы "Мәзір" бөліміне өтіңіз.'),
    ('Нажмите на иконку "Приёмка" в секции для сотрудников ПВЗ.',
     'Tap the "Acceptance" icon in the pickup point employees section.',
     'ПВЗ қызметкерлеріне арналған бөлімдегі "Қабылдау" белгішесін басыңыз.'),

    # pp_extradition_tutorial
    ('Нажмите на иконку меню для навигации.',
     'Tap the menu icon for navigation.',
     'Навигация үшін мәзір белгішесін басыңыз.'),
    ('Перейдите в раздел "Выдача посылок" — здесь оформляется выдача посылок клиентам.',
     'Go to the "Parcel extradition" section — here the issuance of parcels to clients is processed.',
     '"Посылкаларды беру" бөліміне өтіңіз — мұнда клиенттерге посылка беру рәсімделеді.'),
    ('Когда клиент приходит за посылками, отсканируйте его QR-код выдачи в это поле. Также можно ввести код вручную.',
     'When a client comes for parcels, scan their extradition QR code into this field. You can also enter the code manually.',
     'Клиент посылкаларын алуға келгенде, оның беру QR-кодын осы өріске сканерлеңіз. Сондай-ақ кодты қолмен енгізуге болады.'),
    ('Или нажмите эту кнопку, чтобы открыть камеру и отсканировать QR-код клиента.',
     'Or click this button to open the camera and scan the client\'s QR code.',
     'Немесе камераны ашып, клиенттің QR-кодын сканерлеу үшін осы түймені басыңыз.'),
    ('После сканирования QR-кода клиента система найдёт его пакет и покажет информацию: имя клиента, ПВЗ, ячейку хранения и список чеков с посылками.',
     'After scanning the client\'s QR code, the system will find their package and display information: client name, pickup point, storage cell and list of receipts with parcels.',
     'Клиенттің QR-кодын сканерлегеннен кейін жүйе оның пакетін тауып, ақпаратты көрсетеді: клиент аты, ПВЗ, сақтау ұяшығы және посылкалары бар чектер тізімі.'),
    ('Для быстрой выдачи нажмите "Оформить выдачу". Для проверки — нажмите "Проверить и выдать", чтобы отсканировать QR-коды на каждом чеке.',
     'For quick issuance, click "Issue". For verification — click "Verify and issue" to scan QR codes on each receipt.',
     'Жылдам беру үшін "Беруді рәсімдеу" түймесін басыңыз. Тексеру үшін әр чектегі QR-кодтарды сканерлеуге "Тексеру және беру" түймесін басыңыз.'),
    ('В режиме проверки отсканируйте QR-код каждого чека. Прогресс-бар покажет сколько чеков проверено. После проверки всех чеков нажмите "Подтвердить выдачу".',
     'In verification mode, scan the QR code of each receipt. The progress bar will show how many receipts have been checked. After checking all receipts, click "Confirm issuance".',
     'Тексеру режимінде әр чектің QR-кодын сканерлеңіз. Прогресс жолағы қанша чек тексерілгенін көрсетеді. Барлық чектерді тексергеннен кейін "Беруді растау" түймесін басыңыз.'),
    ('После оформления выдачи: посылки будут отмечены как выданные, ячейка хранения освободится, а клиент получит уведомление.',
     'After processing issuance: parcels will be marked as issued, the storage cell will become free, and the client will receive a notification.',
     'Беруді рәсімдегеннен кейін: посылкалар берілген ретінде белгіленеді, сақтау ұяшығы босайды және клиент хабарландыру алады.'),
    ('Нажмите на иконку "Выдача" в секции для сотрудников ПВЗ.',
     'Tap the "Extradition" icon in the pickup point employees section.',
     'ПВЗ қызметкерлеріне арналған бөлімдегі "Беру" белгішесін басыңыз.'),
    ('После сканирования система покажет информацию о клиенте: имя, ПВЗ, ячейку хранения и список чеков с посылками.',
     'After scanning, the system will display client information: name, pickup point, storage cell and list of receipts with parcels.',
     'Сканерлегеннен кейін жүйе клиент туралы ақпаратты көрсетеді: аты, ПВЗ, сақтау ұяшығы және посылкалары бар чектер тізімі.'),
    ('Для быстрой выдачи нажмите "Оформить выдачу". Для проверки — "Проверить и выдать", чтобы отсканировать QR-коды на каждом чеке.',
     'For quick issuance, click "Issue". For verification — "Verify and issue" to scan QR codes on each receipt.',
     'Жылдам беру үшін "Беруді рәсімдеу" түймесін басыңыз. Тексеру үшін әр чектегі QR-кодтарды сканерлеуге "Тексеру және беру" түймесін басыңыз.'),
    ('После оформления: посылки отмечены как выданные, ячейка освободится, клиент получит уведомление.',
     'After processing: parcels are marked as issued, the cell will become free, the client will receive a notification.',
     'Рәсімдегеннен кейін: посылкалар берілген ретінде белгіленеді, ұяшық босайды, клиент хабарландыру алады.'),

    # pp_warehouse_tutorial
    ('Это страница "Склад ПВЗ". Здесь отображаются все ячейки с посылками, ожидающими выдачи клиентам.',
     'This is the "Pickup point warehouse" page. All cells with parcels awaiting issuance to clients are displayed here.',
     'Бұл "ПВЗ қоймасы" беті. Мұнда клиенттерге берілуді күтіп тұрған посылкалары бар барлық ұяшықтар көрсетіледі.'),
    ('Номер ячейки отображается в квадрате. Нажмите на него, чтобы изменить номер ячейки. "Пол" означает ячейку 0.',
     'The cell number is displayed in a square. Click on it to change the cell number. "Floor" means cell 0.',
     'Ұяшық нөмірі квадратта көрсетіледі. Ұяшық нөмірін өзгерту үшін оны басыңыз. "Еден" — 0 ұяшығын білдіреді.'),
    ('Каждая ячейка разделена на подячейки по чекам. Это позволяет легко найти конкретные посылки клиента.',
     'Each cell is divided into sub-cells by receipts. This allows you to easily find specific client parcels.',
     'Әр ұяшық чектер бойынша ішкі ұяшықтарға бөлінген. Бұл клиенттің нақты посылкаларын оңай табуға мүмкіндік береді.'),
    ('Кнопка "Инвентаризация" создаёт печатный документ со списком всех клиентов, ячеек и посылок на складе.',
     'The "Inventory" button creates a printable document with a list of all clients, cells and parcels in the warehouse.',
     '"Түгендеу" түймесі қоймадағы барлық клиенттер, ұяшықтар мен посылкалар тізімі бар баспа құжатын жасайды.'),
    ('Используйте инвентаризацию для сверки реального содержимого склада с данными в системе.',
     'Use the inventory to reconcile the actual warehouse contents with the data in the system.',
     'Қойманың нақты құрамын жүйедегі деректермен салыстыру үшін түгендеуді қолданыңыз.'),
    ('Нажмите на иконку "Склад ПВЗ" в секции для сотрудников.',
     'Tap the "Pickup point warehouse" icon in the employees section.',
     'Қызметкерлерге арналған бөлімдегі "ПВЗ қоймасы" белгішесін басыңыз.'),
    ('Здесь отображаются все ячейки с посылками. Номер ячейки — в квадрате. Нажмите, чтобы изменить номер. "Пол" означает ячейку 0.',
     'All cells with parcels are displayed here. The cell number is in a square. Click to change the number. "Floor" means cell 0.',
     'Мұнда посылкалары бар барлық ұяшықтар көрсетіледі. Ұяшық нөмірі — квадратта. Нөмірді өзгерту үшін басыңыз. "Еден" — 0 ұяшығын білдіреді.'),

    # pp_restructure_tutorial
    ('Реструктуризация позволяет переназначить все ячейки на складе. Используйте её, когда нужно переорганизовать склад.',
     'Restructuring allows you to reassign all cells in the warehouse. Use it when you need to reorganize the warehouse.',
     'Қайта құрылымдау қоймадағы барлық ұяшықтарды қайта тағайындауға мүмкіндік береді. Қойманы қайта ұйымдастыру қажет болғанда қолданыңыз.'),
    ('Нажмите "Реструктуризация склада". Все номера ячеек будут удалены, а посылки останутся в системе.',
     'Click "Warehouse restructuring". All cell numbers will be deleted, but the parcels will remain in the system.',
     '"Қойманы қайта құрылымдау" түймесін басыңыз. Барлық ұяшық нөмірлері жойылады, ал посылкалар жүйеде қалады.'),
    ('После нажатия откроется страница назначения ячеек. Здесь 3 способа назначить ячейки: вручную, сканером или камерой.',
     'After clicking, the cell assignment page will open. There are 3 ways to assign cells here: manually, with a scanner or with a camera.',
     'Басқаннан кейін ұяшықтарды тағайындау беті ашылады. Мұнда ұяшықтарды тағайындаудың 3 тәсілі бар: қолмен, сканермен немесе камерамен.'),
    ('Сканер: отсканируйте QR-код чека — система найдёт клиента и назначит ячейку автоматически.',
     'Scanner: scan the receipt QR code — the system will find the client and assign the cell automatically.',
     'Сканер: чектің QR-кодын сканерлеңіз — жүйе клиентті тауып, ұяшықты автоматты түрде тағайындайды.'),
    ('Камера: если нет аппаратного сканера, откройте камеру телефона и наведите на QR-код чека.',
     'Camera: if there is no hardware scanner, open the phone camera and point it at the receipt QR code.',
     'Камера: аппараттық сканер болмаса, телефон камерасын ашып, чектің QR-кодына бағыттаңыз.'),
    ('Вручную: выберите клиента из списка и укажите номер ячейки (или оставьте пустым для автоназначения).',
     'Manually: select a client from the list and specify the cell number (or leave empty for auto-assignment).',
     'Қолмен: тізімнен клиентті таңдап, ұяшық нөмірін енгізіңіз (немесе автотағайындау үшін бос қалдырыңыз).'),
    ('Когда все ячейки назначены, нажмите "Завершить реструктуризацию". До завершения на складе будет мигать кнопка "Продолжить реструктуризацию".',
     'When all cells are assigned, click "Finish restructuring". Until completion, a blinking "Continue restructuring" button will be shown in the warehouse.',
     'Барлық ұяшықтар тағайындалғаннан кейін "Қайта құрылымдауды аяқтау" түймесін басыңыз. Аяқталғанға дейін қоймада "Қайта құрылымдауды жалғастыру" түймесі жыпылықтайды.'),
    ('Откроется страница назначения ячеек. 3 способа: вручную, сканером или камерой.',
     'The cell assignment page will open. 3 ways: manually, with a scanner or with a camera.',
     'Ұяшықтарды тағайындау беті ашылады. 3 тәсіл: қолмен, сканермен немесе камерамен.'),
    ('Камера: если нет аппаратного сканера, откройте камеру и наведите на QR-код чека.',
     'Camera: if there is no hardware scanner, open the camera and point it at the receipt QR code.',
     'Камера: аппараттық сканер болмаса, камераны ашып, чектің QR-кодына бағыттаңыз.'),
    ('Когда все ячейки назначены, нажмите "Завершить реструктуризацию".',
     'When all cells are assigned, click "Finish restructuring".',
     'Барлық ұяшықтар тағайындалғаннан кейін "Қайта құрылымдауды аяқтау" түймесін басыңыз.'),
]


def translate(content, lang_idx):
    # Sort by length desc so longer strings replace before shorter ones
    ordered = sorted(TRANSLATIONS, key=lambda x: len(x[0]), reverse=True)
    replaced = 0
    for ru, en, kk in ordered:
        tgt = en if lang_idx == 1 else kk
        # Escape Russian string for exact replacement
        if ru in content:
            content = content.replace(ru, tgt)
            replaced += 1
    return content, replaced


with open(SRC, encoding='utf-8') as f:
    src = f.read()

for lang_idx, out_path, label in [(1, OUT_EN, 'EN'), (2, OUT_KK, 'KK')]:
    out, count = translate(src, lang_idx)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(out)
    # Check for any remaining Cyrillic
    remaining = re.findall(r'[А-Яа-яЁё][А-Яа-яЁё \-.,!?:;()«»"0-9/]{3,}', out)
    remaining_uniq = list(dict.fromkeys(remaining))
    # Remove ones that are expected to remain (ПВЗ, QR etc)
    acceptable = {'ПВЗ'}
    leftover = [r for r in remaining_uniq if r.strip() not in acceptable and not all(ch in 'ПВЗQRабвгдежзQqRrqr-_0123456789.,:; ' for ch in r)]
    print(f'{label}: replaced {count} unique strings; remaining Cyrillic fragments: {len(leftover)}')
    for r in leftover[:30]:
        print(f'  LEFT: {r[:150]}')
