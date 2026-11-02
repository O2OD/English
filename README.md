# 📚 Telegram Lug'at Yodlash Boti (Quiz & Flashcards)

Foydalanuvchilarga hech qanday ortiqcha fayllar (Word/Excel) yoki murakkab dasturlarsiz, Telegram ichida oddiy matn (Copy-Paste) orqali o'z lug'atini yaratish, do'stlariga ulashish (Share link) va Telegramning o'rnatilgan Poll (Quiz) so'rovnomasi yordamida tez va qiziqarli yodlash imkonini beruvchi professional Telegram bot.

---

## 🚀 Asosiy Imkoniyatlar

1. **Tezkor Lug'at Yaratish (Copy-Paste)**:
   - Istalgancha so'zlarni bitta xabarda quyidagi formatda yuborish:
     ```plaintext
     apple - olma
     book - kitob
     color - rang
     ```
   - Turli ajratuvchilar (`-`, `—`, `–`, `−`, `=`, `:`, tab) va tartib raqamlarini avtomatik tozalash va parse qilish.

2. **Lug'atni Xavfsiz Ulashish (Deep-linking)**:
   - Maxsus havola yaratish: `https://t.me/<bot_username>?start=dict_<id>`
   - Do'stingiz havolani bosib testni to'g'ridan-to'g'ri ishlashi mumkin.
   - **Xavfsizlik**: Test faqat muallifning "Mening lug'atlarim" bo'limida ko'rinadi va faqat muallif tomonidan o'chirilishi mumkin.

3. **Professional Quiz Test Rejimi (Telegram Native Poll)**:
   - **Yo'nalishni tanlash**: 🇬🇧 ➡️ 🇺🇿, 🇺🇿 ➡️ 🇬🇧 yoki 🔀 Aralash rejim (Mix).
   - **Taymerni tanlash**: 10s, 15s, 20s, 30s.
   - **Tezkor Taymer To'xtatish**: Javob belgilangach, eski savol taymeri darhol to'xtatilib, yangi savol bilan to'qnashmaydi.
   - **Aktiv Boshqaruv**:
     - `⏸ Pauza` / `▶️ Davom etish` — Dinamik almashuvchi boshqaruv tugmasi.
     - `⏹ To'xtatish` — Testni muddatidan oldin yakunlash va hisobot olish.
     - `🔄 Boshidan boshlash` — Savollarni yangidan aralashtirib boshlash.
   - **Avtomatik Pauza**: Foydalanuvchi ketma-ket 2 ta savolga vaqtida javob bermasa, bot testni avtomatik ravishda pauza qiladi.

4. **Natijalar, Tahlil va Qo'shimcha Qulayliklar**:
   - To'g'ri, xato va tashlab ketilgan savollar tahlili.
   - **❌ Xatolar ustida ishlash** — Testda faqat xato qilingan so'zlardan qayta test tuzish.
   - **🔥 Kunlik Streak** — Har kungi faollikni hisoblab borish.
   - **📥 Bir bosishda Eksport** — Barcha so'zlarni bitta bosishda nusxalab olish.

---

## 🛠 Texnik Stek

- **Til**: Python 3.11+
- **Framework**: aiogram 3.13+ (Asinxron)
- **Ma'lumotlar bazasi**: PostgreSQL + SQLAlchemy 2.0 (asyncpg drayveri, `pool_size=20`, `pool_pre_ping=True`)
- **Holatlar boshqaruvi**: FSM (MemoryStorage)
- **Konteynerizatsiya**: Docker & Docker Compose
- **Tarmoq barqarorligi**: IPv4 majburiy ulanish, timeout nazorati, Windows va Linuxda uzluksiz ishlash.

---

## 📁 Papka Tuzilmasi

```plaintext
BOT/
├── app/
│   ├── __init__.py
│   ├── config.py         # .env fayldan sozlamalarni o'qish
│   ├── database.py       # SQLAlchemy async modellar (User, Dictionary, Word)
│   └── handlers.py       # Barcha komandalar, FSM va Poll-quiz mantiqi
├── .env                  # Maxfiy kalitlar va parollar (BOT_TOKEN, DB_*) - GitHub'ga kirmaydi
├── .env.example          # Namuna konfiguratsiya fayli
├── .gitignore            # Git istisno fayli
├── Dockerfile            # Konteyner yaratish sozlamasi
├── docker-compose.yml    # PostgreSQL va Bot konteynerlarini birlashtirish
├── main.py               # Asosiy ishga tushirish fayli
├── requirements.txt      # Kutubxonalar ro'yxati
├── sample.jpg            # Foydalanuvchiga ko'rsatiladigan namuna rasm
└── README.md             # Qo'llanma
```

---

## ⚙️ Serverda Ishga Tushirish (Deployment)

### 1. Docker Compose orqali (Tavsiya etiladi - 1 ta buyruq bilan):
Serverda Docker va Docker Compose o'rnatilgan bo'lsa:
```bash
# 1. Repozitoriydan kodni oling (yoki git pull qiling):
git clone <REPO_URL>
cd BOT

# 2. .env faylini yarating va BOT_TOKEN ni kiriting:
cp .env.example .env
nano .env

# 3. Docker konteynerlarini ishga tushiring:
docker compose up -d --build

# 4. Bot loglarini kuzatish:
docker compose logs -f bot
```

### 2. Mahalliy (Lokal) yoki Docker'siz Serverda Ishga Tushirish:
```bash
# 1. Virtual muhit yaratish va faollashtirish:
python3 -m venv venv
source venv/bin/activate    # Linux
# Windows: venv\Scripts\activate

# 2. Kutubxonalarni o'rnatish:
pip install -r requirements.txt

# 3. .env faylni to'ldiring:
cp .env.example .env
nano .env

# 4. Botni ishga tushiring:
python3 main.py
```
