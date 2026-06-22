import random
import re
import json
from typing import Dict, List, Tuple, Optional

# ── Level XP thresholds ───────────────────────────────────────────────────────

LEVEL_XP = [
    0, 300, 900, 2700, 6500, 14000, 23000, 34000,
    48000, 64000, 85000, 100000, 120000, 140000,
    165000, 195000, 225000, 265000, 305000, 355000,
]

# ── Races ─────────────────────────────────────────────────────────────────────

RACES: Dict[str, Dict] = {
    "Человек":          {"str":1,"dex":1,"con":1,"int":1,"wis":1,"cha":1, "desc":"Универсальны — +1 ко всем"},
    "Эльф":             {"dex":2,"int":1,                                  "desc":"+2 Ловкость, +1 Интеллект"},
    "Дварф":            {"con":2,"wis":1,                                  "desc":"+2 Телосложение, +1 Мудрость"},
    "Полурослик":       {"dex":2,"cha":1,                                  "desc":"+2 Ловкость, +1 Харизма"},
    "Гном":             {"int":2,"con":1,                                  "desc":"+2 Интеллект, +1 Телосложение"},
    "Полуорк":          {"str":2,"con":1,                                  "desc":"+2 Сила, +1 Телосложение"},
    "Тифлинг":          {"cha":2,"int":1,                                  "desc":"+2 Харизма, +1 Интеллект"},
    "Драконорождённый": {"str":2,"cha":1,                                  "desc":"+2 Сила, +1 Харизма"},
}

# ── Classes ───────────────────────────────────────────────────────────────────

CLASSES: Dict[str, Dict] = {
    "Воин":     {"hp":10,"ac":16,"caster":False,"hit_die":10,"desc":"Мастер боя, высокий КД"},
    "Маг":      {"hp":6, "ac":12,"caster":True, "hit_die":6, "desc":"Повелитель магии, хрупкий"},
    "Жрец":     {"hp":8, "ac":14,"caster":True, "hit_die":8, "desc":"Целитель и защитник"},
    "Плут":     {"hp":8, "ac":13,"caster":False,"hit_die":8, "desc":"Ловкач, мастер скрытности"},
    "Варвар":   {"hp":12,"ac":11,"caster":False,"hit_die":12,"desc":"Берсерк, самый живучий"},
    "Бард":     {"hp":8, "ac":13,"caster":True, "hit_die":8, "desc":"Вдохновитель, разносторонний"},
    "Паладин":  {"hp":10,"ac":16,"caster":True, "hit_die":10,"desc":"Воин света, полукастер"},
    "Следопыт": {"hp":10,"ac":13,"caster":True, "hit_die":10,"desc":"Охотник, мастер природы"},
}

FULL_CASTERS  = {"Маг", "Жрец", "Бард"}
HALF_CASTERS  = {"Паладин", "Следопыт"}

FULL_CASTER_SLOTS = {
    1:{1:2}, 2:{1:3}, 3:{1:4,2:2}, 4:{1:4,2:3}, 5:{1:4,2:3,3:2},
    6:{1:4,2:3,3:3}, 7:{1:4,2:3,3:3,4:1}, 8:{1:4,2:3,3:3,4:2},
    9:{1:4,2:3,3:3,4:3,5:1}, 10:{1:4,2:3,3:3,4:3,5:2},
}
HALF_CASTER_SLOTS = {
    1:{}, 2:{1:2}, 3:{1:3}, 4:{1:3}, 5:{1:4,2:2},
    6:{1:4,2:2}, 7:{1:4,2:3}, 8:{1:4,2:3}, 9:{1:4,2:3,3:2}, 10:{1:4,2:3,3:2},
}

SKILL_MAP = {
    'акробатика':'dexterity','атлетика':'strength','восприятие':'wisdom',
    'выживание':'wisdom','история':'intelligence','запугивание':'charisma',
    'магия':'intelligence','медицина':'wisdom','обман':'charisma',
    'обращение с животными':'wisdom','природа':'intelligence',
    'проницательность':'wisdom','религия':'intelligence','скрытность':'dexterity',
    'убеждение':'charisma','ловкость рук':'dexterity','расследование':'intelligence',
    'выступление':'charisma',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def modifier(stat: int) -> int:
    return (stat - 10) // 2

def modifier_str(stat: int) -> str:
    m = modifier(stat)
    return f"+{m}" if m >= 0 else str(m)

def bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    filled = round(length * max(0, current) / maximum)
    return "█" * filled + "░" * (length - filled)

def xp_for_level(level: int) -> int:
    if level <= 0:
        return 0
    if level >= len(LEVEL_XP):
        return LEVEL_XP[-1]
    return LEVEL_XP[level]

def check_level_up(player: Dict) -> Tuple[bool, int]:
    level, exp = player['level'], player['exp']
    new_level = level
    for lvl in range(level, 19):
        if exp >= xp_for_level(lvl + 1):
            new_level = lvl + 1
        else:
            break
    return new_level > level, new_level

def roll_4d6() -> int:
    rolls = sorted([random.randint(1, 6) for _ in range(4)])
    return sum(rolls[1:])

def roll_stats_array() -> List[int]:
    return [roll_4d6() for _ in range(6)]

def default_spell_slots(class_name: str, level: int) -> Dict[str, List[int]]:
    lvl = min(level, 10)
    if class_name in FULL_CASTERS:
        table = FULL_CASTER_SLOTS.get(lvl, {})
    elif class_name in HALF_CASTERS:
        table = HALF_CASTER_SLOTS.get(lvl, {})
    else:
        table = {}
    return {str(sl): [n, n] for sl, n in table.items()}

DICE_RE = re.compile(r'^(\d*)d(\d+)([+-]\d+)?$', re.IGNORECASE)

def roll_dice(expr: str) -> Tuple[str, int]:
    expr = expr.strip().replace(' ', '').lower()
    m = DICE_RE.match(expr)
    if not m:
        raise ValueError(f"Неверный формат: {expr}")
    n_s, s_s, mod_s = m.groups()
    n   = int(n_s) if n_s else 1
    s   = int(s_s)
    mod = int(mod_s) if mod_s else 0
    if not (1 <= n <= 100): raise ValueError("Кубиков: 1–100")
    if not (2 <= s <= 1000): raise ValueError("Граней: 2–1000")
    rolls = [random.randint(1, s) for _ in range(n)]
    total = sum(rolls) + mod
    rolls_str = ', '.join(str(r) for r in rolls)
    mod_part  = f" {mod_s}" if mod_s else ""
    return f"🎲 {n}d{s}{mod_part}: [{rolls_str}]{mod_part} = **{total}**", total

# ── Format status ─────────────────────────────────────────────────────────────

def format_status(player: Dict, short: bool = False) -> str:
    hp, max_hp = player.get('hp', 10), player.get('max_hp', 10)
    exp = player.get('exp', 0)
    exp_next = player.get('exp_next', 300)
    inv  = player.get('inventory', [])
    abl  = player.get('abilities', [])
    hp_icon = "❤️" if hp > max_hp * 0.5 else ("🟡" if hp > max_hp * 0.25 else "🔴")
    s, d, c = player.get('strength',10), player.get('dexterity',10), player.get('constitution',10)
    i, w, ch = player.get('intelligence',10), player.get('wisdom',10), player.get('charisma',10)

    if short:
        return (
            f"⚔️ {player.get('name','?')} ({player.get('race','?')} {player.get('class','?')} "
            f"ур.{player.get('level',1)})\n"
            f"{hp_icon} HP: {hp}/{max_hp}  {bar(hp,max_hp)}\n"
            f"💰 {player.get('gold',0)} зм   🛡️ КД {player.get('armor_class',10)}"
        )

    lines = [
        f"╔══ ⚔️ ЛИСТ ПЕРСОНАЖА ══╗",
        f"👤 {player.get('name','?')} ({player.get('race','?')} • {player.get('class','?')} • {player.get('level',1)} ур.)",
        f"{hp_icon} HP:  {hp}/{max_hp}  {bar(hp,max_hp)}",
        f"⭐ XP:  {exp}/{exp_next}  {bar(exp,exp_next)}",
        f"🛡️ КД: {player.get('armor_class',10)}   💰 {player.get('gold',0)} зм",
        "",
        f"💪 Сила:         {s:>2} ({modifier_str(s)})",
        f"🏃 Ловкость:     {d:>2} ({modifier_str(d)})",
        f"🧱 Телосложение: {c:>2} ({modifier_str(c)})",
        f"🧠 Интеллект:    {i:>2} ({modifier_str(i)})",
        f"🔭 Мудрость:     {w:>2} ({modifier_str(w)})",
        f"✨ Харизма:      {ch:>2} ({modifier_str(ch)})",
    ]

    if inv:
        lines.append(f"\n🎒 {', '.join(inv)}")
    if abl:
        lines.append(f"🔮 {', '.join(abl)}")

    slots = player.get('spell_slots', {})
    if slots:
        slot_parts = []
        for lvl in sorted(slots.keys(), key=int):
            v = slots[lvl]
            cur, mx = (v[0], v[1]) if isinstance(v, list) else (v, v)
            slot_parts.append(f"{lvl}ур:{cur}/{mx}")
        lines.append(f"🪄 Слоты: {', '.join(slot_parts)}")

    lines.append("╚══════════════════════╝")
    return "\n".join(lines)

def build_context(player: Dict, quests: List[Dict]) -> str:
    lines = ["=== ПЕРСОНАЖ ИГРОКА ===", format_status(player)]
    if quests:
        lines.append("\n🗺️ Активные квесты:")
        for q in quests[:5]:
            lines.append(f"  [{q['id']}] {q['title']}")
    lines.append("=== КОНЕЦ ===")
    return "\n".join(lines)

def build_party_context(players: List[Dict], quests: List[Dict]) -> str:
    lines = ["=== ПАРТИЯ ИГРОКОВ ==="]
    for p in players:
        hp, mhp = p.get('hp',10), p.get('max_hp',10)
        lines.append(
            f"• {p.get('name','?')} ({p.get('race','?')} {p.get('class','?')} ур.{p.get('level',1)}) "
            f"❤️{hp}/{mhp}"
        )
    if quests:
        lines.append("\n🗺️ Квесты группы:")
        for q in quests[:5]:
            lines.append(f"  [{q['id']}] {q['title']}")
    lines.append("=== КОНЕЦ ===")
    return "\n".join(lines)

# ── Memory block formatter ────────────────────────────────────────────────────

MEMORY_ICONS = {
    "npc":    "👤",
    "world":  "🌍",
    "plot":   "📖",
    "player": "🎭",
    "loot":   "💎",
}

def format_memory_block(memories: List[Dict]) -> str:
    """Форматирует записи долгосрочной памяти для вставки в системный промпт."""
    if not memories:
        return ""

    by_cat: Dict[str, List[Dict]] = {}
    for m in memories:
        cat = m.get("category", "world")
        by_cat.setdefault(cat, []).append(m)

    lines = ["📚 ПАМЯТЬ DM (всегда актуально):"]
    order = ["plot", "npc", "world", "player", "loot"]
    for cat in order:
        if cat not in by_cat:
            continue
        icon = MEMORY_ICONS.get(cat, "•")
        for entry in by_cat[cat]:
            lines.append(f"  {icon} [{entry['key']}] {entry['value']}")

    # остальные категории (не из стандартных)
    for cat, entries in by_cat.items():
        if cat in order:
            continue
        for entry in entries:
            lines.append(f"  • [{entry['key']}] {entry['value']}")

    return "\n".join(lines)

# ── AI State Parser ───────────────────────────────────────────────────────────

STATE_RE = re.compile(r'\[STATE\](.*?)\[/STATE\]', re.DOTALL | re.IGNORECASE)

def parse_ai_state(text: str) -> Tuple[str, Optional[Dict]]:
    """Extract [STATE]...[/STATE] block from AI response.
    Returns (clean_text, state_dict or None).
    """
    match = STATE_RE.search(text)
    if not match:
        return text, None
    raw   = match.group(1).strip()
    clean = STATE_RE.sub('', text).strip()
    try:
        state = json.loads(raw)
        return clean, state
    except (json.JSONDecodeError, ValueError):
        return text, None
