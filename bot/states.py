from aiogram.fsm.state import State, StatesGroup

class Checkout(StatesGroup):
    waiting_for_screenshot = State()

class Owner(StatesGroup):
    setting = State()
    service = State()
    vault_service = State()
    vault_text = State()
    users = State()
    broadcast = State()
    broadcast_confirm = State()
    refund = State()
    content_title = State()
    content_text = State()
    edit_content = State()
    rename_content = State()
    backup_password = State()
    restore_file = State()
    restore_password = State()
    restore_confirm = State()
    import_file = State()
    import_confirm = State()
