import asyncio
import logging
import socket
import sys
from typing import Optional
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramNetworkError
from aiohttp.client_exceptions import ClientConnectorError

from app.config import BOT_TOKEN, PROXY_URL
from app.database import init_db
from app.handlers import router

# Windows tizimida ProactorEventLoop'ning [WinError 121] Semaphore timeout xatolarini
# bartaraf qilish uchun SelectorEventLoop'ni faollashtiramiz (VPN'siz barqaror ishlaydi)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)

# VPN'siz, mahalliy provayderlar (Uztelecom, Beeline, Ucell va h.k.)da barqaror ishlash mexanizmi:
# 1. Faqat IPv4 (AF_INET) - provayderlarda ishlamaydigan IPv6 marshrutlariga urinmaydi.
# 2. sock_connect=5.0s - Windows'ning 21 soniyalik qotishini (Semaphore timeout) 5 soniyada to'xtatib qayta ulaydi.
# 3. keepalive_timeout=30s - Har bir so'rov uchun yangi port ochib Windows portlarini to'ldirmaydi.
# 4. Avtomatik qayta urinish - mikro-uzilish bo'lsa sessiyani yangilab uzluksiz davom etadi.
class RobustIPv4AiohttpSession(AiohttpSession):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # aiogram start_polling ichida self.timeout + polling_timeout hisoblaydi, shuning uchun float bo'lishi shart
        self.timeout = 60.0

    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,
                limit=30,
                keepalive_timeout=30,
                enable_cleanup_closed=True,
                ssl=True,
                ttl_dns_cache=300
            )
            session_timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=5.0,
                sock_connect=5.0
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=session_timeout,
                json_serialize=self.json_dumps
            )
        return self._session

    async def make_request(self, bot: Bot, method, timeout: Optional[int] = None):
        req_total = float(timeout) if timeout is not None else float(self.timeout)
        custom_timeout = aiohttp.ClientTimeout(
            total=max(req_total + 10.0, 20.0),
            connect=5.0,
            sock_connect=5.0,
            sock_read=max(req_total + 10.0, 20.0)
        )

        for attempt in range(3):
            try:
                return await super().make_request(bot, method, timeout=custom_timeout)
            except (TelegramNetworkError, ClientConnectorError, asyncio.TimeoutError, OSError) as e:
                logging.warning(f"⚠️ Tarmoq xatoligi (urinish {attempt + 1}/3): {e}")
                if self._session and not self._session.closed:
                    try:
                        await self._session.close()
                    except Exception:
                        pass
                    self._session = None
                if attempt == 2:
                    raise e
                await asyncio.sleep(1.0)

async def setup_commands(bot: Bot):
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🔄 Bosh menyu"),
            BotCommand(command="my_dicts", description="📚 Mening lug'atlarim"),
            BotCommand(command="new_dict", description="➕ Yangi lug'at yaratish"),
            BotCommand(command="streak", description="🔥 Natijalarim (Streak)"),
            BotCommand(command="help", description="ℹ️ Qo'llanma")
        ])
        logging.info("Bot buyruqlari (Menu) muvaffaqiyatli o'rnatildi.")
    except Exception as e:
        logging.warning(f"Buyruqlarni o'rnatishda xatolik: {e}")

async def main():
    logging.info("Ma'lumotlar bazasi initsializatsiya qilinmoqda...")
    try:
        await init_db()
        logging.info("Ma'lumotlar bazasi muvaffaqiyatli ulandi va jadvallar yaratildi.")
    except Exception as e:
        logging.error(f"❌ Baza bilan bog'lanishda XATOLIK: {e}", exc_info=True)
        logging.error("PostgreSQL serveri ishlayotganini va .env fayldagi ma'lumotlarni tekshiring.")
        return

    session = RobustIPv4AiohttpSession(proxy=PROXY_URL) if PROXY_URL else RobustIPv4AiohttpSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    try:
        while True:
            try:
                logging.info("Telegram serveriga ulanilmoqda (IPv4)...")
                await bot.delete_webhook(drop_pending_updates=True)
                await setup_commands(bot)
                logging.info("✅ Bot muvaffaqiyatli ishga tushdi va xabarlarni kutmoqda!")
                await dp.start_polling(bot)
                break
            except (TelegramNetworkError, ClientConnectorError, OSError) as e:
                logging.warning(
                    f"⚠️ Tarmoqda vaqtinchalik uzilish: {e}. 3 soniyadan so'ng qayta ulaniladi..."
                )
                await asyncio.sleep(3)
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                logging.error(f"Kutilmagan xatolik: {e}", exc_info=True)
                await asyncio.sleep(3)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")