"""
D&D Master Bot v3
Новое в v3:
- Авто-трекинг сюжета: DM сам обновляет HP/XP/золото/предметы/способности/квесты через [STATE] блок
- Групповой чат: несколько игроков в одном Telegram-чате
- Система ходов по инициативе
- Приватные листы персонажа (только игрок видит свой лист)
- Каждый игрок — свой персонаж в каждой группе
"""

import asyncio
import json
import logging
import os
import random

import aiohttp
from telegram import Update, Chat
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters,
)
from telegram.constants import ChatAction

from character import (
    CLASSES, RACES, SKILL_MAP, bar, build_context, build_party_context,
    check_level_up, default_spell_slots, format_status, modifier,
    modifier_str, parse_ai_state, roll_dice, roll_stats_array, xp_for_level,
)
from database import Database
from keyboards import (
    class_keyboard, combat_keyboard, confirm_keyboard, group_combat_keyboard,
    main_keyboard, party_keyboard, race_keyboard, stats_keyboard,
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

TG_TOKEN           = os.environ.get("TG_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
MODEL              = os.environ.get("LLM_MODEL", "openrouter/owl-alpha")
MAX_HISTORY        = 30
COMPRESS_AT        = 40
KEEP_RECENT        = 20
MAX_RETRIES        = 3

if not TG_TOKEN:           raise RuntimeError("TG_TOKEN не задан")
if not OPENROUTER_API_KEY: raise RuntimeError("OPENROUTER_API_KEY не задан")

db = Database()

# ── Wizard states ─────────────────────────────────────────────────────────────
CHOOSE_RACE, CHOOSE_CLASS, CHOOSE_STATS, ENTER_NAME, CONFIRM = range(5)


# ── Helpers: chat type ────────────────────────────────────────────────────────

def is_group(update: Update) -> bool:
    return update.effective_chat.type in (Chat.GROUP, Chat.SUPERGROUP)

def get_ids(update: Update):
    """Return (group_id, user_id). For private chats group_id == user_id."""
    user_id  = update.effective_user.id
    group_id = update.effective_chat.id
    return group_id, user_id

def get_username(update: Update) -> str:
    u = update.effective_user
    return u.username or u.first_name or str(u.id)

# ── System prompt ─────────────────────────────────────────────────────────────

BASE_PROMPT = """Ты — мастер подземелий (DM) для настольной D&D 2024. Веди захватывающую историю на русском языке.

СТИЛЬ:
• Ярко и образно — атмосфера, диалоги, напряжение, юмор
• Никаких звёздочек/решёток — только текст и эмодзи
• Ответы 150–300 слов. В конце — открытый вопрос или выбор для игроков
• Учитывай характеристики персонажа — они реально влияют на события

АВТО-ОБНОВЛЕНИЕ СОСТОЯНИЯ:
Это самое важное! Если в сцене произошло что-то из списка:
- Персонаж получил урон или исцеление
- Нашёл/купил предмет
- Продал/потратил предмет  
- Получил золото или потратил его
- Получил новую способность
- Начался или завершился квест

→ Добавь в САМЫЙ КОНЕЦ ответа (после всего текста) блок:
[STATE]{{"hp_change":0,"gold":0,"exp":0,"items_add":[],"items_remove":[],"abilities_add":[],"quests_add":[],"quests_done":[]}}[/STATE]

Правила блока STATE:
• hp_change: число (отрицательное = урон, положительное = лечение, 0 = без изменений)
• gold: изменение золота (+50, -10, 0)
• exp: XP за событие/победу (0 если ничего не было)
• items_add: список новых предметов ["Зелье лечения", "Ключ от тюрьмы"]
• items_remove: список потраченных/проданных предметов ["Зелье лечения"]
• abilities_add: новые способности или заклинания ["Огненный шар"]
• quests_add: названия новых квестов ["Найти дракона"]
• quests_done: ID выполненных квестов [3, 7]
Если ничего не изменилось — не добавляй блок STATE вообще.

{context}"""


def make_system_prompt(player_or_party, quests, is_group_game: bool = False) -> str:
    if is_group_game and isinstance(player_or_party, list):
        ctx = build_party_context(player_or_party, quests)
    else:
        ctx = build_context(player_or_party, quests)
    return BASE_PROMPT.format(context=ctx)


# ── AI ────────────────────────────────────────────────────────────────────────

async def ask_ai(messages: list, max_tokens: int = 900) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": MODEL, "messages": messages,
        "max_tokens": max_tokens, "temperature": 0.85,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_URL, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(5 * attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("AI error (attempt %d): %s", attempt, e)
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(3 * attempt)
    raise RuntimeError("AI недоступен")


async def compress_history(group_id: int):
    count = db.count_history(group_id)
    if count <= COMPRESS_AT:
        return
    old = db.get_oldest_history(group_id, count - KEEP_RECENT)
    if len(old) < 8:
        return
    msgs = [
        {"role": "system",
         "content": "Ты — летописец. Кратко (4–6 предложений) перескажи события на русском. Только факты."},
        *[{"role": m["role"], "content": m["content"]} for m in old],
        {"role": "user", "content": "Кратко изложи события этого сеанса."},
    ]
    try:
        summary = await ask_ai(msgs, max_tokens=350)
        ids = [m["id"] for m in old]
        db.delete_history_ids(group_id, ids)
        db.add_message(group_id, "system",
                       f"📜 [Краткое изложение]\n{summary}", is_summary=True)
        logger.info("History compressed for group %d (%d msgs)", group_id, len(ids))
    except Exception as e:
        logger.warning("Compression failed: %s", e)


# ── Auto state update ─────────────────────────────────────────────────────────

async def apply_state_update(group_id: int, user_id: int, state: dict) -> str:
    """Apply AI-detected changes, return summary string."""
    player = db.get_player(group_id, user_id)
    if not player:
        return ""
    updates  = {}
    changes  = []

    # HP change
    hp_delta = state.get("hp_change", 0)
    if hp_delta != 0:
        new_hp = max(0, min(player["hp"] + hp_delta, player["max_hp"]))
        updates["hp"] = new_hp
        icon = "💚" if hp_delta > 0 else "🩸"
        changes.append(f"{icon} {'+'if hp_delta>0 else ''}{hp_delta} HP → {new_hp}/{player['max_hp']}")

    # Gold
    gold_delta = state.get("gold", 0)
    if gold_delta != 0:
        new_gold = max(0, player["gold"] + gold_delta)
        updates["gold"] = new_gold
        sign = "+" if gold_delta > 0 else ""
        changes.append(f"💰 {sign}{gold_delta} зм → {new_gold} зм")

    # XP
    exp_gain = state.get("exp", 0)
    if exp_gain > 0:
        new_exp = player["exp"] + exp_gain
        leveled, new_level = check_level_up({**player, "exp": new_exp})
        exp_next = xp_for_level(new_level + 1) if new_level < 20 else player["exp_next"]
        updates["exp"]      = new_exp
        updates["exp_next"] = exp_next
        changes.append(f"⭐ +{exp_gain} XP → {new_exp}/{exp_next}")
        if leveled:
            hit_die = player.get("hit_die", 8)
            con_mod = modifier(player["constitution"])
            hp_gain = max(1, random.randint(1, hit_die) + con_mod)
            updates["level"]   = new_level
            updates["max_hp"]  = player["max_hp"] + hp_gain
            updates["hp"]      = updates.get("hp", player["hp"]) + hp_gain
            updates["spell_slots"] = default_spell_slots(player.get("class",""), new_level)
            changes.append(f"🎉 НОВЫЙ УРОВЕНЬ {new_level}! +{hp_gain} HP макс.")

    # Items gained
    inv = player["inventory"].copy()
    for item in state.get("items_add", []):
        if item and item not in inv:
            inv.append(item)
            changes.append(f"🎁 Получено: {item}")
    # Items removed
    for item in state.get("items_remove", []):
        for x in list(inv):
            if item.lower() in x.lower():
                inv.remove(x)
                changes.append(f"📤 Потрачено: {x}")
                break
    if inv != player["inventory"]:
        updates["inventory"] = inv

    # Abilities
    abilities = player["abilities"].copy()
    for ab in state.get("abilities_add", []):
        if ab and ab not in abilities:
            abilities.append(ab)
            changes.append(f"✨ Новая способность: {ab}")
    if abilities != player["abilities"]:
        updates["abilities"] = abilities

    # Quests
    for q_title in state.get("quests_add", []):
        if q_title:
            q = db.add_quest(group_id, q_title)
            changes.append(f"📋 Квест: {q_title} [#{q['id']}]")
    for qid in state.get("quests_done", []):
        if db.complete_quest(group_id, qid):
            changes.append(f"✅ Квест #{qid} выполнен")

    if updates:
        db.update_player(group_id, user_id, **updates)

    return "\n".join(changes) if changes else ""


def split_msg(text: str, max_len: int = 4000) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        idx = text.rfind("\n\n", 0, max_len)
        if idx == -1:
            idx = text.rfind(". ", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx].strip())
        text = text[idx:].strip()
    return [c for c in chunks if c]


# ── Core DM reply ─────────────────────────────────────────────────────────────

async def dm_reply(update: Update, group_id: int, user_id: int, extra_text: str = ""):
    """Get DM reply, auto-apply state updates, send response."""
    await compress_history(group_id)
    player  = db.get_player(group_id, user_id)
    quests  = db.get_quests(group_id)
    party   = db.get_party(group_id)
    in_group = is_group(update)

    if in_group and len(party) > 1:
        players = db.get_all_players_in_group(group_id)
        system  = make_system_prompt(players, quests, is_group_game=True)
    else:
        system = make_system_prompt(player, quests)

    history  = db.get_history(group_id, MAX_HISTORY)
    messages = [{"role": "system", "content": system}] + history

    try:
        raw_reply = await ask_ai(messages)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Ошибка AI: {e}")
        return

    # Parse and apply state updates
    clean_reply, state = parse_ai_state(raw_reply)
    state_summary = ""
    if state:
        state_summary = await apply_state_update(group_id, user_id, state)

    db.add_message(group_id, "assistant", clean_reply)

    # Build output
    full_text = clean_reply
    if state_summary:
        full_text = full_text + f"\n\n━━━━━━━━━━\n{state_summary}"

    # Turn system annotation for group games
    ts = db.get_turn_state(group_id)
    turn_note = ""
    if ts and ts.get("turn_order") and in_group:
        order    = ts["turn_order"]
        cur_uid  = order[ts["current_idx"] % len(order)] if order else None
        if cur_uid:
            pmembers = {m["user_id"]: m["username"] for m in party}
            cur_name = pmembers.get(cur_uid, str(cur_uid))
            turn_note = (
                f"\n\n⚔️ Раунд {ts['round_number']} — ход: "
                f"@{cur_name} | /done чтобы передать ход"
            )

    full_text += turn_note

    in_combat  = bool(player and player.get("combat_state"))
    kb = (group_combat_keyboard() if (in_group and in_combat)
          else (combat_keyboard() if in_combat else main_keyboard()))

    for chunk in split_msg(full_text):
        await update.effective_message.reply_text(chunk, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
# CHARACTER CREATION WIZARD
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id, user_id = get_ids(update)
    username = get_username(update)
    db.clear_history(group_id)
    db.reset_player(group_id, user_id, username)
    context.user_data.clear()

    await update.message.reply_text(
        "🐉 Добро пожаловать, искатель приключений!\n\nВыбери расу:",
        reply_markup=race_keyboard(),
    )
    return CHOOSE_RACE


async def handle_race(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    race = query.data.replace("race_", "")
    context.user_data["race"] = race
    info = RACES.get(race, {})
    await query.edit_message_text(
        f"✅ Раса: {race}\n{info.get('desc','')}\n\nТеперь выбери класс:",
        reply_markup=class_keyboard(),
    )
    return CHOOSE_CLASS


async def handle_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cls  = query.data.replace("class_", "")
    context.user_data["class"] = cls
    info = CLASSES.get(cls, {})
    await query.edit_message_text(
        f"✅ Класс: {cls}\n{info.get('desc','')}\n\nКак распределить характеристики?",
        reply_markup=stats_keyboard(),
    )
    return CHOOSE_STATS


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    race = context.user_data.get("race", "Человек")

    if query.data == "stats_roll":
        arr   = sorted(roll_stats_array(), reverse=True)
        stats = {"strength":arr[0],"dexterity":arr[1],"constitution":arr[2],
                 "intelligence":arr[3],"wisdom":arr[4],"charisma":arr[5]}
        method = f"🎲 Броски: {arr}"
    else:
        stats  = {"strength":15,"dexterity":14,"constitution":13,
                  "intelligence":12,"wisdom":10,"charisma":8}
        method = "⚖️ Стандартный набор: 15,14,13,12,10,8"

    bonuses = RACES.get(race, {})
    for key, val in bonuses.items():
        if key in stats:
            stats[key] = min(stats[key] + val, 20)

    context.user_data["stats"] = stats
    s = stats
    await query.edit_message_text(
        f"{method}\n(с расовыми бонусами {race})\n\n"
        f"💪 Сила: {s['strength']}  🏃 Ловкость: {s['dexterity']}  🧱 Телосложение: {s['constitution']}\n"
        f"🧠 Интеллект: {s['intelligence']}  🔭 Мудрость: {s['wisdom']}  ✨ Харизма: {s['charisma']}\n\n"
        "Введи имя своего героя:"
    )
    return ENTER_NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()[:32]
    context.user_data["name"] = name
    race = context.user_data.get("race", "Человек")
    cls  = context.user_data.get("class", "Воин")
    s    = context.user_data.get("stats", {})
    cd   = CLASSES.get(cls, {})
    con_mod = (s.get("constitution", 10) - 10) // 2
    max_hp  = cd.get("hp", 10) + con_mod

    preview = (
        f"⚔️ {name} ({race} • {cls} • 1 ур.)\n"
        f"❤️ HP: {max_hp}/{max_hp}   🛡️ КД: {cd.get('ac',10)}\n"
        f"💪{s.get('strength',10)} 🏃{s.get('dexterity',10)} 🧱{s.get('constitution',10)} "
        f"🧠{s.get('intelligence',10)} 🔭{s.get('wisdom',10)} ✨{s.get('charisma',10)}\n\n"
        "Начать приключение?"
    )
    await update.message.reply_text(preview, reply_markup=confirm_keyboard())
    return CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query    = update.callback_query
    await query.answer()
    group_id = query.message.chat_id
    user_id  = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or str(user_id)

    if query.data == "confirm_no":
        await query.edit_message_text("🔄 Хорошо, начнём заново!")
        await query.message.reply_text("Выбери расу:", reply_markup=race_keyboard())
        return CHOOSE_RACE

    name = context.user_data.get("name", "Герой")
    race = context.user_data.get("race", "Человек")
    cls  = context.user_data.get("class", "Воин")
    s    = context.user_data.get("stats", {})
    cd   = CLASSES.get(cls, {})
    con_mod = (s.get("constitution", 10) - 10) // 2
    max_hp  = max(1, cd.get("hp", 10) + con_mod)
    slots   = default_spell_slots(cls, 1)

    db.update_player(
        group_id, user_id,
        username=username, name=name, race=race, **{"class": cls},
        level=1, hp=max_hp, max_hp=max_hp,
        armor_class=cd.get("ac", 10), hit_die=cd.get("hit_die", 8),
        exp=0, exp_next=300, gold=0, spell_slots=slots, **s,
    )

    # Auto-join party in group chats
    if query.message.chat.type in (Chat.GROUP, Chat.SUPERGROUP):
        db.join_party(group_id, user_id, username)

    await query.edit_message_text(f"✅ {name} создан!")
    db.add_message(group_id, "user",
                   f"Привет! Меня зовут {name}, я {race}-{cls}. Начинаем приключение!",
                   user_id=user_id)
    await dm_reply(update, group_id, user_id,
                   extra_text=f"Путь начинается, {name}! Удачи!")
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Создание персонажа отменено. /start — заново.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# GROUP COMMANDS
# ═══════════════════════════════════════════════════════════

async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Join the group game. Create character first if needed."""
    group_id, user_id = get_ids(update)
    username = get_username(update)
    player   = db.get_player(group_id, user_id)

    if not player:
        await update.message.reply_text(
            "⚠️ Сначала создай персонажа! Напиши /start"
        )
        return

    if db.is_in_party(group_id, user_id):
        await update.message.reply_text(
            f"✅ {player['name']} уже в партии!"
        )
        return

    db.join_party(group_id, user_id, username)
    await update.message.reply_text(
        f"⚔️ {player['name']} ({player['race']} {player['class']}) вступает в партию!\n"
        f"Используй /party чтобы увидеть всех.",
        reply_markup=party_keyboard(),
    )


async def cmd_party(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all party members."""
    group_id = update.effective_chat.id
    members  = db.get_party(group_id)

    if not members:
        await update.message.reply_text(
            "👥 Партия пуста.\n"
            "Каждый игрок: /start → создай персонажа → /join"
        )
        return

    lines = ["👥 Состав партии:\n"]
    for m in members:
        p = db.get_player(group_id, m["user_id"])
        if p:
            hp, mhp = p["hp"], p["max_hp"]
            hp_bar  = bar(hp, mhp, 8)
            lines.append(
                f"• {p['name']} (@{m['username']})\n"
                f"  {p['race']} {p['class']} ур.{p['level']}  "
                f"❤️{hp}/{mhp} {hp_bar}"
            )
        else:
            lines.append(f"• @{m['username']} — нет персонажа")

    ts = db.get_turn_state(group_id)
    if ts and ts["turn_order"]:
        order = ts["turn_order"]
        cur   = order[ts["current_idx"] % len(order)]
        name_map = {m["user_id"]: m["username"] for m in members}
        lines.append(f"\n⚔️ Раунд {ts['round_number']}. Ход: @{name_map.get(cur,'?')}")

    await update.message.reply_text("\n".join(lines), reply_markup=party_keyboard())


async def cmd_roll_initiative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Roll initiative for all party members and set turn order."""
    group_id = update.effective_chat.id
    members  = db.get_party(group_id)

    if not members:
        await update.message.reply_text("👥 В партии никого нет. /join чтобы вступить.")
        return

    db.reset_initiatives(group_id)
    rolls    = []
    order    = []

    for m in members:
        p   = db.get_player(group_id, m["user_id"])
        dex = p["dexterity"] if p else 10
        dex_mod = modifier(dex)
        roll    = random.randint(1, 20)
        total   = roll + dex_mod
        db.set_initiative(group_id, m["user_id"], total)
        rolls.append((total, random.random(), m["user_id"], m["username"], roll, dex_mod))

    rolls.sort(reverse=True)

    lines = ["🎲 Инициатива:\n"]
    for i, (total, _, uid, uname, roll, dex_mod) in enumerate(rolls, 1):
        order.append(uid)
        sign = "+" if dex_mod >= 0 else ""
        lines.append(f"{i}. @{uname}: {roll} {sign}{dex_mod} = **{total}**")

    # Handle ties (already broken by random.random())
    db.set_turn_state(group_id, order, current_idx=0, round_number=1, mode="combat")

    first_uid  = order[0]
    first_name = rolls[0][3]
    lines.append(f"\n⚔️ Первым ходит: @{first_name}!")

    await update.message.reply_text("\n".join(lines), reply_markup=party_keyboard())


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End your turn and pass to the next player."""
    group_id, user_id = get_ids(update)
    ts = db.get_turn_state(group_id)

    if not ts or not ts["turn_order"]:
        await update.message.reply_text(
            "⚠️ Нет активного боя. /roll_initiative чтобы начать."
        )
        return

    order   = ts["turn_order"]
    cur_uid = order[ts["current_idx"] % len(order)]

    if cur_uid != user_id:
        members  = db.get_party(group_id)
        name_map = {m["user_id"]: m["username"] for m in members}
        await update.message.reply_text(
            f"⚠️ Сейчас ход @{name_map.get(cur_uid,'?')}!"
        )
        return

    new_ts   = db.advance_turn(group_id)
    new_order = new_ts["turn_order"]
    new_uid   = new_order[new_ts["current_idx"] % len(new_order)]
    members   = db.get_party(group_id)
    name_map  = {m["user_id"]: m["username"] for m in members}
    new_name  = name_map.get(new_uid, str(new_uid))

    await update.message.reply_text(
        f"✅ Ход передан!\n"
        f"⚔️ Раунд {new_ts['round_number']} — ход: @{new_name}!",
        reply_markup=party_keyboard(),
    )


async def cmd_end_combat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End combat and turn system."""
    group_id = update.effective_chat.id
    db.clear_turn_state(group_id)
    # Clear combat state for all players
    for m in db.get_party(group_id):
        db.update_player(group_id, m["user_id"], combat_state=None)
    await update.message.reply_text(
        "🕊️ Бой завершён. Порядок ходов сброшен.\n"
        "Продолжайте повествование!",
        reply_markup=main_keyboard(),
    )


# ═══════════════════════════════════════════════════════════
# INLINE BUTTON CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    data     = query.data
    group_id = query.message.chat_id
    user_id  = query.from_user.id
    player   = db.get_player(group_id, user_id)

    # my_status always private (answered only to clicking user)
    if data == "my_status":
        if not player:
            await query.answer("⚠️ Нет персонажа. /start", show_alert=True)
            return
        sheet = format_status(player)
        # Send as private message in group, popup in private
        if is_group(update):
            try:
                await context.bot.send_message(user_id, sheet)
                await query.answer("📜 Лист отправлен в личку!", show_alert=False)
            except Exception:
                # If user hasn't started bot in private, show alert
                await query.answer(
                    format_status(player, short=True)[:200],
                    show_alert=True
                )
        else:
            await query.answer()
            await query.message.reply_text(sheet, reply_markup=main_keyboard())
        return

    await query.answer()
    if not player:
        await query.message.reply_text("⚠️ Нет персонажа. /start")
        return

    if data == "inventory":
        inv  = player.get("inventory", [])
        text = "🎒 Инвентарь:\n" + ("\n".join(f"• {i}" for i in inv) if inv else "пусто")
        await query.message.reply_text(text, reply_markup=main_keyboard())

    elif data == "quests":
        active = db.get_quests(group_id, "active")
        done   = db.get_quests(group_id, "completed")
        msg = "🗺️ Квесты:\n"
        if active: msg += "\n🔸 " + "\n  ".join(f"[{q['id']}] {q['title']}" for q in active)
        if done:   msg += "\n\n✅ " + "\n  ".join(f"[{q['id']}] {q['title']}" for q in done)
        if not active and not done: msg += "Нет квестов."
        await query.message.reply_text(msg, reply_markup=main_keyboard())

    elif data == "roll_d20":
        roll = random.randint(1, 20)
        note = " ✨ Критический успех!" if roll == 20 else (" 💀 Критическая неудача!" if roll == 1 else "")
        await query.message.reply_text(
            f"🎲 d20 ({player['name']}): **{roll}**{note}",
            reply_markup=main_keyboard(),
        )

    elif data == "attack_quick":
        str_mod = modifier(player["strength"])
        dex_mod = modifier(player["dexterity"])
        atk_mod = max(str_mod, dex_mod)
        atk     = random.randint(1, 20)
        total   = atk + atk_mod
        dmg     = random.randint(1, 8) + max(str_mod, 0)
        mod_s   = modifier_str(max(player["strength"], player["dexterity"]))
        msg = f"⚔️ {player['name']} атакует!\n🎲 {atk} {mod_s} = **{total}**\n"
        if atk == 20:
            dmg *= 2
            msg += f"✨ Крит! Урон: **{dmg}**"
        elif atk == 1:
            msg += "💀 Промах!"
        else:
            msg += f"🗡️ Урон: **{dmg}**"
        await query.message.reply_text(msg, reply_markup=main_keyboard())

    elif data == "rest_short":
        hit_die = player.get("hit_die", 8)
        con_mod = modifier(player["constitution"])
        healed  = max(1, random.randint(1, hit_die) + con_mod)
        new_hp  = min(player["hp"] + healed, player["max_hp"])
        db.update_player(group_id, user_id, hp=new_hp)
        await query.message.reply_text(
            f"💤 Короткий отдых ({player['name']})\n"
            f"💚 +{healed} HP\n❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}",
            reply_markup=main_keyboard(),
        )

    elif data == "rest_long":
        slots = default_spell_slots(player.get("class",""), player.get("level",1))
        db.update_player(group_id, user_id, hp=player["max_hp"], spell_slots=slots)
        msg = (
            f"🌙 Долгий отдых ({player['name']})\n"
            f"❤️ HP восстановлено: {player['max_hp']}/{player['max_hp']}\n"
        )
        if slots: msg += "🪄 Все слоты заклинаний восстановлены"
        await query.message.reply_text(msg, reply_markup=main_keyboard())

    elif data == "save_quick":
        ts = query.message.date.strftime('%d%m_%H%M')
        db.save_game(group_id, user_id, f"auto_{ts}")
        await query.message.reply_text(
            f"💾 Сохранено: auto_{ts}", reply_markup=main_keyboard()
        )

    elif data == "help":
        await send_help(query.message)

    elif data == "party_list":
        # Reuse party command
        members = db.get_party(group_id)
        if not members:
            await query.message.reply_text("👥 Партия пуста.")
            return
        lines = ["👥 Состав партии:\n"]
        for m in members:
            p = db.get_player(group_id, m["user_id"])
            if p:
                hp, mhp = p["hp"], p["max_hp"]
                lines.append(f"• {p['name']} ❤️{hp}/{mhp} {bar(hp,mhp,6)}")
        await query.message.reply_text("\n".join(lines), reply_markup=party_keyboard())

    elif data == "roll_initiative":
        # Inline button rolls initiative
        members = db.get_party(group_id)
        if members:
            context._user_id = user_id
            await _do_roll_initiative(query.message, group_id)
        else:
            await query.message.reply_text("👥 Нет партии. /join чтобы вступить.")

    elif data == "turn_done":
        ts = db.get_turn_state(group_id)
        if ts and ts["turn_order"]:
            order   = ts["turn_order"]
            cur_uid = order[ts["current_idx"] % len(order)]
            if cur_uid == user_id:
                new_ts   = db.advance_turn(group_id)
                new_order = new_ts["turn_order"]
                new_uid   = new_order[new_ts["current_idx"] % len(new_order)]
                members   = db.get_party(group_id)
                name_map  = {m["user_id"]: m["username"] for m in members}
                await query.message.reply_text(
                    f"✅ Ход передан! Раунд {new_ts['round_number']} — ход: @{name_map.get(new_uid,'?')}!",
                    reply_markup=party_keyboard(),
                )
            else:
                await query.message.reply_text("⚠️ Сейчас не твой ход!")

    elif data.startswith("combat_"):
        await handle_combat_inline(query, data, player, group_id, user_id)


async def _do_roll_initiative(message, group_id: int):
    members = db.get_party(group_id)
    db.reset_initiatives(group_id)
    rolls = []
    for m in members:
        p   = db.get_player(group_id, m["user_id"])
        dex = p["dexterity"] if p else 10
        dex_mod = modifier(dex)
        roll    = random.randint(1, 20)
        total   = roll + dex_mod
        db.set_initiative(group_id, m["user_id"], total)
        rolls.append((total, random.random(), m["user_id"], m["username"], roll, dex_mod))
    rolls.sort(reverse=True)
    order = [r[2] for r in rolls]
    db.set_turn_state(group_id, order, 0, 1, "combat")
    lines = ["🎲 Инициатива:\n"]
    for i, (total, _, uid, uname, roll, dex_mod) in enumerate(rolls, 1):
        sign = "+" if dex_mod >= 0 else ""
        lines.append(f"{i}. @{uname}: {roll} {sign}{dex_mod} = **{total}**")
    lines.append(f"\n⚔️ Первым ходит: @{rolls[0][3]}!")
    await message.reply_text("\n".join(lines), reply_markup=party_keyboard())


async def handle_combat_inline(query, data: str, player: dict, group_id: int, user_id: int):
    combat = player.get("combat_state")
    if not combat:
        await query.message.reply_text(
            "⚠️ Нет активного боя. Напиши /fight <противник>",
            reply_markup=main_keyboard(),
        )
        return

    in_group_chat = query.message.chat.type in (Chat.GROUP, Chat.SUPERGROUP)
    kb = group_combat_keyboard() if in_group_chat else combat_keyboard()

    if data == "combat_flee":
        dex_roll = random.randint(1, 20) + modifier(player["dexterity"])
        if dex_roll >= 12:
            db.update_player(group_id, user_id, combat_state=None)
            db.add_message(group_id, "user",
                           f"{player['name']} убегает от {combat['enemy']}!", user_id=user_id)
            await dm_reply(query, group_id, user_id,
                           extra_text=f"🏃 Побег: {dex_roll} — удалось!")
        else:
            hit    = random.randint(4, 12)
            new_hp = max(0, player["hp"] - hit)
            db.update_player(group_id, user_id, hp=new_hp)
            await query.message.reply_text(
                f"🏃 Попытка побега: {dex_roll} — не удалось!\n"
                f"🩸 {combat['enemy']} атакует: -{hit} HP\n"
                f"❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}",
                reply_markup=kb,
            )
        return

    if data == "combat_dodge":
        await query.message.reply_text(
            "🛡️ Защитная стойка! Следующая атака противника с помехой.",
            reply_markup=kb,
        )
        return

    if data == "combat_dash":
        db.add_message(group_id, "user",
                       f"{player['name']} делает рывок!", user_id=user_id)
        await dm_reply(query, group_id, user_id, extra_text="💨 Рывок!")
        return

    if data == "combat_spell":
        slots = player.get("spell_slots", {})
        if not slots:
            await query.message.reply_text("🔮 Нет слотов заклинаний!", reply_markup=kb)
            return
        avail = [lvl for lvl, v in slots.items()
                 if (v[0] if isinstance(v, list) else v) > 0]
        if not avail:
            await query.message.reply_text(
                "🔮 Все слоты исчерпаны! /rest long", reply_markup=kb
            )
            return
        await query.message.reply_text(
            f"🔮 Используй /spell <уровень> <название>",
            reply_markup=kb,
        )
        return

    # combat_attack
    str_mod  = modifier(player["strength"])
    dex_mod  = modifier(player["dexterity"])
    atk_mod  = max(str_mod, dex_mod)
    atk      = random.randint(1, 20)
    total    = atk + atk_mod
    enemy_ac = combat.get("enemy_ac", 13)
    mod_s    = modifier_str(max(player["strength"], player["dexterity"]))

    msg = f"⚔️ {player['name']} атакует {combat['enemy']}\n🎲 {atk} {mod_s} = **{total}** (КД {enemy_ac})\n"

    if atk == 1:
        msg += "💀 Критический промах!"
    elif atk == 20 or total >= enemy_ac:
        dmg = random.randint(1, 8) + max(str_mod, 0)
        if atk == 20:
            dmg *= 2
            msg += "✨ КРИТ! "
        enemy_hp = max(0, combat["enemy_hp"] - dmg)
        combat["enemy_hp"] = enemy_hp
        msg += (
            f"🗡️ Урон: **{dmg}**\n"
            f"{combat['enemy']}: ❤️ {enemy_hp}/{combat['enemy_max_hp']}  "
            f"{bar(enemy_hp, combat['enemy_max_hp'])}"
        )
        if enemy_hp <= 0:
            xp = combat.get("xp_reward", 50)
            db.update_player(group_id, user_id, combat_state=None)
            db.add_message(group_id, "user",
                           f"{player['name']} победил {combat['enemy']}!", user_id=user_id)
            await dm_reply(query, group_id, user_id,
                           extra_text=msg + f"\n\n🏆 Победа! DM добавит XP.")
            return
        db.update_player(group_id, user_id, combat_state=combat)
        enemy_hit = random.randint(3, 10)
        new_hp    = max(0, player["hp"] - enemy_hit)
        db.update_player(group_id, user_id, hp=new_hp)
        msg += (
            f"\n\n↩️ {combat['enemy']} контратакует: -{enemy_hit} HP\n"
            f"❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}"
        )
    else:
        msg += f"❌ Промах ({total} < {enemy_ac})\n"
        enemy_hit = random.randint(3, 10)
        new_hp    = max(0, player["hp"] - enemy_hit)
        db.update_player(group_id, user_id, hp=new_hp)
        msg += (
            f"↩️ {combat['enemy']} атакует: -{enemy_hit} HP\n"
            f"❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}"
        )

    await query.message.reply_text(msg, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
# GAME COMMANDS
# ═══════════════════════════════════════════════════════════

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show your character sheet. In group — sends to private."""
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player:
        await update.message.reply_text("⚠️ Нет персонажа. /start")
        return
    sheet = format_status(player)
    if is_group(update):
        try:
            await context.bot.send_message(user_id, sheet)
            await update.message.reply_text(
                f"📜 {player['name']}, лист отправлен тебе в личку!",
                reply_markup=main_keyboard(),
            )
        except Exception:
            await update.message.reply_text(
                "⚠️ Напиши боту в личку /start, чтобы получать приватные листы.\n"
                f"(Краткий лист: {player['name']} ур.{player['level']} "
                f"❤️{player['hp']}/{player['max_hp']})"
            )
    else:
        await update.message.reply_text(sheet, reply_markup=main_keyboard())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_info(update, context)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    username = get_username(update)
    db.clear_history(group_id)
    db.reset_player(group_id, user_id, username)
    await update.message.reply_text("🗑 Сброшено. /start чтобы создать персонажа.")


async def cmd_heal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args or not context.args[0].lstrip('-').isdigit():
        await update.message.reply_text("Использование: /heal <N>"); return
    n = int(context.args[0])
    new_hp = min(player["hp"] + n, player["max_hp"])
    db.update_player(group_id, user_id, hp=new_hp)
    await update.message.reply_text(
        f"💚 {player['name']}: +{n} HP\n❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}",
        reply_markup=main_keyboard(),
    )


async def cmd_damage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /damage <N>"); return
    n = int(context.args[0])
    new_hp = max(0, player["hp"] - n)
    db.update_player(group_id, user_id, hp=new_hp)
    msg = f"🩸 {player['name']}: -{n} HP\n❤️ {new_hp}/{player['max_hp']}  {bar(new_hp, player['max_hp'])}"
    if new_hp == 0:
        msg += "\n\n💀 Герой при смерти!"
    await update.message.reply_text(msg, reply_markup=main_keyboard())


async def cmd_take(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args: await update.message.reply_text("Использование: /take <предмет>"); return
    item = " ".join(context.args)
    inv  = player["inventory"] + [item]
    db.update_player(group_id, user_id, inventory=inv)
    await update.message.reply_text(f"🎒 {player['name']} взял: {item}", reply_markup=main_keyboard())


async def cmd_drop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args: await update.message.reply_text("Использование: /drop <предмет>"); return
    item = " ".join(context.args).lower()
    inv  = player["inventory"]
    found = next((x for x in inv if item in x.lower()), None)
    if not found:
        await update.message.reply_text(f"❌ Нет в инвентаре: {item}"); return
    inv.remove(found)
    db.update_player(group_id, user_id, inventory=inv)
    await update.message.reply_text(f"🗑 {player['name']} выбросил: {found}", reply_markup=main_keyboard())


async def cmd_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args:
        await update.message.reply_text(f"💰 {player['name']}: {player['gold']} зм\nИспользование: /gold +50"); return
    try:
        delta    = int(context.args[0])
        new_gold = max(0, player["gold"] + delta)
        db.update_player(group_id, user_id, gold=new_gold)
        sign = "+" if delta >= 0 else ""
        await update.message.reply_text(f"💰 {player['name']}: {sign}{delta} зм → {new_gold} зм", reply_markup=main_keyboard())
    except ValueError:
        await update.message.reply_text("Использование: /gold +50 или /gold -10")


async def cmd_add_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /add_exp <N>"); return
    n       = int(context.args[0])
    new_exp = player["exp"] + n
    leveled, new_level = check_level_up({**player, "exp": new_exp})
    exp_next = xp_for_level(new_level + 1) if new_level < 20 else player["exp_next"]
    updates  = {"exp": new_exp, "exp_next": exp_next}
    if leveled:
        hit_die = player.get("hit_die", 8)
        con_mod = modifier(player["constitution"])
        hp_gain = max(1, random.randint(1, hit_die) + con_mod)
        updates.update(level=new_level, max_hp=player["max_hp"]+hp_gain,
                       hp=player["hp"]+hp_gain,
                       spell_slots=default_spell_slots(player.get("class",""), new_level))
    db.update_player(group_id, user_id, **updates)
    msg = f"⭐ {player['name']}: +{n} XP → {new_exp}/{exp_next}\n{bar(new_exp, exp_next)}"
    if leveled:
        msg += f"\n\n🎉 УРОВЕНЬ {new_level}! +{updates.get('max_hp',0)-player['max_hp']} HP!"
    await update.message.reply_text(msg, reply_markup=main_keyboard())


async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player  = db.get_player(group_id, user_id)
    name    = player['name'] if player else get_username(update)
    expr    = context.args[0] if context.args else "1d20"
    try:
        desc, _ = roll_dice(expr)
        await update.message.reply_text(f"{name}: {desc}", reply_markup=main_keyboard())
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}\nПример: /roll 2d6+3")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if not context.args:
        await update.message.reply_text(f"Использование: /check <навык>\nНавыки: {', '.join(SKILL_MAP)}"); return
    skill   = " ".join(context.args).lower()
    ability = SKILL_MAP.get(skill)
    if not ability:
        await update.message.reply_text(f"❓ Навык не найден: {skill}"); return
    stat  = player[ability]
    mod   = modifier(stat)
    roll  = random.randint(1, 20)
    total = roll + mod
    note  = " ✨ Крит!" if roll == 20 else (" 💀 Провал!" if roll == 1 else "")
    await update.message.reply_text(
        f"🎲 {player['name']} — {skill.capitalize()} ({ability} {modifier_str(stat)})\n"
        f"{roll} {modifier_str(stat)} = **{total}**{note}",
        reply_markup=main_keyboard(),
    )


async def cmd_fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    enemy  = " ".join(context.args) if context.args else "Гоблин"
    hp     = random.randint(10, 35)
    ac     = random.randint(10, 16)
    xp_rew = random.randint(25, 100)
    combat = {"enemy":enemy,"enemy_hp":hp,"enemy_max_hp":hp,"enemy_ac":ac,"xp_reward":xp_rew}
    db.update_player(group_id, user_id, combat_state=combat)
    db.add_message(group_id, "user",
                   f"{player['name']} вступает в бой с {enemy}!", user_id=user_id)

    init_p = random.randint(1, 20) + modifier(player["dexterity"])
    init_e = random.randint(1, 20)
    first  = "Ты действуешь первым!" if init_p >= init_e else f"{enemy} действует первым!"

    # In group: also roll initiative for all
    in_group_game = is_group(update) and len(db.get_party(group_id)) > 1
    if in_group_game:
        await _do_roll_initiative(update.message, group_id)

    player = db.get_player(group_id, user_id)
    await dm_reply(
        update, group_id, user_id,
        extra_text=(
            f"⚔️ БОЙ НАЧИНАЕТСЯ: {enemy}\n"
            f"❤️ HP врага: {hp}/{hp}  {bar(hp,hp)}\n"
            f"🛡️ КД: {ac}\n"
            f"🎲 Инициатива: {player['name']} {init_p} vs {enemy} {init_e} — {first}"
        ),
    )


async def cmd_spell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    player = db.get_player(group_id, user_id)
    if not player: await update.message.reply_text("⚠️ Нет персонажа."); return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /spell <уровень> <название>"); return
    try:
        lvl = str(int(context.args[0]))
    except ValueError:
        await update.message.reply_text("Укажи уровень: /spell 1 Магическая стрела"); return
    spell_name = " ".join(context.args[1:])
    slots = player.get("spell_slots", {})
    if not slots or lvl not in slots:
        await update.message.reply_text(f"🔮 Нет слотов {lvl}-го уровня."); return
    v   = slots[lvl]
    cur = v[0] if isinstance(v, list) else v
    if cur <= 0:
        await update.message.reply_text(f"🔮 Слоты {lvl}-го уровня исчерпаны! /rest long"); return
    slots[lvl] = [cur - 1, v[1] if isinstance(v, list) else v]
    db.update_player(group_id, user_id, spell_slots=slots)
    db.add_message(group_id, "user",
                   f"{player['name']} применяет {spell_name} ({lvl}-й ур.)!", user_id=user_id)
    player = db.get_player(group_id, user_id)
    await dm_reply(update, group_id, user_id,
                   extra_text=f"🔮 {player['name']} → {spell_name} (слот {lvl} ур., осталось: {slots[lvl][0]})")


async def cmd_quest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    if not context.args:
        await update.message.reply_text("Использование: /quest list | add <название> | done <ID>"); return
    sub = context.args[0].lower()
    if sub == "list":
        active = db.get_quests(group_id, "active")
        done   = db.get_quests(group_id, "completed")
        msg = "🗺️ Квесты:\n"
        if active: msg += "\n🔸 Активные:\n" + "\n".join(f"  [{q['id']}] {q['title']}" for q in active)
        if done:   msg += "\n\n✅ Выполненные:\n" + "\n".join(f"  [{q['id']}] {q['title']}" for q in done)
        if not active and not done: msg += "Нет квестов."
        await update.message.reply_text(msg, reply_markup=main_keyboard())
    elif sub == "add":
        if len(context.args) < 2: await update.message.reply_text("Укажи название: /quest add ..."); return
        title = " ".join(context.args[1:])
        q = db.add_quest(group_id, title)
        await update.message.reply_text(f"📋 Квест [{q['id']}]: {title}", reply_markup=main_keyboard())
    elif sub == "done":
        if len(context.args) < 2 or not context.args[1].isdigit():
            await update.message.reply_text("Укажи ID: /quest done 3"); return
        ok = db.complete_quest(group_id, int(context.args[1]))
        await update.message.reply_text(
            "✅ Квест выполнен!" if ok else "❌ Квест не найден.",
            reply_markup=main_keyboard(),
        )


async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    if not context.args: await update.message.reply_text("Использование: /save <название>"); return
    name = " ".join(context.args)
    ok   = db.save_game(group_id, user_id, name)
    await update.message.reply_text(
        f"{'💾 Сохранено: ' + name if ok else '❌ Нет персонажа.'}",
        reply_markup=main_keyboard(),
    )


async def cmd_load(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    if not context.args: await update.message.reply_text("Использование: /load <название>"); return
    name = " ".join(context.args)
    if db.load_game(group_id, user_id, name):
        player = db.get_player(group_id, user_id)
        await update.message.reply_text(
            f"📂 Загружено: «{name}»\n\n{format_status(player)}",
            reply_markup=main_keyboard(),
        )
    else:
        saves = db.list_saves(group_id, user_id)
        names = "\n".join(f"• {s['save_name']}" for s in saves)
        await update.message.reply_text(
            (f"❌ Не найдено.\n\nДоступные:\n{names}" if saves else "❌ Сохранений нет.")
        )


async def cmd_saves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    saves = db.list_saves(group_id, user_id)
    if not saves: await update.message.reply_text("💾 Нет сохранений. /save <название>"); return
    msg = "💾 Сохранения:\n" + "\n".join(
        f"• {s['save_name']} ({s['created_at'][:10]})" for s in saves
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard())


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    history = db.get_history(group_id, 40)
    if not history: await update.message.reply_text("История пуста."); return
    await update.message.chat.send_action(ChatAction.TYPING)
    msgs = [
        {"role":"system","content":"Ты — летописец. Кратко (5–7 предложений) изложи события на русском."},
        *history,
        {"role":"user","content":"Краткая летопись всего приключения?"},
    ]
    try:
        reply = await ask_ai(msgs, max_tokens=500)
        await update.message.reply_text(f"📜 Летопись:\n\n{reply}", reply_markup=main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def send_help(message):
    await message.reply_text(
        "📖 D&D Master v3 — команды\n\n"
        "🎮 Персонаж:\n"
        "/start — создать персонажа (визард)\n"
        "/info — твой лист (в группе → личка)\n"
        "/reset — сбросить персонажа\n"
        "/summary — летопись событий\n\n"
        "👥 Группа:\n"
        "/join — вступить в партию\n"
        "/party — состав партии\n"
        "/roll_initiative — бросить инициативу\n"
        "/done — завершить ход\n"
        "/end_combat — завершить бой\n\n"
        "⚔️ Бой:\n"
        "/fight <враг> — начать бой\n"
        "/roll [NdS] — бросок кубика\n"
        "/check <навык> — проверка навыка\n"
        "/spell <ур> <название> — заклинание\n"
        "/damage <N> — получить урон\n"
        "/heal <N> — лечение\n\n"
        "🎒 Предметы:\n"
        "/take <предмет> — взять\n"
        "/drop <предмет> — выбросить\n"
        "/gold +N/-N — изменить золото\n"
        "/add_exp <N> — добавить XP\n\n"
        "🗺️ Квесты:\n"
        "/quest list | add <название> | done <ID>\n\n"
        "💾 Сохранения:\n"
        "/save <название> | /load <название> | /saves",
        reply_markup=main_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update.message)


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id, user_id = get_ids(update)
    username = get_username(update)
    player   = db.get_player(group_id, user_id)
    if not player:
        player = db.create_player(group_id, user_id, username)

    # In group: check whose turn it is
    ts = db.get_turn_state(group_id)
    if ts and ts["turn_order"] and is_group(update):
        order   = ts["turn_order"]
        cur_uid = order[ts["current_idx"] % len(order)]
        if cur_uid != user_id and db.is_in_party(group_id, user_id):
            members  = db.get_party(group_id)
            name_map = {m["user_id"]: m["username"] for m in members}
            await update.message.reply_text(
                f"⚠️ Сейчас ход @{name_map.get(cur_uid,'?')}!\n"
                f"Используй /done чтобы пропустить или дождись своей очереди."
            )
            return

    # Prefix group messages with player name
    text = update.message.text
    if is_group(update):
        text = f"[{player.get('name', username)}]: {text}"

    db.add_message(group_id, "user", text, user_id=user_id)
    await update.message.chat.send_action(ChatAction.TYPING)
    await dm_reply(update, group_id, user_id)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    db.connect()
    logger.info("DB: %s | Model: %s", db.db_path, MODEL)

    app = ApplicationBuilder().token(TG_TOKEN).build()

    wizard = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            CHOOSE_RACE:  [CallbackQueryHandler(handle_race,    pattern=r"^race_")],
            CHOOSE_CLASS: [CallbackQueryHandler(handle_class,   pattern=r"^class_")],
            CHOOSE_STATS: [CallbackQueryHandler(handle_stats,   pattern=r"^stats_")],
            ENTER_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            CONFIRM:      [CallbackQueryHandler(handle_confirm, pattern=r"^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(wizard)
    app.add_handler(CallbackQueryHandler(handle_callback))

    for name, handler in [
        ("reset",           cmd_reset),
        ("status",          cmd_status),
        ("info",            cmd_info),
        ("heal",            cmd_heal),
        ("damage",          cmd_damage),
        ("take",            cmd_take),
        ("drop",            cmd_drop),
        ("gold",            cmd_gold),
        ("add_exp",         cmd_add_exp),
        ("roll",            cmd_roll),
        ("check",           cmd_check),
        ("fight",           cmd_fight),
        ("spell",           cmd_spell),
        ("quest",           cmd_quest),
        ("save",            cmd_save),
        ("load",            cmd_load),
        ("saves",           cmd_saves),
        ("summary",         cmd_summary),
        ("help",            cmd_help),
        ("join",            cmd_join),
        ("party",           cmd_party),
        ("roll_initiative", cmd_roll_initiative),
        ("done",            cmd_done),
        ("end_combat",      cmd_end_combat),
    ]:
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot v3 started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
