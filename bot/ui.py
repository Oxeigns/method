from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label,data in row]
        for row in rows])

MAIN = keyboard([('🛒 View Services','catalog')], [('👤 My Profile & Purchases','profile')], [('📞 Support','support')])
ADMIN = keyboard([('📊 Analytics','admin:analytics'),('💳 Verification Queue','admin:queue')],
                 [('⚙️ Payment / Support','admin:settings'),('💰 Service Settings','admin:services')],
                 [('🔐 Manage Content','admin:vault'),('👥 Manage Users','admin:users')],
                 [('📢 Broadcast','admin:broadcast'),('↩️ Stars Refund','admin:refund')],
                 [('📦 Content Backup','content:backup'),('📥 Restore / Import','content:restore')])
CANCEL = keyboard([('✖️ Cancel','cancel')])
