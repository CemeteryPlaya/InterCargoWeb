"""Обработчики для администраторов бота."""

import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from asgiref.sync import sync_to_async

from tgbot.bot.keyboards import get_admin_keyboard
from tgbot.bot.utils import get_telegram_profile, is_user_admin

router = Router()
logger = logging.getLogger(__name__)


class BroadcastStates(StatesGroup):
    selecting_pvz = State()
    entering_message = State()
    confirming = State()


class ReminderStates(StatesGroup):
    selecting_storage_days = State()


# ─── Админ-меню ──────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def admin_start(message: Message):
    profile = await get_telegram_profile(message.chat.id)
    if not profile or not await is_user_admin(profile):
        await message.answer("🚫 У вас нет прав администратора.")
        return

    await message.answer(
        "👨‍✈️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
    )


# ─── Напоминания ─────────────────────────────────────────────────────────────

@router.message(F.text == 'Напоминания о незабранных 🔔')
async def reminders_settings_start(message: Message, state: FSMContext):
    await state.clear()
    settings = await _get_or_create_reminder_settings()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 дня", callback_data="set_days:3"),
         InlineKeyboardButton(text="5 дней", callback_data="set_days:5"),
         InlineKeyboardButton(text="7 дней", callback_data="set_days:7")],
        [InlineKeyboardButton(text="Свой срок ✏️", callback_data="set_custom_days")],
        [InlineKeyboardButton(text="Настроить ПВЗ 📍", callback_data="manage_pvz_reminders")],
        [InlineKeyboardButton(text="🔔 Запустить напоминания", callback_data="force_remind_start")],
        [InlineKeyboardButton(text="Закрыть ❌", callback_data="close_admin_reminders")],
    ])

    await message.answer(
        f"⚙️ <b>Настройка напоминаний</b>\n\n"
        f"Текущие интервалы: <b>{settings.intervals} дней</b>\n"
        f"Выберите срок или настройте список ПВЗ:",
        reply_markup=kb,
    )


@sync_to_async
def _get_or_create_reminder_settings():
    from tgbot.models import ReminderSettings
    settings = ReminderSettings.objects.first()
    if not settings:
        settings = ReminderSettings.objects.create(is_active=True, intervals='3,5,7')
    return settings


@router.callback_query(F.data == "set_custom_days")
async def set_custom_days_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReminderStates.selecting_storage_days)
    await callback.message.edit_text(
        "📝 Введите количество дней (только число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="manage_reminders_back")]
        ]),
    )
    await callback.answer()


@router.message(ReminderStates.selecting_storage_days)
async def set_custom_days_save(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        await message.answer("❌ Пожалуйста, введите целое число дней.")
        return

    days = message.text.strip()
    await _update_reminder_intervals(days)
    await state.clear()
    await message.answer(f"✅ Срок хранения установлен: <b>{days} дней</b>.")
    await reminders_settings_start(message, state)


@sync_to_async
def _update_reminder_intervals(days):
    from tgbot.models import ReminderSettings
    settings = ReminderSettings.objects.first()
    if settings:
        settings.intervals = days
        settings.save(update_fields=['intervals'])


@router.callback_query(F.data == "manage_reminders_back")
async def manage_reminders_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await reminders_settings_start(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("set_days:"))
async def set_reminder_days(callback: CallbackQuery):
    days = callback.data.split(":")[1]
    await _update_reminder_intervals(days)
    await callback.answer(f"Срок хранения изменен на {days} дн.")
    await callback.message.edit_text(
        f"✅ Срок хранения установлен: <b>{days} дней</b>.\n\n"
        "Теперь выберите ПВЗ для которых включить напоминания:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Настроить ПВЗ 📍", callback_data="manage_pvz_reminders")],
            [InlineKeyboardButton(text="Закрыть ❌", callback_data="close_admin_reminders")],
        ]),
    )


@router.callback_query(F.data == "manage_pvz_reminders")
async def manage_pvz_reminders(callback: CallbackQuery):
    try:
        await _show_pvz_reminder_list(callback.message)
    except Exception as e:
        logger.error(f"Error in manage_pvz_reminders: {e}")
        await callback.message.answer("Выберите пункты выдачи:")
    await callback.answer()


async def _show_pvz_reminder_list(message: Message):
    pvzs = await _get_all_pvz()

    if not pvzs:
        await message.answer("Пункты выдачи не найдены.")
        return

    buttons = []
    for p in pvzs:
        status = "✅" if p['reminder_enabled'] else "☐"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {p['name']}",
            callback_data=f"toggle_pvz_rem:{p['id']}",
        )])

    buttons.append([InlineKeyboardButton(text="Готово ✅", callback_data="close_admin_reminders")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await message.edit_text("Выберите пункты выдачи для отправки напоминаний:", reply_markup=kb)
    except Exception:
        await message.answer("Выберите пункты выдачи для отправки напоминаний:", reply_markup=kb)


@sync_to_async
def _get_all_pvz():
    from register.models import PickupPoint
    return [
        {
            'id': p.id,
            'name': p.address or f'PVZ ID: {p.id}',
            'reminder_enabled': getattr(p, 'reminder_enabled', False),
        }
        for p in PickupPoint.objects.all()
    ]


@router.callback_query(F.data.startswith("toggle_pvz_rem:"))
async def toggle_pvz_reminder(callback: CallbackQuery):
    pvz_id = int(callback.data.split(":")[1])
    await _toggle_pvz_reminder_enabled(pvz_id)
    await _show_pvz_reminder_list(callback.message)
    await callback.answer()


@sync_to_async
def _toggle_pvz_reminder_enabled(pvz_id):
    from register.models import PickupPoint
    pvz = PickupPoint.objects.filter(id=pvz_id).first()
    if pvz:
        pvz.reminder_enabled = not pvz.reminder_enabled
        pvz.save(update_fields=['reminder_enabled'])


@router.callback_query(F.data == "close_admin_reminders")
async def close_admin_reminders(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Настройки сохранены")


# ─── Главное меню ────────────────────────────────────────────────────────────

@router.message(F.text == '🔙 Главное меню')
async def back_to_main_menu(message: Message, state: FSMContext):
    await state.clear()
    from tgbot.bot.handlers import start_command
    await start_command(message)


# ─── Отчёт по рассылке ───────────────────────────────────────────────────────

@router.message(F.text == '📊 Отчёт по рассылке')
async def broadcast_report(message: Message):
    profile = await get_telegram_profile(message.chat.id)
    if not profile or not await is_user_admin(profile):
        await message.answer("🚫 У вас нет прав администратора.")
        return

    logs = await _get_recent_broadcasts()
    if not logs:
        await message.answer("📭 Рассылки ещё не проводились.")
        return

    lines = ["📊 <b>Последние рассылки (10):</b>\n"]
    for log in logs:
        preview = log['text'][:60] + ('…' if len(log['text']) > 60 else '')
        author = f" — <i>{log['author']}</i>" if log['author'] else ''
        lines.append(
            f"🗓 <b>{log['created']}</b>{author}\n"
            f"📍 {log['pvz_name']}\n"
            f"📦 {log['sent']}/{log['total']} (❌ {log['errors']})\n"
            f"✉️ <i>{preview}</i>\n"
        )
    await message.answer('\n'.join(lines))


@sync_to_async
def _get_recent_broadcasts():
    from tgbot.models import BroadcastLog
    qs = BroadcastLog.objects.select_related('created_by').order_by('-created_at')[:10]
    return [
        {
            'pvz_name': b.pvz_name,
            'text': b.text,
            'sent': b.sent_count,
            'errors': b.error_count,
            'total': b.total_count,
            'created': b.created_at.strftime('%d.%m.%Y %H:%M'),
            'author': b.created_by.username if b.created_by else '',
        }
        for b in qs
    ]


# ─── Рассылка ────────────────────────────────────────────────────────────────

@router.message(F.text == '📢 Сделать рассылку')
async def broadcast_start(message: Message, state: FSMContext):
    pvzs = await _get_active_pvz_names()

    if not pvzs:
        await message.answer("Пункты выдачи не найдены.")
        return

    buttons = [[KeyboardButton(text='🌍 Все пункты')]]
    for i in range(0, len(pvzs), 2):
        row = [KeyboardButton(text=f"📍 {pvzs[i]}")]
        if i + 1 < len(pvzs):
            row.append(KeyboardButton(text=f"📍 {pvzs[i + 1]}"))
        buttons.append(row)
    buttons.append([KeyboardButton(text='❌ Отмена')])

    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите пункт выдачи для рассылки:", reply_markup=keyboard)
    await state.set_state(BroadcastStates.selecting_pvz)


@sync_to_async
def _get_active_pvz_names():
    from register.models import PickupPoint
    return list(PickupPoint.objects.filter(is_active=True).values_list('address', flat=True))


@router.message(F.text == '❌ Отмена', StateFilter(BroadcastStates))
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())


@router.message(BroadcastStates.selecting_pvz)
async def broadcast_pvz_selected(message: Message, state: FSMContext):
    pvz_name = message.text.replace('📍 ', '').replace('🌍 ', '')
    await state.update_data(selected_pvz=pvz_name)

    await message.answer(
        f"Выбрано: <b>{pvz_name}</b>\n\nВведите текст сообщения для рассылки:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text='❌ Отмена')]],
            resize_keyboard=True,
        ),
    )
    await state.set_state(BroadcastStates.entering_message)


@router.message(BroadcastStates.entering_message)
async def broadcast_message_entered(message: Message, state: FSMContext):
    if message.text == '❌ Отмена':
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=get_admin_keyboard())
        return

    data = await state.get_data()
    pvz_name = data['selected_pvz']
    await state.update_data(broadcast_text=message.text)

    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n"
        f"Пункт выдачи: <b>{pvz_name}</b>\n"
        f"───────────────────\n"
        f"{message.text}\n"
        f"───────────────────\n\n"
        f"Отправить сообщение?"
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='✅ Подтвердить и отправить')],
            [KeyboardButton(text='❌ Отмена')],
        ],
        resize_keyboard=True,
    )
    await message.answer(preview, reply_markup=keyboard)
    await state.set_state(BroadcastStates.confirming)


@router.message(BroadcastStates.confirming)
async def broadcast_confirm(message: Message, state: FSMContext):
    if message.text != '✅ Подтвердить и отправить':
        return

    data = await state.get_data()
    pvz_name = data['selected_pvz']
    text = data['broadcast_text']

    await message.answer("⏳ Рассылка запущена...", reply_markup=get_admin_keyboard())

    targets = await _get_broadcast_targets(pvz_name)

    sent = 0
    errors = 0
    bot = message.bot

    for chat_id in targets:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"📢 <b>Объявление ({pvz_name})</b>\n\n{text}",
            )
            sent += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to {chat_id}: {e}")
            errors += 1
        await asyncio.sleep(0.05)

    profile = await get_telegram_profile(message.chat.id)
    user_id = await sync_to_async(lambda: profile.user_id if profile else None)()
    await _save_broadcast_log(pvz_name, text, sent, errors, len(targets), user_id)

    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📍 ПВЗ: <b>{pvz_name}</b>\n"
        f"📦 Отправлено: {sent}\n"
        f"❌ Ошибки: {errors}\n"
        f"📊 Всего: {sent + errors}"
    )
    await state.clear()


@sync_to_async
def _save_broadcast_log(pvz_name, text, sent, errors, total, user_id):
    from tgbot.models import BroadcastLog
    BroadcastLog.objects.create(
        pvz_name=pvz_name, text=text,
        sent_count=sent, error_count=errors,
        total_count=total, created_by_id=user_id,
    )


@sync_to_async
def _get_broadcast_targets(pvz_name):
    """Получить список chat_id для рассылки."""
    from tgbot.models import TelegramProfile
    qs = TelegramProfile.objects.filter(is_active=True).select_related('user__userprofile__pickup')

    chat_ids = []
    for tp in qs:
        try:
            pickup = tp.user.userprofile.pickup
            if pvz_name == 'Все пункты' or (pickup and pickup.address == pvz_name):
                chat_ids.append(tp.telegram_chat_id)
        except Exception:
            if pvz_name == 'Все пункты':
                chat_ids.append(tp.telegram_chat_id)
    return chat_ids


# ─── Принудительная отправка напоминаний ─────────────────────────────────────

@router.callback_query(F.data == "force_remind_start")
async def force_remind_start(callback: CallbackQuery):
    pvzs = await _get_all_pvz()
    if not pvzs:
        await callback.answer("Пункты выдачи не найдены.", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(text="🌍 Все ПВЗ", callback_data="force_remind_run:all")]]
    for p in pvzs:
        buttons.append([InlineKeyboardButton(
            text=f"📍 {p['name']}",
            callback_data=f"force_remind_run:{p['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="manage_reminders_back")])

    try:
        await callback.message.edit_text(
            "🔔 <b>Принудительная отправка напоминаний</b>\n\n"
            "Выберите ПВЗ — напоминания будут отправлены всем пользователям этого ПВЗ, "
            "у которых есть незабранные посылки (статус «на ПВЗ»):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await callback.message.answer(
            "🔔 Выберите ПВЗ для принудительной отправки напоминаний:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("force_remind_run:"))
async def force_remind_run(callback: CallbackQuery):
    target = callback.data.split(":", 1)[1]
    pvz_id = None if target == 'all' else int(target)

    await callback.answer("Отправка запущена…")
    try:
        await callback.message.edit_text("⏳ Отправка напоминаний…")
    except Exception:
        pass

    targets = await _get_force_reminder_targets(pvz_id)

    # Группируем по пользователю — одно сообщение на пользователя
    from collections import defaultdict
    by_user = defaultdict(lambda: {
        'chat_id': None, 'track_count': 0,
        'pvz_name': '', 'working_hours': '',
    })
    for t in targets:
        u = by_user[t['user_id']]
        u['chat_id'] = t['chat_id']
        u['track_count'] += 1
        u['pvz_name'] = t['pvz_name']
        u['working_hours'] = t['working_hours']

    sent = 0
    errors = 0
    bot = callback.message.bot

    for data in by_user.values():
        try:
            text_msg = (
                f"📦 <b>Напоминание</b>\n\n"
                f"У вас {data['track_count']} посылок на пункте выдачи.\n"
                f"Пожалуйста, заберите их.\n\n"
                f"📍 Пункт выдачи: <b>{data['pvz_name']}</b>\n"
            )
            if data.get('working_hours'):
                text_msg += f"🕒 Время работы: <b>{data['working_hours']}</b>\n"
            await bot.send_message(chat_id=data['chat_id'], text=text_msg)
            sent += 1
        except Exception as e:
            logger.error(f"Force reminder to {data['chat_id']} failed: {e}")
            errors += 1
        await asyncio.sleep(0.05)

    await callback.message.answer(
        f"✅ <b>Напоминания отправлены!</b>\n\n"
        f"👥 Пользователей: <b>{len(by_user)}</b>\n"
        f"📦 Посылок всего: <b>{len(targets)}</b>\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибки: <b>{errors}</b>"
    )


@sync_to_async
def _get_force_reminder_targets(pvz_id):
    """Все пользователи с tracks в статусе 'ready' (опц. фильтр по ПВЗ)."""
    from myprofile.models import TrackCode
    from tgbot.models import TelegramProfile

    qs = (
        TrackCode.objects
        .filter(status='ready')
        .exclude(owner__isnull=True)
        .select_related('owner__userprofile__pickup')
    )
    if pvz_id is not None:
        qs = qs.filter(owner__userprofile__pickup_id=pvz_id)

    results = []
    for track in qs:
        try:
            pickup = track.owner.userprofile.pickup
            if not pickup:
                continue
            tp = TelegramProfile.objects.filter(user=track.owner, is_active=True).first()
            if not tp:
                continue
            results.append({
                'user_id': track.owner_id,
                'track_id': track.id,
                'chat_id': tp.telegram_chat_id,
                'pvz_name': pickup.premise_name or pickup.address,
                'working_hours': pickup.working_hours or '',
            })
        except Exception:
            continue
    return results