# 📚 Telegram Lug'at Yodlash Boti (Quiz & Flashcards)

Foydalanuvchilarga hech qanday ortiqcha fayllar (Word/Excel) yoki murakkab dasturlarsiz, Telegram ichida oddiy matn (Copy-Paste) orqali o'z lug'atini yaratish, do'stlariga ulashish (Share link) va Telegramning o'rnatilgan Poll (Quiz) so'rovnomasi yordamida tez va qiziqarli yodlash imkonini beruvchi mukammal Telegram bot.

---

## 🚀 Asosiy Imkoniyatlar

1. **Tezkor Lug'at Yaratish (Copy-Paste)**:
   - Istalgancha so'zlarni bitta xabarda quyidagi formatda yuborish:
     ```plaintext
     apple - olma
     book - kitob
     color - rang
     ```
   - Turli ajratuvchilar (`-`, `—`, `=`) va tartib raqamlarini avtomatik tozalash va parse qilish.

2. **Lug'atni Ulashish (Deep-linking)**:
   - Maxsus havola yaratish: `https://t.me/<bot_username>?start=share_<dict_id>`
   - Boshqa foydalanuvchi havolani bosganda, lug'at va uning barcha so'zlari to'liq uning profiliga klonlanadi.

3. **Professional Quiz Test Rejimi (Telegram Native Poll)**:
   - **Taymerni tanlash**: 10s, 15s, 20s, 30s.
   - **Telegram Quiz Poll**: Zerikarli modal ogohlantirishlarsiz (`show_alert`), to'g'ridan-to'g'ri Telegram interfeysida to'g'ri/xato animatsiyasi.
   - **Aktiv Boshqaruv**:
     - `⏸ Pauza` — Testni vaqtincha to'xtatish.
     - `▶️ Davom etish` — Testni pauza qilingan joyidan davom ettirish.
     - `⏹ To'xtatish` — Testni muddatidan oldin yakunlash va hisobot olish.
     - `🔄 Boshidan boshlash` — Savollarni yangidan aralashtirib boshlash.
   - **Xavfsiz Avtomatik Pauza**: Foydalanuvchi ketma-ket 2 ta savolga vaqtida javob bermasa, bot testni avtomatik ravishda pauza qiladi.

4. **Natijalar va Tahlil**:
   - Jami savollar soni
   - To'g'ri javoblar va foiz ko'rsatkichi
   - Xato javoblar soni
   - Tashlab ketilgan (vaqti o'tib ketgan) savollar soni
   - `🔄 Qayta topshirish` va `📚 Asosiy menyu` tugmalari

---

## 🛠 Texnik Stek

- **Til**: Python 3.11+
- **Framework**: aiogram 3.13+ (Asinxron)
- **Ma'lumotlar bazasi**: PostgreSQL + SQLAlchemy 2.0 (asyncpg drayveri, `pool_size=20`, `pool_pre_ping=True`)
- **Holatlar boshqaruvi**: FSM (MemoryStorage)
- **Konteynerizatsiya**: Docker & Docker Compose

---

## 📁 Papka Tuzilmasi

```plaintext
BOT/
├── app/
│   ├── __init__.py
│   ├── config.py         # .env fayldan sozlamalarni o'qish
│   ├── database.py       # SQLAlchemy async modellar (User, Dictionary, Word)
│   └── handlers.py       # Barcha komandalar, FSM va Poll-quiz mantiqi
├── .env                  # Maxfiy kalitlar va parollar (BOT_TOKEN, DB_*)
├── .env.example          # Namuna konfiguratsiya fayli
├── Dockerfile            # Konteyner yaratish sozlamasi
├── docker-compose.yml    # PostgreSQL va Bot konteynerlarini birlashtirish
├── main.py               # Asosiy ishga tushirish fayli
├── requirements.txt      # Kutubxonalar ro'yxati
├── sample.jpg            # Foydalanuvchiga ko'rsatiladigan namuna rasm
└── README.md             # Qo'llanma
```

---

## ⚙️ O'rnatish va Ishga Tushirish

### 1. Docker Compose orqali (Tavsiya etiladi):
```bash
# 1. Loyihani yuklab oling va .env faylni to'ldiring:
cp .env.example .env
# .env ichiga BOT_TOKEN va parollarni kiriting

# 2. Docker orqali ishga tushiring:
docker compose up -d --build
```

### 2. Mahalliy (Lokal) Ishga Tushirish:
```bash
# 1. Virtual muhit yaratish va faollashtirish:
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 2. Kutubxonalarni o'rnatish:
pip install -r requirements.txt

# 3. .env faylni to'ldiring va botni ishga tushiring:
python main.py
```
