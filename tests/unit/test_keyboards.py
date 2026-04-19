from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from bot.keyboards.main_menu import main_menu_kb
from bot.keyboards.utils import back_button, back_kb, confirm_kb, paginate

# ── Main menu ─────────────────────────────────────────────────────────────────

class TestMainMenu:
    def test_has_6_buttons_for_regular_user(self) -> None:
        kb = main_menu_kb(is_owner=False)
        buttons = [b for row in kb.inline_keyboard for b in row]
        assert len(buttons) == 6

    def test_owner_sees_admin_button(self) -> None:
        kb = main_menu_kb(is_owner=True)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:panel" in datas

    def test_regular_user_no_admin_button(self) -> None:
        kb = main_menu_kb(is_owner=False)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:panel" not in datas

    def test_has_sessions_button(self) -> None:
        kb = main_menu_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:sessions" in datas

    def test_has_campaigns_button(self) -> None:
        kb = main_menu_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:campaigns" in datas

    def test_has_posts_button(self) -> None:
        kb = main_menu_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:posts" in datas

    def test_has_stats_button(self) -> None:
        kb = main_menu_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:stats" in datas


# ── Utility keyboards ─────────────────────────────────────────────────────────

class TestBackButton:
    def test_default_callback(self) -> None:
        btn = back_button()
        assert btn.callback_data == "menu:main"

    def test_custom_callback(self) -> None:
        btn = back_button("menu:sessions")
        assert btn.callback_data == "menu:sessions"

    def test_text(self) -> None:
        btn = back_button()
        assert "Назад" in btn.text


class TestBackKb:
    def test_single_row(self) -> None:
        kb = back_kb()
        assert len(kb.inline_keyboard) == 1

    def test_custom_callback(self) -> None:
        kb = back_kb("menu:posts")
        assert kb.inline_keyboard[0][0].callback_data == "menu:posts"


class TestConfirmKb:
    def test_two_buttons(self) -> None:
        kb = confirm_kb("yes:1", "no:1")
        assert len(kb.inline_keyboard[0]) == 2

    def test_confirm_callback(self) -> None:
        kb = confirm_kb("yes:1", "no:1")
        assert kb.inline_keyboard[0][0].callback_data == "yes:1"

    def test_cancel_callback(self) -> None:
        kb = confirm_kb("yes:1", "no:1")
        assert kb.inline_keyboard[0][1].callback_data == "no:1"


# ── Pagination ────────────────────────────────────────────────────────────────

class TestPaginate:
    def test_empty_list(self) -> None:
        sliced, kb = paginate([], 0, page_size=8)
        assert sliced == []
        assert kb is None

    def test_fits_on_one_page(self) -> None:
        items = list(range(5))
        sliced, kb = paginate(items, 0, page_size=8)
        assert sliced == items
        assert kb is None

    def test_first_page(self) -> None:
        items = list(range(20))
        sliced, kb = paginate(items, 0, page_size=8)
        assert sliced == list(range(8))
        assert kb is not None

    def test_second_page(self) -> None:
        items = list(range(20))
        sliced, kb = paginate(items, 1, page_size=8)
        assert sliced == list(range(8, 16))

    def test_last_page(self) -> None:
        items = list(range(20))
        sliced, kb = paginate(items, 2, page_size=8)
        assert sliced == [16, 17, 18, 19]

    def test_page_clamped_to_last(self) -> None:
        items = list(range(5))
        sliced, _ = paginate(items, 999, page_size=8)
        assert sliced == items

    def test_negative_page_clamped_to_zero(self) -> None:
        items = list(range(5))
        sliced, _ = paginate(items, -1, page_size=8)
        assert sliced == items

    def test_pagination_keyboard_has_next_on_first_page(self) -> None:
        items = list(range(20))
        _, kb = paginate(items, 0, page_size=8, callback_prefix="pg")
        buttons = [b.callback_data for b in kb.inline_keyboard[0]]
        assert any("pg:1" in (b or "") for b in buttons)

    def test_pagination_keyboard_has_prev_on_last_page(self) -> None:
        items = list(range(20))
        _, kb = paginate(items, 2, page_size=8, callback_prefix="pg")
        buttons = [b.callback_data for b in kb.inline_keyboard[0]]
        assert any("pg:1" in (b or "") for b in buttons)


# ── Session keyboards ─────────────────────────────────────────────────────────

class TestSessionsKb:
    def test_sessions_list_has_add_button(self) -> None:
        from bot.keyboards.sessions_kb import sessions_list_kb
        kb = sessions_list_kb([])
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "session:add" in datas

    def test_sessions_list_with_premium_session(self) -> None:
        from bot.keyboards.sessions_kb import sessions_list_kb
        s = MagicMock()
        s.id = uuid.uuid4()
        s.name = "Premium"
        s.has_premium = True
        s.is_active = True
        kb = sessions_list_kb([s])
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert any("💎" in t for t in texts)

    def test_session_view_has_delete(self) -> None:
        from bot.keyboards.sessions_kb import session_view_kb
        kb = session_view_kb("test-uuid")
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "session:delete:test-uuid" in datas

    def test_add_method_has_qr_and_phone(self) -> None:
        from bot.keyboards.sessions_kb import session_add_method_kb
        kb = session_add_method_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "session:add:qr" in datas
        assert "session:add:phone" in datas


# ── Post keyboards ────────────────────────────────────────────────────────────

class TestPostsKb:
    def test_post_add_type_has_forward_and_manual(self) -> None:
        from bot.keyboards.posts_kb import post_add_type_kb
        kb = post_add_type_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "post:add:forward" in datas
        assert "post:add:manual" in datas

    def test_post_manual_type_has_all_types(self) -> None:
        from bot.keyboards.posts_kb import post_manual_type_kb
        kb = post_manual_type_kb()
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "post:manual:text" in datas
        assert "post:manual:photo" in datas
        assert "post:manual:video" in datas
        assert "post:manual:document" in datas

    def test_posts_list_has_add_button(self) -> None:
        from bot.keyboards.posts_kb import posts_list_kb
        kb = posts_list_kb([])
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "post:add" in datas


# ── Campaign keyboards ────────────────────────────────────────────────────────

class TestCampaignsKb:
    def test_view_draft_has_start_button(self) -> None:
        from bot.keyboards.campaigns_kb import campaign_view_kb
        from db.models import CampaignStatus
        kb = campaign_view_kb("test-id", CampaignStatus.DRAFT)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "campaign:start:test-id" in datas

    def test_view_active_has_pause_and_stop(self) -> None:
        from bot.keyboards.campaigns_kb import campaign_view_kb
        from db.models import CampaignStatus
        kb = campaign_view_kb("test-id", CampaignStatus.ACTIVE)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "campaign:pause:test-id" in datas
        assert "campaign:stop:test-id" in datas

    def test_view_paused_has_resume(self) -> None:
        from bot.keyboards.campaigns_kb import campaign_view_kb
        from db.models import CampaignStatus
        kb = campaign_view_kb("test-id", CampaignStatus.PAUSED)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "campaign:resume:test-id" in datas

    def test_settings_has_all_options(self) -> None:
        from bot.keyboards.campaigns_kb import campaign_settings_kb
        cfg = MagicMock()
        cfg.delay_between_chats = 5
        cfg.randomize_delay = False
        cfg.randomize_min = 3
        cfg.randomize_max = 10
        cfg.delay_between_cycles = 60
        cfg.cycle_delay_randomize = False
        cfg.cycle_delay_min = 30
        cfg.cycle_delay_max = 120
        cfg.shuffle_after_cycle = False
        cfg.max_cycles = None
        cfg.forward_mode = True
        kb = campaign_settings_kb("test-id", cfg)
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        # Callbacks use short codes (see SETTING_CODES) to stay under Telegram's 64-byte limit
        assert any("cs:dc:" in (d or "") for d in datas)  # delay_between_chats
        assert any("cs:sh:" in (d or "") for d in datas)  # shuffle_after_cycle
        assert any("cs:fm:" in (d or "") for d in datas)  # forward_mode

    def test_session_select_toggle(self) -> None:
        from bot.keyboards.campaigns_kb import session_select_kb
        s = MagicMock()
        s.id = uuid.uuid4()
        s.name = "Acc"
        s.has_premium = False
        sid = str(s.id)
        kb_unselected = session_select_kb([s], set())
        kb_selected = session_select_kb([s], {sid})
        unsel_texts = [b.text for row in kb_unselected.inline_keyboard for b in row]
        sel_texts = [b.text for row in kb_selected.inline_keyboard for b in row]
        assert any("⬜" in t for t in unsel_texts)
        assert any("✅" in t for t in sel_texts)
