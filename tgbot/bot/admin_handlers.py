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
    return list(PickupPoint.objects.filter(is_active=True).values_list('premise_name', flat=True))


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

    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📍 ПВЗ: <b>{pvz_name}</b>\n"
        f"📦 Отправлено: {sent}\n"
        f"❌ Ошибки: {errors}\n"
        f"📊 Всего: {sent + errors}"
    )
    await state.clear()


@sync_to_async
def _get_broadcast_targets(pvz_name):
    """Получить список chat_id для рассылки."""
    from tgbot.models import TelegramProfile
    qs = TelegramProfile.objects.filter(is_active=True).select_related('user__userprofile__pickup')

    chat_ids = []
    for tp in qs:
        try:
            pickup = tp.user.userprofile.pickup
            if pvz_name == 'Все пункты' or (pickup and pickup.premise_name == pvz_name):
                chat_ids.append(tp.telegram_chat_id)
        except Exception:
            if pvz_name == 'Все пункты':
                chat_ids.append(tp.telegram_chat_id)
    return chat_ids