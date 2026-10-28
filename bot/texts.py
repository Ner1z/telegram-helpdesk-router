from __future__ import annotations

from bot.config import TicketRoute
from bot.models import Ticket, UserProfile
from bot.security import escape_html
from bot.timeutils import format_for_admin

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def render_user_card(profile: UserProfile) -> str:
    username = f"@{escape_html(profile.username)}" if profile.username else "без username"
    name = escape_html(profile.full_name)
    return (
        f'<a href="tg://user?id={profile.user_id}">{name}</a> · '
        f"{username} · <code>{profile.user_id}</code>"
    )


def render_new_ticket(
    ticket_id: str,
    route: TicketRoute,
    profile: UserProfile,
    message_text: str,
    created_at: str,
) -> str:
    return (
        f"🎫 <b>Новый тикет</b> · <code>#TKT-{escape_html(ticket_id)}</code>\n"
        f"🏷 {escape_html(route.emoji)} {escape_html(route.title)}\n"
        f"👤 {render_user_card(profile)}\n"
        f"🕒 <code>{escape_html(format_for_admin(created_at))}</code>\n"
        f"{DIVIDER}\n"
        f"{escape_html(message_text)}"
    )


def render_follow_up(
    ticket_id: str,
    profile: UserProfile,
    message_text: str,
    created_at: str,
) -> str:
    return (
        f"➕ <b>Дополнение к тикету</b> · <code>#TKT-{escape_html(ticket_id)}</code>\n"
        f"👤 {render_user_card(profile)}\n"
        f"🕒 <code>{escape_html(format_for_admin(created_at))}</code>\n"
        f"{DIVIDER}\n"
        f"{escape_html(message_text)}"
    )


def render_reply_header(ticket_id: str) -> str:
    return (
        f"💬 <b>Ответ поддержки</b> · <code>#TKT-{escape_html(ticket_id)}</code>\n"
        f"{DIVIDER}"
    )


def render_admin_reply(ticket_id: str, message_text: str) -> str:
    return f"{render_reply_header(ticket_id)}\n{escape_html(message_text)}"


def render_ticket_created(ticket_id: str) -> str:
    return (
        f"✅ Обращение <code>#TKT-{escape_html(ticket_id)}</code> создано.\n\n"
        "Ответ придёт в этот чат. Вы можете дополнять обращение сообщениями. "
        "Для нового обращения используйте /new."
    )


def render_follow_up_accepted(ticket_id: str) -> str:
    return (
        f"✅ Сообщение добавлено к обращению <code>#TKT-{escape_html(ticket_id)}</code>."
    )


def render_closed_for_user(ticket_id: str) -> str:
    return (
        f"✅ Обращение <code>#TKT-{escape_html(ticket_id)}</code> закрыто.\n"
        "Если проблема повторится, создайте новое обращение командой /new."
    )


def render_closed_for_admin(ticket_id: str, user: UserProfile) -> str:
    return (
        f"✅ Тикет <code>#TKT-{escape_html(ticket_id)}</code> закрыт.\n"
        f"Пользователь: {render_user_card(user)}"
    )


def render_banned_for_user() -> str:
    return "⛔ Обращения от вас больше не принимаются."


def render_unbanned_for_user() -> str:
    return "✅ Доступ к обращениям восстановлен. Для нового тикета используйте /new."


def render_ban_confirmation(
    ticket_id: str,
    user: UserProfile,
    closed_tickets: int,
) -> str:
    return (
        f"⛔ Пользователь {render_user_card(user)} заблокирован.\n"
        f"Исходный тикет: <code>#TKT-{escape_html(ticket_id)}</code>. "
        f"Закрыто обращений: <b>{closed_tickets}</b>."
    )


def render_unban_confirmation(user: UserProfile) -> str:
    return f"✅ Пользователь {render_user_card(user)} разблокирован."


def render_rate_limited() -> str:
    return (
        "⏳ Слишком много сообщений за короткое время. "
        "Подождите несколько минут и попробуйте снова."
    )


def render_message_too_long(max_length: int) -> str:
    return (
        f"✂️ Сообщение слишком длинное. Максимум: <b>{max_length}</b> символов. "
        "Сократите текст и отправьте снова."
    )


def render_text_only() -> str:
    return "📝 Пока принимаются только текстовые сообщения."


def render_category_prompt(route: TicketRoute) -> str:
    return (
        f"Вы выбрали: {escape_html(route.emoji)} <b>{escape_html(route.title)}</b>.\n\n"
        "Отправьте текст обращения одним сообщением. "
        "Не отправляйте пароли, коды подтверждения и полные платёжные данные."
    )


def render_choose_category() -> str:
    return "Выберите тему обращения кнопкой ниже."


def render_category_unavailable() -> str:
    return "Эта категория больше недоступна. Выберите другую командой /new."


def render_cancelled() -> str:
    return "Отменено. Чтобы начать заново, используйте /new."


def render_active_ticket_exists(ticket_id: str) -> str:
    return (
        f"У вас уже есть открытое обращение <code>#TKT-{escape_html(ticket_id)}</code>.\n"
        "Просто отправьте сообщение, чтобы дополнить его, или используйте /new "
        "для нового обращения."
    )


def render_ticket_not_found() -> str:
    return "Тикет не найден или срок его хранения истёк."


def render_ticket_already_closed(ticket_id: str) -> str:
    return f"Тикет <code>#TKT-{escape_html(ticket_id)}</code> уже закрыт."


def render_reply_usage() -> str:
    return (
        "Ответьте на сообщение бота с тикетом либо укажите ID: "
        "<code>/close #TKT-0123456789ABCDEF</code>."
    )


def render_ban_usage() -> str:
    return "Команда /ban работает только ответом на сообщение с тикетом."


def render_unban_usage() -> str:
    return "Команда /unban работает только ответом на сообщение с тикетом."


def render_not_a_ticket_reply() -> str:
    return "Не удалось определить тикет. Ответьте на сообщение бота с номером #TKT-…."


def render_closed_reply_blocked(ticket_id: str) -> str:
    return (
        f"Тикет <code>#TKT-{escape_html(ticket_id)}</code> закрыт. "
        "Ответ не отправлен. Создайте новый тикет при необходимости."
    )


def render_delivery_confirmation(ticket_id: str, user: UserProfile) -> str:
    return (
        f"✅ Ответ доставлен по тикету <code>#TKT-{escape_html(ticket_id)}</code> "
        f"пользователю {render_user_card(user)}."
    )


def render_delivery_failed() -> str:
    return (
        "⚠️ Не удалось доставить ответ: пользователь заблокировал бота "
        "или удалил аккаунт. Тикет оставлен открытым."
    )


def render_admin_help() -> str:
    return (
        "<b>Команды агента поддержки</b>\n\n"
        "<b>Ответ пользователю</b> — ответьте в этой группе на любое сообщение "
        "с тикетом <code>#TKT-…</code>.\n"
        "<b>/close</b> — ответом на тикет или <code>/close #TKT-…</code>; "
        "помечает обращение решённым.\n"
        "<b>/ban [причина]</b> — только ответом на тикет; блокирует пользователя "
        "и закрывает его открытые обращения.\n"
        "<b>/unban</b> — ответом на тикет; снимает блокировку.\n\n"
        "Команды работают только в разрешённых админ-группах и только для "
        "пользователей из ADMIN_USER_IDS."
    )


def render_user_help() -> str:
    return (
        "<b>Помощь</b>\n\n"
        "/start — выбрать тему и создать обращение\n"
        "/new — новое обращение\n"
        "/cancel — отменить выбор темы\n"
        "/help — эта справка\n\n"
        "После создания тикета просто отправляйте сообщения — они добавятся "
        "к обращению. Ответ придёт в этот чат."
    )


def render_welcome() -> str:
    return (
        "<b>Поддержка на связи</b>\n\n"
        "Выберите тему обращения. После этого отправьте текст одним сообщением.\n\n"
        "🔒 Не отправляйте пароли, коды подтверждения, данные банковских карт "
        "и другие секреты. Для работы поддержке нужны только описание проблемы "
        "и контакт в Telegram."
    )


def render_ticket_context(ticket: Ticket) -> str:
    return (
        f"<code>#TKT-{escape_html(ticket.ticket_id)}</code> · "
        f"{escape_html(ticket.category_emoji)} {escape_html(ticket.category_title)} · "
        f"{render_user_card(ticket.user)}"
    )


def render_unknown_command() -> str:
    return "Неизвестная команда. Используйте /help."


def render_temporary_error() -> str:
    return "⚠️ Временная ошибка. Попробуйте отправить сообщение ещё раз через минуту."


def render_admin_temporary_error() -> str:
    return "⚠️ Не удалось выполнить операцию: временная ошибка хранилища. Повторите позже."


def render_close_with_reply_and_argument() -> str:
    return "Используйте либо ответ на сообщение тикета, либо /close #TKT-…, но не оба способа сразу."
