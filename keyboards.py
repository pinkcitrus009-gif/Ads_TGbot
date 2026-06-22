from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Бросить d20",  callback_data="roll_d20"),
            InlineKeyboardButton("⚔️ Быстрая атака", callback_data="attack_quick"),
        ],
        [
            InlineKeyboardButton("📜 Мой лист",   callback_data="my_status"),
            InlineKeyboardButton("🎒 Инвентарь",  callback_data="inventory"),
            InlineKeyboardButton("🗺️ Квесты",     callback_data="quests"),
        ],
        [
            InlineKeyboardButton("💤 Короткий отдых", callback_data="rest_short"),
            InlineKeyboardButton("🌙 Долгий отдых",   callback_data="rest_long"),
        ],
        [
            InlineKeyboardButton("💾 Сохранить",  callback_data="save_quick"),
            InlineKeyboardButton("📖 Помощь",     callback_data="help"),
        ],
    ])


def combat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Атаковать",  callback_data="combat_attack"),
            InlineKeyboardButton("🔮 Заклинание", callback_data="combat_spell"),
        ],
        [
            InlineKeyboardButton("🛡️ Уклонение",  callback_data="combat_dodge"),
            InlineKeyboardButton("💨 Рывок",       callback_data="combat_dash"),
        ],
        [
            InlineKeyboardButton("🏃 Бежать",     callback_data="combat_flee"),
            InlineKeyboardButton("📜 Мой лист",   callback_data="my_status"),
        ],
    ])


def group_combat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Атаковать",  callback_data="combat_attack"),
            InlineKeyboardButton("🔮 Заклинание", callback_data="combat_spell"),
        ],
        [
            InlineKeyboardButton("🛡️ Уклонение",  callback_data="combat_dodge"),
            InlineKeyboardButton("💨 Рывок",       callback_data="combat_dash"),
        ],
        [
            InlineKeyboardButton("🏃 Бежать",     callback_data="combat_flee"),
            InlineKeyboardButton("✅ Завершить ход", callback_data="turn_done"),
        ],
        [InlineKeyboardButton("📜 Мой лист (скрыто)", callback_data="my_status")],
    ])


def party_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Партия",        callback_data="party_list"),
            InlineKeyboardButton("📜 Мой лист",       callback_data="my_status"),
        ],
        [
            InlineKeyboardButton("🎲 Бросить инициативу", callback_data="roll_initiative"),
            InlineKeyboardButton("✅ Мой ход завершён",    callback_data="turn_done"),
        ],
    ])


def race_keyboard() -> InlineKeyboardMarkup:
    races = [
        ("👤 Человек",         "race_Человек"),
        ("🌿 Эльф",            "race_Эльф"),
        ("⛏️ Дварф",           "race_Дварф"),
        ("🌾 Полурослик",      "race_Полурослик"),
        ("🔧 Гном",            "race_Гном"),
        ("💪 Полуорк",         "race_Полуорк"),
        ("🔥 Тифлинг",         "race_Тифлинг"),
        ("🐉 Драконорождённый","race_Драконорождённый"),
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=d)] for n, d in races])


def class_keyboard() -> InlineKeyboardMarkup:
    classes = [
        ("⚔️ Воин",     "class_Воин"),
        ("🔮 Маг",      "class_Маг"),
        ("✝️ Жрец",     "class_Жрец"),
        ("🗡️ Плут",     "class_Плут"),
        ("🪓 Варвар",   "class_Варвар"),
        ("🎵 Бард",     "class_Бард"),
        ("🛡️ Паладин",  "class_Паладин"),
        ("🏹 Следопыт", "class_Следопыт"),
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=d)] for n, d in classes])


def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Бросить кубики (4d6, отбросить 1)", callback_data="stats_roll")],
        [InlineKeyboardButton("⚖️ Стандартный набор (15,14,13,12,10,8)", callback_data="stats_pb")],
    ])


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Начать приключение!", callback_data="confirm_yes"),
            InlineKeyboardButton("🔄 Создать заново",      callback_data="confirm_no"),
        ]
    ])
