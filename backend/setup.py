"""Database-free bootstrap. No purchases or research are stored on Heroku disk."""
import os

from dotenv import load_dotenv


def pending():
    load_dotenv()
    return (os.getenv('APP_ENV') == 'production' or bool(os.getenv('DYNO'))) and not os.getenv('DATABASE_URL', '').strip()


def web_app():
    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.get('/')
    def index():
        return '<h1>Setup pending</h1><p>Owner: open the Telegram bot and send /adminpanel to connect permanent storage.</p>'

    @app.get('/health')
    def health():
        return jsonify(status='setup_required', payments_enabled=False)

    @app.route('/api/<path:path>', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    def unavailable(path):
        return jsonify(error='Database setup required'), 503
    return app


def authorized(message, owner):
    return bool(message.from_user and message.from_user.id == owner and message.chat.type == 'private')


async def run():
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    owner = int(os.environ['ADMIN_ID'])
    if owner <= 0:
        raise ValueError('ADMIN_ID must be positive')
    bot = Bot(os.environ['BOT_TOKEN'], default=DefaultBotProperties(protect_content=True))
    dp = Dispatcher()
    menu = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔌 Connect database in Heroku', url='https://dashboard.heroku.com/apps')]])

    @dp.errors()
    async def error(event):
        # Never log messages or upstream errors containing credentials.
        return True

    @dp.message()
    async def message(msg):
        if not authorized(msg, owner):
            await msg.answer('Bot setup is in progress. Purchases are not available yet.')
            return
        if (msg.text or '').split('@')[0] in {'/start', '/adminpanel', '/cancel'}:
            await msg.answer(
                'Owner setup panel. Tap Connect database, select this app, then Settings → Reveal Config Vars. '
                'Set DATABASE_URL to your PostgreSQL session-pooler URL. Remove stale MIGRATION_DATABASE_URL. '
                'Heroku restarts the bot automatically; then send /start. Keep the original encryption seed/keys. '
                'Enter credentials only on Heroku, not in this chat. Purchases remain disabled until setup completes.',
                reply_markup=menu)
        else:
            # A misplaced credential should not remain in Telegram history.
            try:
                await msg.delete()
            except Exception:
                pass
            await msg.answer('Use /adminpanel. Enter database credentials only in Heroku Config Vars.')

    @dp.callback_query()
    async def callback(query):
        await query.answer('Setup pending. Send /adminpanel in a private chat.', show_alert=True)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=['message', 'callback_query'], close_bot_session=False)
    finally:
        await bot.session.close()
