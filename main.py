"""
Telegram Self-Bot (Userbot)
===========================

ربات سلف‌ساز تلگرام که با اکانت کاربر لاگین میشه و هر کلمه‌ای
که در گروه با پسوند «روشن سرور» نوشته بشه، هر ۵ دقیقه یکبار تکرار میکنه.

ساختار:
  - `bot`  : ربات کنترل (Bot API) که کاربر باهاش چت میکنه تا لاگین کنه
  - `user` : یوزربات (همان اکانت کاربر) که در گروه‌ها پیام میفرسته

دستورات:
  در چت خصوصی با ربات کنترل:
    /start    شروع / اتصال اکانت
    /help     راهنما
    /status   وضعیت و ارسال‌های فعال
    /logout   خروج از اکانت

  در هر گروهی که اکانتت عضو هست:
    <کلمه> روشن سرور   -> شروع ارسال هر ۵ دقیقه
    <کلمه> خاموش سرور  -> توقف ارسال
"""

import os
import re
import asyncio
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError


# ------------------------------------------------------------------
# پیکربندی از متغیرهای محیطی
# ------------------------------------------------------------------
API_ID = int(os.environ.get("API_ID", "0") or "0")
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
# فاصله ارسال به ثانیه (پیش‌فرض ۳۰۰ = ۵ دقیقه)
SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "300") or "300")

if not API_ID or not API_HASH:
    raise RuntimeError(
        "API_ID و API_HASH لازم است. از https://my.telegram.org/apps بگیر."
    )
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN لازم است. با @BotFather یک ربات بساز.")
if not OWNER_ID:
    raise RuntimeError("OWNER_ID لازم است. آیدی عددی خودت رو از @userinfobot بگیر.")


# ------------------------------------------------------------------
# لاگ‌گذاری
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("selfbot")


# ------------------------------------------------------------------
# کلاینت‌ها
# ------------------------------------------------------------------
# ربات کنترل (Bot API) — برای چت با صاحب اکانت
bot = TelegramClient(StringSession(), API_ID, API_HASH)

# یوزربات (اکانت خود کاربر) — برای ارسال پیام در گروه‌ها
user = TelegramClient(
    StringSession(SESSION_STRING) if SESSION_STRING else StringSession(),
    API_ID, API_HASH,
)


# ------------------------------------------------------------------
# وضعیت‌ها
# ------------------------------------------------------------------
# جریان لاگین: owner_id -> {step, phone, code_hash}
login_flow = {}

# ارسال‌های فعال: (chat_id, word_lower) -> asyncio.Task
senders = {}


# ------------------------------------------------------------------
# الگوهای دستور (در گروه)
# ------------------------------------------------------------------
PATTERN_ON = re.compile(r"^(.+?)\s+روشن\s+سرور\s*$")
PATTERN_OFF = re.compile(r"^(.+?)\s+خاموش\s+سرور\s*$")


# ------------------------------------------------------------------
# حلقه ارسال کلمه
# ------------------------------------------------------------------
async def send_word_loop(chat_id: int, word: str) -> None:
    """`word` را به `chat_id` میفرستد، سپس هر SEND_INTERVAL ثانیه تکرار میکند."""
    try:
        await user.send_message(chat_id, word)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("Initial send failed (chat=%s word=%s): %s", chat_id, word, e)
        return

    while True:
        try:
            await asyncio.sleep(SEND_INTERVAL)
        except asyncio.CancelledError:
            raise
        try:
            await user.send_message(chat_id, word)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(
                "Send failed (chat=%s word=%s): %s. Will retry next interval.",
                chat_id, word, e,
            )


# ------------------------------------------------------------------
# پایان لاگین موفق
# ------------------------------------------------------------------
async def finish_login(event) -> None:
    """بعد از لاگین موفق، SESSION_STRING رو به کاربر میده."""
    session_str = user.session.save()
    me = await user.get_me()
    await event.respond(
        f"✅ لاگین موفق بود!\n"
        f"👤 اکانت: {me.first_name} (@{me.username})\n\n"
        f"📝 این متن رو کپی کن و در Railway به عنوان متغیر محیطی "
        f"با نام `SESSION_STRING` ست کن، بعد ری‌استارت کن:\n\n"
        f"`{session_str}`",
        link_preview=False,
    )
    login_flow.pop(OWNER_ID, None)


# ------------------------------------------------------------------
# هندلر ربات کنترل (چت خصوصی با صاحب)
# ------------------------------------------------------------------
@bot.on(events.NewMessage(from_users=OWNER_ID))
async def control_handler(event):
    text = event.raw_text.strip()
    state = login_flow.get(OWNER_ID, {})

    # مرحله: منتظر شماره تلفن
    if state.get("step") == "phone":
        phone = text
        try:
            result = await user.send_code_request(phone)
        except Exception as e:
            await event.respond(f"❌ خطا در ارسال کد: `{e}`\n\nدوباره شماره رو بفرست:")
            return
        state["phone"] = phone
        state["code_hash"] = result.phone_code_hash
        state["step"] = "code"
        await event.respond("📨 کد تایید به تلگرامت ارسال شد. کد رو بفرست:")
        return

    # مرحله: منتظر کد تایید
    if state.get("step") == "code":
        try:
            await user.sign_in(state["phone"], text, state["code_hash"])
        except SessionPasswordNeededError:
            state["step"] = "password"
            await event.respond("🔐 اکانت رمز دو مرحله‌ای داره. رمز رو بفرست:")
            return
        except Exception as e:
            await event.respond(f"❌ خطا: `{e}`\n\nکد رو دوباره بفرست:")
            return
        await finish_login(event)
        return

    # مرحله: منتظر رمز ۲FA
    if state.get("step") == "password":
        try:
            await user.sign_in(password=text)
        except Exception as e:
            await event.respond(f"❌ خطا: `{e}`\n\nرمز رو دوباره بفرست:")
            return
        await finish_login(event)
        return

    # دستورات معمولی
    if text == "/start":
        if SESSION_STRING and await user.is_user_authorized():
            me = await user.get_me()
            await event.respond(
                f"👋 سلام!\n"
                f"👤 اکانت متصل: {me.first_name} (@{me.username})\n"
                f"📊 وضعیت: آنلاین\n\n"
                f"برای راهنما /help رو بفرست."
            )
        else:
            login_flow[OWNER_ID] = {"step": "phone"}
            await event.respond(
                "👋 سلام!\n\n"
                "شماره تلفن اکانتی که میخوای بهش وصل بشی رو با کد کشور بفرست.\n"
                "مثال: `+989123456789`"
            )
        return

    if text == "/help":
        await event.respond(
            "📖 راهنما:\n\n"
            "1️⃣ توی هر گروهی که اکانتت عضو هست، بنویس:\n"
            "   `<کلمه> روشن سرور`\n"
            "   مثال: `سلام روشن سرور`\n\n"
            f"   👉 هر {SEND_INTERVAL // 60} دقیقه اون کلمه ارسال میشه.\n\n"
            "2️⃣ برای توقف:\n"
            "   `<همون کلمه> خاموش سرور`\n\n"
            "3️⃣ دستورات ربات کنترل:\n"
            "   `/start` - شروع / اتصال اکانت\n"
            "   `/status` - وضعیت و ارسال‌های فعال\n"
            "   `/help` - این راهنما\n"
            "   `/logout` - خروج از اکانت"
        )
        return

    if text == "/status":
        if not (SESSION_STRING and await user.is_user_authorized()):
            await event.respond("❌ اکانتی وصل نیست. `/start` رو بزن.")
            return
        me = await user.get_me()
        if senders:
            lines = [f"• `{w}` در چت `{c}`" for (c, w) in senders.keys()]
            list_str = "\n".join(lines)
        else:
            list_str = "هیچ ارسال فعالی نیست."
        await event.respond(
            f"✅ اکانت: {me.first_name} (@{me.username})\n"
            f"📊 ارسال‌های فعال:\n{list_str}"
        )
        return

    if text == "/logout":
        if await user.is_user_authorized():
            await user.log_out()
        await event.respond(
            "✅ از اکانت خارج شدی.\n"
            "SESSION_STRING رو از Railway پاک کن."
        )
        return


# ------------------------------------------------------------------
# هندلر یوزربات (در گروه‌ها)
# ------------------------------------------------------------------
@user.on(events.NewMessage(outgoing=True))
async def selfbot_handler(event):
    # فقط در گروه‌ها (نه چت خصوصی)
    if event.is_private:
        return

    text = event.raw_text
    chat_id = event.chat_id

    # جلوگیری از لوپ: پیام‌های ارسالی خود ربات رو نادیده بگیر
    text_stripped = text.strip().lower()
    for (cid, w) in senders.keys():
        if cid == chat_id and w == text_stripped:
            return

    # دستور: <کلمه> روشن سرور
    m = PATTERN_ON.match(text)
    if m:
        word = m.group(1).strip()
        if not word:
            return
        key = (chat_id, word.lower())
        if key in senders:
            return  # از قبل فعاله
        task = asyncio.create_task(send_word_loop(chat_id, word))
        senders[key] = task
        log.info("Sender ON: chat=%s word=%s", chat_id, word)
        try:
            await event.message.delete()
        except Exception:
            pass
        return

    # دستور: <کلمه> خاموش سرور
    m = PATTERN_OFF.match(text)
    if m:
        word = m.group(1).strip()
        if not word:
            return
        key = (chat_id, word.lower())
        task = senders.pop(key, None)
        if task:
            task.cancel()
            log.info("Sender OFF: chat=%s word=%s", chat_id, word)
        try:
            await event.message.delete()
        except Exception:
            pass
        return


# ------------------------------------------------------------------
# ورودی اصلی
# ------------------------------------------------------------------
async def main():
    # راه‌اندازی ربات کنترل
    await bot.start(bot_token=BOT_TOKEN)
    bot_me = await bot.get_me()
    log.info("Control bot started as @%s", bot_me.username)

    # اتصال یوزربات
    await user.connect()
    if SESSION_STRING:
        if await user.is_user_authorized():
            me = await user.get_me()
            log.info("Userbot logged in as %s (@%s)", me.first_name, me.username)
        else:
            log.warning(
                "SESSION_STRING نامعتبر یا منقضی شده. "
                "برای لاگین مجدد در ربات کنترل /start بفرست."
            )
    else:
        log.warning(
            "SESSION_STRING تنظیم نشده. "
            "در ربات کنترل /start بفرست تا لاگین کنی."
        )

    # پیام راه‌اندازی به صاحب ربات
    try:
        is_authed = SESSION_STRING and await user.is_user_authorized()
        status_msg = "✅ وصل" if is_authed else "❌ وصل نیست — /start بزن"
        await bot.send_message(
            OWNER_ID,
            f"🤖 ربات خودکار آماده‌ست!\n\n"
            f"📊 وضعیت اکانت: {status_msg}\n\n"
            f"برای راهنما /help رو بفرست.",
        )
    except Exception as e:
        log.error("Failed to send startup message: %s", e)

    # اجرا تا زمان قطع
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
