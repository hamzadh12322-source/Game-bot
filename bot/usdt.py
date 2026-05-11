import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "8371295271:AAH0KNIAB8qHm1VTNhrGeQBqule_YoCRnGA"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    keyboard = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        text="💳 شحن عبر USDT",
        callback_data="usdt_charge"
    )

    keyboard.add(btn)

    bot.send_message(
        message.chat.id,
        "اختر طريقة الشحن:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data == "usdt_charge")
def usdt_charge(call):

    text = """
💳 شحن عبر USDT

📌 عنوان المحفظة:
0x9a82c889ed9acbc370ac3315134e6286e93a15d5

⚠️ يرجى التحويل فقط عبر شبكة BSC (BEP20)
"""

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="Markdown"
    )

bot.infinity_polling()
