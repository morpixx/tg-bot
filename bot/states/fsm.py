from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SessionAddQR(StatesGroup):
    waiting_name = State()
    waiting_scan = State()
    waiting_2fa = State()


class SessionAddPhone(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_code = State()
    waiting_2fa = State()


class PostAdd(StatesGroup):
    waiting_type_choice = State()       # forward or manual
    waiting_forward = State()           # waiting forwarded message
    waiting_manual_type = State()       # text/photo/video
    waiting_manual_content = State()    # text or media+caption
    waiting_title = State()             # name for the post library


class ChatAdd(StatesGroup):
    waiting_chat = State()              # chat username / id


class ChatImport(StatesGroup):
    waiting_list = State()              # multiline text of chats


class CampaignCreate(StatesGroup):
    waiting_name = State()
    waiting_post = State()
    waiting_sessions = State()
    waiting_chats = State()
    waiting_settings = State()
    waiting_session_offsets = State()
    confirm = State()


class CampaignSettingsEdit(StatesGroup):
    waiting_field = State()
    waiting_value = State()


class CampaignSessionOffset(StatesGroup):
    waiting_offset = State()


class GlobalSettingsEdit(StatesGroup):
    waiting_value = State()


class AdminNotify(StatesGroup):
    waiting_message = State()   # message to broadcast to all users
