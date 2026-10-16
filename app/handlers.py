import os
import random
import asyncio
import logging
import re
import urllib.parse
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, PollAnswer,
    ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, delete

from app.database import async_session, User, Dictionary, Word

router = Router()

# --- FSM HOLATLARI ---
class BotStates(StatesGroup):
    waiting_dict_name = State()
    waiting_words = State()


# --- ASOSIY HUB (MARKAZIY MENYU) TUGMALARI ---
def get_start_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi lug'at yaratish", callback_data="action_create_dict")],
        [InlineKeyboardButton(text="📂 Mening lug'atlarim", callback_data="action_my_dicts_0")],
        [InlineKeyboardButton(text="🔥 Mening natijalarim", callback_data="action_streak")],
        [InlineKeyboardButton(text="❓ Qo'llanma", callback_data="action_help")]
    ])

def quiz_control_kb(is_paused: bool = False) -> ReplyKeyboardMarkup:
    toggle_btn = KeyboardButton(text="▶️ Davom etish") if is_paused else KeyboardButton(text="⏸ Pauza")
    return ReplyKeyboardMarkup(
        keyboard=[
            [toggle_btn, KeyboardButton(text="⏹ To'xtatish")],
            [KeyboardButton(text="🔄 Boshidan boshlash")]
        ],
        resize_keyboard=True
    )


# --- YORDAMCHI FUNKSIYALAR ---
async def ensure_user_exists(session, user_id: int, full_name: Optional[str] = None):
    user = await session.get(User, user_id)
    if not user:
        user = User(
            telegram_id=user_id,
            full_name=full_name or "Foydalanuvchi",
            streak_days=1,
            total_tests=0,
            total_correct=0
        )
        session.add(user)
        await session.flush()
    return user

async def update_user_streak(user_id: int, correct_count: int):
    try:
        async with async_session() as session:
            user = await session.get(User, user_id)
            if user:
                now = datetime.utcnow()
                if user.last_activity:
                    diff_days = (now.date() - user.last_activity.date()).days
                    if diff_days == 1:
                        user.streak_days = (user.streak_days or 0) + 1
                    elif diff_days > 1:
                        user.streak_days = 1
                else:
                    user.streak_days = 1

                user.last_activity = now
                user.total_tests = (user.total_tests or 0) + 1
                user.total_correct = (user.total_correct or 0) + correct_count
                await session.commit()
    except Exception as e:
        logging.error(f"Streak yangilashda xato: {e}")

def parse_word_line(line: str) -> Optional[Tuple[str, str]]:
    line = line.strip()
    if not line:
        return None

    cleaned = re.sub(r"^\s*(\d+[\.\)]\s*|[-•*]\s*)", "", line).strip()
    if not cleaned:
        return None

    for sep in [" — ", " – ", " - ", " − ", " = ", " : ", "\t"]:
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            en, uz = parts[0].strip(), parts[1].strip()
            if en and uz:
                return en[:250], uz[:250]

    for sep in ["—", "–", "−", "=", ":", "-"]:
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            en, uz = parts[0].strip(), parts[1].strip()
            if en and uz:
                return en[:250], uz[:250]

    multi_spaces = re.split(r"\s{2,}", cleaned, maxsplit=1)
    if len(multi_spaces) == 2:
        en, uz = multi_spaces[0].strip(), multi_spaces[1].strip()
        if en and uz:
            return en[:250], uz[:250]

    return None

def extract_words_from_text(text: str) -> List[Tuple[str, str]]:
    lines = text.strip().splitlines()
    words = []
    for line in lines:
        parsed = parse_word_line(line)
        if parsed:
            words.append(parsed)
    return words

def build_share_url(bot_username: str, dict_id: int, title: str, word_count: int) -> str:
    link = f"https://t.me/{bot_username}?start=dict_{dict_id}"
    share_text = f"📚 Lug'at: {title}\n📊 So'zlar soni: {word_count} ta\n\nBilimingizni sinab ko'ring:"
    return f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={urllib.parse.quote(share_text)}"


# --- QUIZ SESSIYASI KLASSI VA XOTIRASI ---
@dataclass
class QuizSession:
    user_id: int
    dict_id: int
    dict_name: str
    timer_seconds: int
    quiz_mode: str
    words: List[dict]
    current_index: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    skipped_count: int = 0
    consecutive_timeouts: int = 0
    is_paused: bool = False
    is_stopped: bool = False
    mistakes: List[dict] = field(default_factory=list)

    current_poll_id: Optional[str] = None
    current_poll_message_id: Optional[int] = None
    correct_option_id: Optional[int] = None
    answer_event: asyncio.Event = field(default_factory=asyncio.Event)
    user_answered: bool = False
    user_selected_option: Optional[int] = None
    task: Optional[asyncio.Task] = None

active_quizzes: Dict[int, QuizSession] = {}
user_last_mistakes: Dict[int, Tuple[int, str, int, str, List[dict]]] = {}


# --- /START VA ULASHISH (DEEP LINK) ---
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, bot: Bot):
    await state.clear()

    old_session = active_quizzes.get(message.from_user.id)
    if old_session and old_session.task and not old_session.task.done():
        old_session.is_stopped = True
        old_session.answer_event.set()
        old_session.task.cancel()
        active_quizzes.pop(message.from_user.id, None)

    try:
        async with async_session() as session:
            await ensure_user_exists(session, message.from_user.id, message.from_user.full_name)
            await session.commit()
    except Exception as e:
        logging.error(f"Foydalanuvchini saqlashda xatolik: {e}")

    # Ulashilgan ssilka: /start dict_123 yoki /start test_123
    if command.args and (command.args.startswith("dict_") or command.args.startswith("test_")):
        try:
            target_dict_id = int(command.args.split("_")[1])
            async with async_session() as session:
                original_dict = await session.get(Dictionary, target_dict_id)
                if not original_dict:
                    return await message.answer("⚠️ Test/Lug'at topilmadi yoki o'chirilgan.")

                creator = await session.get(User, original_dict.user_id)
                creator_name = creator.full_name if creator else "Foydalanuvchi"
                cnt = await session.scalar(select(func.count(Word.id)).where(Word.dict_id == target_dict_id))

            bot_info = await bot.get_me()
            share_url = build_share_url(bot_info.username, target_dict_id, original_dict.name, cnt)

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"quiz_start:{target_dict_id}")],
                [InlineKeyboardButton(text="↗️ Do'stlarga ulashish", url=share_url)],
                [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")]
            ])

            return await message.answer(
                f"📖 <b>Testga taklif qilindingiz!</b>\n\n"
                f"📚 <b>Mavzu:</b> {original_dict.name}\n"
                f"👤 <b>Muallif:</b> {creator_name}\n"
                f"📊 <b>Savollar soni:</b> {cnt} ta\n\n"
                "Tayyor bo'lsangiz, boshlash tugmasini bosing:",
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Ulashish havolasi xatosi: {e}")

    # Bosh menyu
    photo_path = "sample.jpg"
    caption = (
        "👋 <b>Lug'at yodlash platformasiga xush kelibsiz!</b>\n\n"
        "📋 So'zlarni kiritish namunasi yuqoridagi rasmda ko'rsatilgan.\n\n"
        "Quyidagi bo'limlardan birini tanlang:"
    )
    if os.path.exists(photo_path):
        await message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")
    else:
        await message.answer(caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")


# --- ASOSIY MENYUGA QAYTISH (HUB) ---
@router.callback_query(F.data == "back_to_hub")
async def back_to_hub_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    photo_path = "sample.jpg"
    caption = (
        "👋 <b>Asosiy menyu:</b>\n\n"
        "Quyidagi bo'limlardan birini tanlang:"
    )
    try:
        await call.message.delete()
    except Exception:
        pass
    if os.path.exists(photo_path):
        await call.message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")
    else:
        await call.message.answer(caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")


# --- QO'LLANMA ---
@router.callback_query(F.data == "action_help")
@router.message(Command("help"))
async def help_cmd(event: Message | CallbackQuery):
    photo_path = "sample.jpg"
    caption = (
        "💡 <b>Qo'llanma:</b>\n\n"
        "1. Yuqoridagi rasmdagidek qilib so'zlarni tayyorlang.\n"
        "2. Har bir qatorda bittadan so'z va uning tarjimasi bo'lsin.\n"
        "3. Ajratuvchi sifatida <b>-</b>, <b>—</b>, <b>:</b> yoki <b>=</b> ishlatishingiz mumkin.\n"
        "4. Tayyor so'zlaringizni bitta xabarda botga yuboring.\n"
        "5. Bot ularni saqlab, mukammal taymerli test qilib beradi!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")]
    ])

    if isinstance(event, CallbackQuery):
        try:
            await event.message.delete()
        except Exception:
            pass
        if os.path.exists(photo_path):
            await event.message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await event.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        if os.path.exists(photo_path):
            await event.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer(caption, reply_markup=kb, parse_mode="HTML")


# --- NATIJALAR (STREAK) ---
@router.callback_query(F.data == "action_streak")
@router.message(Command("streak"))
async def show_streak(event: Message | CallbackQuery):
    user_id = event.from_user.id
    async with async_session() as session:
        user = await session.get(User, user_id)
        streak = user.streak_days if user else 1
        tests_cnt = user.total_tests if user else 0
        correct_cnt = user.total_correct if user else 0

    text = (
        f"🔥 <b>Sizning natijalaringiz:</b>\n\n"
        f"⚡️ <b>Kunlik Streak:</b> {streak} kun ketma-ket 🔥\n"
        f"🎯 <b>Topshirilgan testlar:</b> {tests_cnt} ta\n"
        f"✅ <b>To'g'ri javoblar:</b> {correct_cnt} ta\n\n"
        f"<i>Har kuni kamida bitta test topshiring va olovingizni so'ndirmang!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")]
    ])

    if isinstance(event, CallbackQuery):
        try:
            await event.message.delete()
        except Exception:
            pass
        await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


# --- YANGI LUG'AT YARATISH ---
@router.callback_query(F.data == "action_create_dict")
@router.message(Command("new_dict"))
async def action_create_dict_cb(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BotStates.waiting_dict_name)

    photo_path = "sample.jpg"
    caption = (
        "✍️ <b>Yangi lug'at yaratish:</b>\n\n"
        "1. Avval lug'at nomini yozib yuboring (Masalan: <i>English 1-kun</i> yoki <i>IELTS Unit 3</i>).\n"
        "2. So'ngra yuqoridagi rasmdagidek so'zlaringizni bitta xabarda yuborasiz.\n\n"
        "<i>(Yoki birdaniga yuqoridagi rasmdagidek tayyor so'zlaringizni tashlasangiz ham bot ularni avtomatik saqlab oladi).</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data="back_to_hub")]
    ])

    if isinstance(event, CallbackQuery):
        try:
            await event.message.delete()
        except Exception:
            pass
        if os.path.exists(photo_path):
            await event.message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await event.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        if os.path.exists(photo_path):
            await event.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer(caption, reply_markup=kb, parse_mode="HTML")

@router.message(BotStates.waiting_dict_name)
async def handle_dict_name(message: Message, state: FSMContext):
    text = message.text.strip()
    lines = text.splitlines()

    detected_words = extract_words_from_text(text)
    if len(lines) > 1 and len(detected_words) >= 2:
        dict_name = f"Lug'at ({datetime.now().strftime('%d.%m.%Y %H:%M')})"
        try:
            async with async_session() as session:
                await ensure_user_exists(session, message.from_user.id, message.from_user.full_name)
                new_dict = Dictionary(user_id=message.from_user.id, name=dict_name)
                session.add(new_dict)
                await session.flush()
                for en, uz in detected_words:
                    session.add(Word(dict_id=new_dict.id, user_id=message.from_user.id, en_word=en, uz_word=uz))
                await session.commit()
                dict_id = new_dict.id

            await state.clear()
            bot_info = await message.bot.get_me()
            share_url = build_share_url(bot_info.username, dict_id, dict_name, len(detected_words))

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"quiz_start:{dict_id}")],
                [InlineKeyboardButton(text="↗️ Ulashish", url=share_url)],
                [InlineKeyboardButton(text="📂 Mening lug'atlarim", callback_data="action_my_dicts_0")]
            ])
            await message.answer(
                f"🎉 <b>Lug'at muvaffaqiyatli saqlandi!</b>\n\n"
                f"📚 <b>Mavzu:</b> {dict_name}\n"
                f"📊 <b>Savollar:</b> {len(detected_words)} ta\n"
                f"🔗 <b>Havola:</b> <code>https://t.me/{bot_info.username}?start=dict_{dict_id}</code>",
                reply_markup=kb,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logging.error(f"So'zlarni saqlashda xato: {e}")
            await message.answer(f"❌ Xatolik yuz berdi: {e}")
            return

    name = text[:100]
    await state.update_data(dict_name=name)
    await state.set_state(BotStates.waiting_words)

    photo_path = "sample.jpg"
    caption = (
        f"✅ <b>\"{name}\"</b> lug'ati ochildi!\n\n"
        "Xuddi shu rasmdagidek qilib so'zlarni yozing yoki tayyorini copy qilib bitta xabarda tashlang.\n\n"
        "<i>(Har bir qatorda bittadan so'z va uning tarjimasi bo'lsa bo'ldi).</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data="back_to_hub")]
    ])

    if os.path.exists(photo_path):
        await message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(caption, reply_markup=kb, parse_mode="HTML")

@router.message(BotStates.waiting_words)
async def handle_words_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    dict_id = data.get("dict_id")
    dict_name = data.get("dict_name", "Yangi lug'at")

    if not message.text:
        await message.answer("Iltimos, so'zlarni matn ko'rinishida yuboring.")
        return

    words_to_add = extract_words_from_text(message.text)
    if not words_to_add:
        photo_path = "sample.jpg"
        caption = (
            "⚠️ <b>So'zlar aniqlanmadi!</b>\n\n"
            "Xuddi shu rasmdagidek qilib so'zlarni yozing yoki tayyorini copy qilib bitta xabarda tashlang.\n\n"
            "<i>(Har bir qatorda bittadan so'z va uning tarjimasi bo'lsa kifoya).</i>"
        )
        if os.path.exists(photo_path):
            await message.answer_photo(photo=FSInputFile(photo_path), caption=caption, parse_mode="HTML")
        else:
            await message.answer(caption, parse_mode="HTML")
        return

    async with async_session() as session:
        await ensure_user_exists(session, message.from_user.id, message.from_user.full_name)

        if not dict_id:
            new_dict = Dictionary(user_id=message.from_user.id, name=dict_name)
            session.add(new_dict)
            await session.flush()
            dict_id = new_dict.id
        else:
            d = await session.get(Dictionary, dict_id)
            if d:
                # Agar boshqa foydalanuvchining lug'atiga qo'shishga urinsa:
                if d.user_id != message.from_user.id:
                    return await message.answer("⚠️ Boshqa foydalanuvchining lug'atiga so'z qo'sha olmaysiz.")
                dict_name = d.name

        for en, uz in words_to_add:
            session.add(Word(dict_id=dict_id, user_id=message.from_user.id, en_word=en, uz_word=uz))
        await session.commit()

        total_words = await session.scalar(select(func.count(Word.id)).where(Word.dict_id == dict_id))

    await state.clear()
    bot_info = await bot.get_me()
    share_url = build_share_url(bot_info.username, dict_id, dict_name, total_words)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"quiz_start:{dict_id}")],
        [InlineKeyboardButton(text="↗️ Ulashish", url=share_url)],
        [InlineKeyboardButton(text="📂 Mening lug'atlarim", callback_data="action_my_dicts_0")]
    ])

    await message.answer(
        f"🎉 <b>Lug'at muvaffaqiyatli saqlandi!</b>\n\n"
        f"📚 <b>Mavzu:</b> {dict_name}\n"
        f"📊 <b>So'zlar:</b> {total_words} ta\n"
        f"🔗 <b>Havola:</b> <code>https://t.me/{bot_info.username}?start=dict_{dict_id}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )


# --- SAHIFALASH (PAGINATION) BILAN FAQAT FOYDALANUVCHINING O'Z LUG'ATLARI ---
@router.callback_query(F.data.startswith("action_my_dicts_"))
@router.message(Command("my_dicts"))
async def show_my_dicts(event: Message | CallbackQuery):
    user_id = event.from_user.id
    page = 0
    if isinstance(event, CallbackQuery):
        page = int(event.data.split("_")[-1])

    async with async_session() as session:
        await ensure_user_exists(session, user_id, event.from_user.full_name)
        # Faqat o'zi yaratgan lug'atlarni chiqaramiz!
        total_dicts = await session.scalar(select(func.count(Dictionary.id)).where(Dictionary.user_id == user_id))
        stmt = select(Dictionary).where(Dictionary.user_id == user_id).order_by(Dictionary.id.desc()).offset(page * 10).limit(10)
        dicts = (await session.execute(stmt)).scalars().all()

    if not dicts and total_dicts == 0:
        text = "📭 Siz hali birorta ham lug'at yaratmabsiz."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi lug'at yaratish", callback_data="action_create_dict")],
            [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")]
        ])
        if isinstance(event, CallbackQuery):
            try:
                await event.message.delete()
            except Exception:
                pass
            return await event.message.answer(text, reply_markup=kb)
        return await event.answer(text, reply_markup=kb)

    buttons = []
    for d in dicts:
        buttons.append([InlineKeyboardButton(text=f"📘 {d.name}", callback_data=f"view_dict_{d.id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"action_my_dicts_{page - 1}"))
    if (page + 1) * 10 < total_dicts:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"action_my_dicts_{page + 1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="➕ Yangi lug'at yaratish", callback_data="action_create_dict")])
    buttons.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    text = f"📂 <b>Siz yaratgan lug'atlar ({total_dicts} ta):</b>\n<i>Sahifa: {page + 1}</i>\n\nKerakli lug'at ustiga bosing:"
    if isinstance(event, CallbackQuery):
        try:
            await event.message.delete()
        except Exception:
            pass
        await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


# --- BITTA LUG'ATNI KO'RISH (FAQAT EGASI O'CHIRA OLADI) ---
@router.callback_query(F.data.startswith("view_dict_"))
async def view_single_dict(call: CallbackQuery, bot: Bot):
    dict_id = int(call.data.split("view_dict_")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi yoki o'chirilgan.", show_alert=True)
        cnt = await session.scalar(select(func.count(Word.id)).where(Word.dict_id == dict_id))

    bot_info = await bot.get_me()
    share_url = build_share_url(bot_info.username, dict_id, d.name, cnt)
    is_owner = (d.user_id == call.from_user.id)

    # Agar egasi bo'lsa: o'chirish va so'z qo'shish chiqadi.
    # Agar begona bo'lsa: o'chirish tugmasi umuman chiqmaydi!
    if is_owner:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Testni ishlash", callback_data=f"quiz_start:{dict_id}")],
            [
                InlineKeyboardButton(text="➕ So'z qo'shish", callback_data=f"add_words:{dict_id}"),
                InlineKeyboardButton(text="📥 Eksport", callback_data=f"export_d:{dict_id}")
            ],
            [InlineKeyboardButton(text="↗️ Do'stlarga ulashish", url=share_url)],
            [InlineKeyboardButton(text="🗑 Lug'atni o'chirish", callback_data=f"del_d:{dict_id}")],
            [InlineKeyboardButton(text="⬅️ Ortga (Lug'atlar ro'yxati)", callback_data="action_my_dicts_0")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Testni ishlash", callback_data=f"quiz_start:{dict_id}")],
            [InlineKeyboardButton(text="📥 Eksport", callback_data=f"export_d:{dict_id}")],
            [InlineKeyboardButton(text="↗️ Do'stlarga ulashish", url=share_url)],
            [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")]
        ])

    try:
        await call.message.delete()
    except Exception:
        pass

    await call.message.answer(
        f"📝 <b>Lug'at ma'lumotlari:</b>\n\n"
        f"📚 <b>Mavzu:</b> {d.name}\n"
        f"📊 <b>Savollar soni:</b> {cnt} ta\n"
        f"🔗 <b>Havola:</b> <code>https://t.me/{bot_info.username}?start=dict_{dict_id}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("export_d:"))
async def export_dict_cb(call: CallbackQuery):
    dict_id = int(call.data.split(":")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi!", show_alert=True)
        words = (await session.execute(select(Word).where(Word.dict_id == dict_id))).scalars().all()

    if not words:
        return await call.answer("Bu lug'atda so'zlar yo'q!", show_alert=True)

    text_lines = [f"{w.en_word} - {w.uz_word}" for w in words]
    formatted = "\n".join(text_lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Lug'atga qaytish", callback_data=f"view_dict_{dict_id}")]
    ])

    await call.message.answer(
        f"📥 <b>\"{d.name}\"</b> lug'ati (jami {len(words)} ta so'z):\n\n"
        f"<code>{formatted}</code>\n\n"
        f"<i>💡 Matn ustiga bir marta bossangiz, Telegram uni nusxalab oladi!</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("add_words:"))
async def add_words_cb(call: CallbackQuery, state: FSMContext):
    dict_id = int(call.data.split(":")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi!", show_alert=True)
        if d.user_id != call.from_user.id:
            return await call.answer("⛔️ Faqat lug'at muallifi so'z qo'sha oladi!", show_alert=True)
        dict_name = d.name

    await state.update_data(dict_id=dict_id, dict_name=dict_name)
    await state.set_state(BotStates.waiting_words)

    photo_path = "sample.jpg"
    caption = (
        f"➕ <b>\"{dict_name}\"</b> lug'atiga yangi so'zlar qo'shish:\n\n"
        "Xuddi shu rasmdagidek qilib yangi so'zlarni bitta xabarda yuboring."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data=f"view_dict_{dict_id}")]
    ])

    if os.path.exists(photo_path):
        await call.message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data.startswith("del_d:"))
async def delete_dict_cb(call: CallbackQuery):
    dict_id = int(call.data.split(":")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi!", show_alert=True)
        if d.user_id != call.from_user.id:
            return await call.answer("⛔️ Bu testni o'chirishga ruxsatingiz yo'q! Uni faqat muallifi o'chira oladi.", show_alert=True)
        dict_name = d.name

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Ha, o'chirilsin", callback_data=f"confirm_del_{dict_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"view_dict_{dict_id}")
        ]
    ])

    await call.message.edit_text(
        f"⚠️ <b>\"{dict_name}\"</b> lug'atini va undagi barcha so'zlarni o'chirishni tasdiqlaysizmi?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("confirm_del_"))
async def confirm_del_cb(call: CallbackQuery):
    dict_id = int(call.data.split("confirm_del_")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi.", show_alert=True)
        if d.user_id != call.from_user.id:
            return await call.answer("⛔️ Bu testni o'chirishga ruxsatingiz yo'q!", show_alert=True)

        await session.execute(delete(Word).where(Word.dict_id == dict_id))
        await session.execute(delete(Dictionary).where(Dictionary.id == dict_id))
        await session.commit()

    await call.answer("✅ Test bazadan butunlay o'chirildi!", show_alert=True)
    await show_my_dicts(call)


# --- QUIZ TEST BOSHLASH: YO'NALISH VA VAQTNI TANLASH ---
@router.callback_query(F.data.startswith("quiz_start:"))
async def quiz_start_select_dir(call: CallbackQuery):
    dict_id = int(call.data.split(":")[1])
    async with async_session() as session:
        d = await session.get(Dictionary, dict_id)
        if not d:
            return await call.answer("Lug'at topilmadi!", show_alert=True)
        cnt = await session.scalar(select(func.count(Word.id)).where(Word.dict_id == dict_id))

    if cnt < 2:
        return await call.answer("Test uchun lug'atda kamida 2 ta so'z bo'lishi kerak!", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 ➡️ 🇺🇿 (Inglizcha — O'zbekcha)", callback_data=f"quiz_dir:{dict_id}:en_uz")],
        [InlineKeyboardButton(text="🇺🇿 ➡️ 🇬🇧 (O'zbekcha — Inglizcha)", callback_data=f"quiz_dir:{dict_id}:uz_en")],
        [InlineKeyboardButton(text="🔀 Aralash rejim (Mix)", callback_data=f"quiz_dir:{dict_id}:mix")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"view_dict_{dict_id}")]
    ])

    await call.message.edit_text(
        f"🎯 <b>\"{d.name}\"</b> — Test yo'nalishini tanlang:\n\n"
        f"📊 So'zlar soni: <b>{cnt} ta</b>\n"
        "Qaysi uslubda test topshirmoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("quiz_dir:"))
async def quiz_dir_selected(call: CallbackQuery):
    parts = call.data.split(":")
    dict_id = int(parts[1])
    mode = parts[2]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡️ 10 soniya", callback_data=f"quiz_time:{dict_id}:{mode}:10"),
            InlineKeyboardButton(text="⚡️ 15 soniya", callback_data=f"quiz_time:{dict_id}:{mode}:15"),
        ],
        [
            InlineKeyboardButton(text="⚡️ 20 soniya", callback_data=f"quiz_time:{dict_id}:{mode}:20"),
            InlineKeyboardButton(text="⚡️ 30 soniya", callback_data=f"quiz_time:{dict_id}:{mode}:30"),
        ],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"quiz_start:{dict_id}")]
    ])

    await call.message.edit_text(
        "⏱ <b>Har bir savol uchun vaqt me'yorini tanlang:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("quiz_time:"))
async def quiz_time_selected(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    dict_id = int(parts[1])
    mode = parts[2]
    timer_seconds = int(parts[3])

    try:
        await call.message.delete()
    except Exception:
        pass

    await start_quiz_session(call.from_user.id, dict_id, timer_seconds, mode, bot, call.message)
    await call.answer()

async def start_quiz_session(user_id: int, dict_id: int, timer_seconds: int, quiz_mode: str, bot: Bot, event_msg: Message, custom_words: Optional[List[dict]] = None, custom_name: Optional[str] = None):
    old = active_quizzes.get(user_id)
    if old and old.task and not old.task.done():
        old.is_stopped = True
        old.answer_event.set()
        old.task.cancel()

    if custom_words:
        word_list = custom_words.copy()
        dict_name = custom_name or "Xatolar ustida ishlash"
    else:
        async with async_session() as session:
            d = await session.get(Dictionary, dict_id)
            if not d:
                await event_msg.answer("Lug'at topilmadi!", reply_markup=get_start_hub_kb())
                return
            dict_name = d.name
            words_db = (await session.execute(select(Word).where(Word.dict_id == dict_id))).scalars().all()

        if len(words_db) < 2:
            await event_msg.answer("⚠️ Test boshlash uchun kamida 2 ta so'z bo'lishi kerak!")
            return

        word_list = [{"id": w.id, "en": w.en_word, "uz": w.uz_word} for w in words_db]

    random.shuffle(word_list)

    quiz_session = QuizSession(
        user_id=user_id,
        dict_id=dict_id,
        dict_name=dict_name,
        timer_seconds=timer_seconds,
        quiz_mode=quiz_mode,
        words=word_list
    )
    active_quizzes[user_id] = quiz_session

    mode_title = "🇬🇧 ➡️ 🇺🇿" if quiz_mode == "en_uz" else ("🇺🇿 ➡️ 🇬🇧" if quiz_mode == "uz_en" else "🔀 Aralash (Mix)")

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"🚀 <b>\"{dict_name}\"</b> test boshlandi!\n\n"
            f"🎯 Yo'nalish: <b>{mode_title}</b>\n"
            f"⏱ Har bir savol: <b>{timer_seconds} soniya</b>\n"
            f"📝 Jami savollar: <b>{len(word_list)} ta</b>"
        ),
        reply_markup=quiz_control_kb(is_paused=False),
        parse_mode="HTML"
    )

    quiz_session.task = asyncio.create_task(run_quiz_loop(quiz_session, bot))

async def run_quiz_loop(session: QuizSession, bot: Bot):
    user_id = session.user_id
    try:
        while session.current_index < len(session.words) and not session.is_stopped:
            while session.is_paused and not session.is_stopped:
                await asyncio.sleep(0.5)

            if session.is_stopped:
                break

            current_word = session.words[session.current_index]

            current_mode = session.quiz_mode
            if current_mode == "mix":
                current_mode = random.choice(["en_uz", "uz_en"])

            if current_mode == "uz_en":
                q_word = current_word["uz"].strip()
                correct_ans = current_word["en"].strip()
                other_answers = list({
                    w["en"].strip() for w in session.words 
                    if w["en"].strip().lower() != correct_ans.lower()
                })
                question_text = f"[{session.current_index + 1}/{len(session.words)}] 🇺🇿 <b>{q_word}</b> — inglizchasi qaysi?"
            else:
                q_word = current_word["en"].strip()
                correct_ans = current_word["uz"].strip()
                other_answers = list({
                    w["uz"].strip() for w in session.words 
                    if w["uz"].strip().lower() != correct_ans.lower()
                })
                question_text = f"[{session.current_index + 1}/{len(session.words)}] 🇬🇧 <b>{q_word}</b> — o'zbekchasi qaysi?"

            distractors = random.sample(other_answers, min(3, len(other_answers)))
            options = distractors + [correct_ans]
            unique_options = list(dict.fromkeys(options))

            for fallback in ["boshqa", "noto'g'ri", "variant"]:
                if len(unique_options) >= 2:
                    break
                if fallback not in unique_options:
                    unique_options.append(fallback)

            random.shuffle(unique_options)
            correct_idx = unique_options.index(correct_ans)

            session.correct_option_id = correct_idx
            session.answer_event = asyncio.Event()
            session.user_answered = False
            session.user_selected_option = None

            try:
                poll_msg = await bot.send_poll(
                    chat_id=user_id,
                    question=question_text[:300],
                    options=[opt[:100] for opt in unique_options],
                    type="quiz",
                    correct_option_id=correct_idx,
                    is_anonymous=False,
                    open_period=session.timer_seconds
                )
                session.current_poll_id = poll_msg.poll.id
                session.current_poll_message_id = poll_msg.message_id
            except Exception as e:
                logging.error(f"Poll yuborishda xatolik: {e}")
                session.current_index += 1
                continue

            try:
                await asyncio.wait_for(session.answer_event.wait(), timeout=session.timer_seconds)
                session.consecutive_timeouts = 0
                if session.user_selected_option == correct_idx:
                    session.correct_count += 1
                else:
                    session.wrong_count += 1
                    session.mistakes.append(current_word)

                try:
                    await bot.stop_poll(chat_id=user_id, message_id=session.current_poll_message_id)
                except Exception:
                    pass

                await asyncio.sleep(1.5)

            except asyncio.TimeoutError:
                session.skipped_count += 1
                session.consecutive_timeouts += 1
                session.mistakes.append(current_word)

                try:
                    await bot.stop_poll(chat_id=user_id, message_id=session.current_poll_message_id)
                except Exception:
                    pass

                if session.consecutive_timeouts >= 2 and not session.is_stopped:
                    session.is_paused = True
                    await bot.send_message(
                        chat_id=user_id,
                        text=(
                            "⏸ <b>Ketma-ket 2 ta savolga javob berilmadi!</b>\n"
                            "Test avtomatik ravishda <b>pauza</b> qilindi.\n\n"
                            "Davom ettirish uchun pastdagi <b>▶️ Davom etish</b> tugmasini bosing."
                        ),
                        reply_markup=quiz_control_kb(is_paused=True),
                        parse_mode="HTML"
                    )
                    while session.is_paused and not session.is_stopped:
                        await asyncio.sleep(0.5)

                await asyncio.sleep(1.0)

            session.current_index += 1

        await finish_quiz(session, bot)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Quiz siklida kutilmagan xatolik: {e}", exc_info=True)

async def finish_quiz(session: QuizSession, bot: Bot):
    user_id = session.user_id
    total_questions = len(session.words)
    pct = round((session.correct_count / total_questions) * 100) if total_questions > 0 else 0

    await update_user_streak(user_id, session.correct_count)

    if session.mistakes:
        user_last_mistakes[user_id] = (session.dict_id, session.dict_name, session.timer_seconds, session.quiz_mode, session.mistakes)

    bot_info = await bot.get_me()
    share_url = build_share_url(bot_info.username, session.dict_id, session.dict_name, total_questions)

    kb_rows = [
        [InlineKeyboardButton(text="🔄 Qayta topshirish", callback_data=f"quiz_restart:{session.dict_id}:{session.quiz_mode}:{session.timer_seconds}")]
    ]

    if session.mistakes and len(session.mistakes) >= 2:
        kb_rows.append([
            InlineKeyboardButton(text=f"❌ Xatolar ustida ishlash ({len(session.mistakes)} ta)", callback_data="quiz_retry_mistakes")
        ])

    kb_rows.append([
        InlineKeyboardButton(text="↗️ Do'stlarga ulashish", url=share_url)
    ])
    kb_rows.append([
        InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_hub")
    ])

    report_text = (
        "🏁 <b>Test yakunlandi!</b>\n\n"
        f"📚 <b>Mavzu:</b> {session.dict_name}\n"
        f"📊 <b>Jami savollar:</b> {total_questions} ta\n"
        f"✅ <b>To'g'ri javoblar:</b> {session.correct_count} ta ({pct}%)\n"
        f"❌ <b>Xato javoblar:</b> {session.wrong_count} ta\n"
        f"⏳ <b>Tashlab ketilgan:</b> {session.skipped_count} ta\n\n"
        "<i>Kerakli amalni tanlang:</i>"
    )

    active_quizzes.pop(user_id, None)

    await bot.send_message(
        chat_id=user_id,
        text="🏁 Natijangiz hisoblandi:",
        reply_markup=ReplyKeyboardRemove()
    )

    await bot.send_message(
        chat_id=user_id,
        text=report_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="HTML"
    )


# --- POLL JAVOBINI USHLASH ---
@router.poll_answer()
async def handle_poll_answer(quiz_answer: PollAnswer):
    user_id = quiz_answer.user.id
    session = active_quizzes.get(user_id)
    if not session:
        return

    if session.current_poll_id == quiz_answer.poll_id:
        session.user_answered = True
        session.user_selected_option = quiz_answer.option_ids[0] if quiz_answer.option_ids else -1
        session.answer_event.set()


# --- TEST BOSHQARUV TUGMALARI ---
@router.message(F.text == "⏸ Pauza")
async def pause_quiz_handler(message: Message, bot: Bot):
    session = active_quizzes.get(message.from_user.id)
    if not session or session.is_stopped:
        return

    if session.is_paused:
        return

    session.is_paused = True

    if session.current_poll_message_id:
        try:
            await bot.stop_poll(chat_id=message.from_user.id, message_id=session.current_poll_message_id)
        except Exception:
            pass

    await message.answer(
        "⏸ <b>Test vaqtincha to'xtatildi.</b>\n"
        "Davom ettirish uchun pastdagi <b>▶️ Davom etish</b> tugmasini bosing.",
        reply_markup=quiz_control_kb(is_paused=True),
        parse_mode="HTML"
    )

@router.message(F.text == "▶️ Davom etish")
async def resume_quiz_handler(message: Message):
    session = active_quizzes.get(message.from_user.id)
    if not session or session.is_stopped:
        return

    if not session.is_paused:
        return

    session.is_paused = False
    session.consecutive_timeouts = 0
    await message.answer(
        "▶️ <b>Test davom ettirilmoqda...</b>",
        reply_markup=quiz_control_kb(is_paused=False),
        parse_mode="HTML"
    )

@router.message(F.text == "⏹ To'xtatish")
async def stop_quiz_handler(message: Message, bot: Bot):
    session = active_quizzes.get(message.from_user.id)
    if not session or session.is_stopped:
        return

    session.is_stopped = True
    session.answer_event.set()

    if session.current_poll_message_id:
        try:
            await bot.stop_poll(chat_id=message.from_user.id, message_id=session.current_poll_message_id)
        except Exception:
            pass

    await message.answer("⏹ <b>Test yakunlanmoqda...</b>", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")

@router.message(F.text == "🔄 Boshidan boshlash")
async def restart_quiz_msg_handler(message: Message, bot: Bot):
    session = active_quizzes.get(message.from_user.id)
    if not session:
        return

    if session.current_poll_message_id:
        try:
            await bot.stop_poll(chat_id=message.from_user.id, message_id=session.current_poll_message_id)
        except Exception:
            pass

    if session.task and not session.task.done():
        session.is_stopped = True
        session.answer_event.set()
        session.task.cancel()

    session.current_index = 0
    session.correct_count = 0
    session.wrong_count = 0
    session.skipped_count = 0
    session.consecutive_timeouts = 0
    session.is_paused = False
    session.is_stopped = False
    session.mistakes.clear()
    random.shuffle(session.words)

    await message.answer(
        "🔄 <b>Test boshidan boshlandi!</b>",
        reply_markup=quiz_control_kb(is_paused=False),
        parse_mode="HTML"
    )
    session.task = asyncio.create_task(run_quiz_loop(session, bot))

@router.callback_query(F.data.startswith("quiz_restart:"))
async def quiz_restart_cb(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    dict_id = int(parts[1])
    quiz_mode = parts[2]
    timer_seconds = int(parts[3])

    try:
        await call.message.delete()
    except Exception:
        pass

    await start_quiz_session(call.from_user.id, dict_id, timer_seconds, quiz_mode, bot, call.message)
    await call.answer()

@router.callback_query(F.data == "quiz_retry_mistakes")
async def quiz_retry_mistakes_cb(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    mistake_info = user_last_mistakes.get(user_id)
    if not mistake_info or len(mistake_info[4]) < 2:
        return await call.answer("Xatolar topilmadi yoki 2 tadan kam!", show_alert=True)

    dict_id, dict_name, timer_seconds, quiz_mode, mistakes = mistake_info
    try:
        await call.message.delete()
    except Exception:
        pass

    await start_quiz_session(
        user_id=user_id,
        dict_id=dict_id,
        timer_seconds=timer_seconds,
        quiz_mode=quiz_mode,
        bot=bot,
        event_msg=call.message,
        custom_words=mistakes,
        custom_name=f"{dict_name} (Xatolar)"
    )
    await call.answer()

@router.callback_query(F.data == "quiz_to_main_menu")
async def quiz_to_main_menu_cb(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    photo_path = "sample.jpg"
    caption = "👋 <b>Asosiy menyu:</b>\n\nQuyidagi bo'limlardan birini tanlang:"
    if os.path.exists(photo_path):
        await call.message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")
    else:
        await call.message.answer(caption, reply_markup=get_start_hub_kb(), parse_mode="HTML")
    await call.answer()


# --- FOYDALANUVCHI TO'G'RIDAN-TO'G'RI MATN TASHLAGANDA ---
@router.message(F.text)
async def handle_direct_text(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    current_state = await state.get_state()

    if current_state:
        return

    detected_words = extract_words_from_text(text)
    if detected_words:
        dict_name = f"Lug'at ({datetime.now().strftime('%d.%m.%Y %H:%M')})"
        try:
            async with async_session() as session:
                await ensure_user_exists(session, message.from_user.id, message.from_user.full_name)
                new_dict = Dictionary(user_id=message.from_user.id, name=dict_name)
                session.add(new_dict)
                await session.flush()
                for en, uz in detected_words:
                    session.add(Word(dict_id=new_dict.id, user_id=message.from_user.id, en_word=en, uz_word=uz))
                await session.commit()
                dict_id = new_dict.id

            bot_info = await bot.get_me()
            share_url = build_share_url(bot_info.username, dict_id, dict_name, len(detected_words))

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"quiz_start:{dict_id}")],
                [InlineKeyboardButton(text="↗️ Ulashish", url=share_url)],
                [InlineKeyboardButton(text="📂 Mening lug'atlarim", callback_data="action_my_dicts_0")]
            ])

            await message.answer(
                f"🎉 <b>Lug'at muvaffaqiyatli saqlandi!</b>\n\n"
                f"📚 <b>Mavzu:</b> {dict_name}\n"
                f"📊 <b>So'zlar:</b> {len(detected_words)} ta\n"
                f"🔗 <b>Havola:</b> <code>https://t.me/{bot_info.username}?start=dict_{dict_id}</code>",
                reply_markup=kb,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logging.error(f"To'g'ridan-to'g'ri so'zlarni saqlashda xato: {e}", exc_info=True)
            await message.answer(f"❌ Xatolik yuz berdi: {e}")
            return

    text_resp = (
        "🤷‍♂️ <b>Kechirasiz, men sizni tushunmadim.</b>\n\n"
        "Botdan foydalanish uchun quyidagi menyudan kerakli bo'limni tanlang:"
    )
    await message.answer(text_resp, reply_markup=get_start_hub_kb(), parse_mode="HTML")