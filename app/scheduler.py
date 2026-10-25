from datetime import datetime
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func
from app.database import async_session, Word

async def send_daily_reminders(bot: Bot):
    async with async_session() as session:
        stmt = (
            select(Word.user_id, func.count(Word.id))
            .where(Word.next_review <= datetime.utcnow())
            .group_by(Word.user_id)
        )
        rows = (await session.execute(stmt)).all()

    for user_id, due_count in rows:
        if due_count > 0:
            try:
                await bot.send_message(
                    user_id,
                    f"⏰ <b>Xotirani yangilash vaqti!</b>\n"
                    f"Sizda takrorlash muddati kelgan <b>{due_count} ta</b> so'z bor.\n"
                    f"Unutib qo'ymaslik uchun <b>🧠 Aqlli takrorlash (SM-2)</b> tugmasini bosing!",
                    parse_mode="HTML"
                )
            except Exception:
                continue

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(send_daily_reminders, "cron", hour="8,14,21", minute=0, args=[bot])
    scheduler.start()
    return scheduler
.