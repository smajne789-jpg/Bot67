import asyncio
import logging
import os
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

DB_NAME = "giveaways.db"

class GiveawayState(StatesGroup):
    waiting_title = State()

def init_db():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message_id INTEGER,
            finished INTEGER DEFAULT 0
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER,
            user_id INTEGER,
            username TEXT,
            UNIQUE(giveaway_id, user_id)
        )
        """)
        conn.commit()

def create_giveaway(title: str):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO giveaways (title) VALUES (?)", (title,))
        conn.commit()
        return cur.lastrowid

def set_message_id(giveaway_id: int, message_id: int):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message_id, giveaway_id))
        conn.commit()

def add_participant(giveaway_id: int, user_id: int, username: str):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO participants (giveaway_id, user_id, username)
                VALUES (?, ?, ?)
            """, (giveaway_id, user_id, username))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def get_participants(giveaway_id: int):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, username
            FROM participants
            WHERE giveaway_id=?
            ORDER BY id ASC
        """, (giveaway_id,))
        return cur.fetchall()

def get_giveaway(giveaway_id: int):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, message_id, finished
            FROM giveaways
            WHERE id=?
        """, (giveaway_id,))
        return cur.fetchone()

def finish_giveaway(giveaway_id: int):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE giveaways SET finished=1 WHERE id=?", (giveaway_id,))
        conn.commit()

def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать розыгрыш", callback_data="create_giveaway")]
        ]
    )

def participate_keyboard(giveaway_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Участвовать", callback_data=f"join_{giveaway_id}")]
        ]
    )

@dp.message(Command("start"))
async def start_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Бот работает.")
        return
    await message.answer("Панель управления:", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "create_giveaway")
async def create_giveaway_btn(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer("Введите название розыгрыша:")
    await state.set_state(GiveawayState.waiting_title)
    await call.answer()

@dp.message(GiveawayState.waiting_title)
async def process_title(message: Message, state: FSMContext):
    title = message.text
    giveaway_id = create_giveaway(title)
    msg = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🎉 <b>Новый розыгрыш!</b>\n\n🏷 <b>{title}</b>\n\nУчастников: 0/6",
        reply_markup=participate_keyboard(giveaway_id)
    )
    set_message_id(giveaway_id, msg.message_id)
    await message.answer("✅ Розыгрыш создан!", reply_markup=admin_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("join_"))
async def join_callback(call: CallbackQuery):
    giveaway_id = int(call.data.split("_")[1])
    giveaway = get_giveaway(giveaway_id)

    if giveaway[3] == 1:
        await call.answer("Розыгрыш завершён", show_alert=True)
        return

    participants = get_participants(giveaway_id)
    if len(participants) >= 6:
        await call.answer("Участники уже набраны", show_alert=True)
        return

    username = call.from_user.username or call.from_user.full_name
    added = add_participant(giveaway_id, call.from_user.id, username)

    if not added:
        await call.answer("Вы уже участвуете", show_alert=True)
        return

    participants = get_participants(giveaway_id)

    await bot.edit_message_text(
        chat_id=CHANNEL_ID,
        message_id=giveaway[2],
        text=f"🎉 <b>Новый розыгрыш!</b>\n\n🏷 <b>{giveaway[1]}</b>\n\nУчастников: {len(participants)}/6",
        reply_markup=participate_keyboard(giveaway_id)
    )

    await call.answer("Вы участвуете!")

    if len(participants) == 6:
        await run_giveaway(giveaway_id)

async def run_giveaway(giveaway_id: int):
    giveaway = get_giveaway(giveaway_id)
    participants = get_participants(giveaway_id)
    finish_giveaway(giveaway_id)

    await bot.send_message(CHANNEL_ID, f"🎲 Розыгрыш <b>{giveaway[1]}</b> начинается!")
    dice_msg = await bot.send_dice(CHANNEL_ID, emoji="🎲")

    await asyncio.sleep(4)

    rolled = dice_msg.dice.value
    winner = participants[rolled - 1]
    participants_text = "\n".join([f"{i+1}. @{p[1]}" for i, p in enumerate(participants)])

    await bot.send_message(
        CHANNEL_ID,
        f"🏆 <b>Результат розыгрыша</b>\n\n🏷 <b>{giveaway[1]}</b>\n\n👥 Участники:\n{participants_text}\n\n🎲 Выпало: <b>{rolled}</b>\n🎉 Победитель: <b>@{winner[1]}</b>"
    )

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
