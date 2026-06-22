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

RACE_SPEED: Dict[str, int] = {
    "Человек":          30,
    "Эльф":             30,
    "Дварф":            25,
    "Полурослик":       25,
    "Гном":             25,
    "Полуорк":          30,
    "Тифлинг":          30,
    "Драконорождённый": 30,
}

RACE_LANGUAGES: Dict[str, List[str]] = {
    "Человек":          ["Общий", "на выбор"],
    "Эльф":             ["Общий", "Эльфийский"],
    "Дварф":            ["Общий", "Дварфийский"],
    "Полурослик":       ["Общий", "Полурослинский"],
    "Гном":             ["Общий", "Гномий"],
    "Полуорк":          ["Общий", "Орочий"],
    "Тифлинг":          ["Общий", "Инфернальный"],
    "Драконорождённый": ["Общий", "Драконий"],
}

RACE_TRAITS: Dict[str, List[str]] = {
    "Человек":          ["Универсальность человека"],
    "Эльф":             ["Тёмное зрение 60 фт.", "Острые чувства", "Наследие фей", "Транс"],
    "Дварф":            ["Тёмное зрение 60 фт.", "Стойкость дварфа", "Знание камня", "Боевая подготовка дварфов"],
    "Полурослик":       ["Удача", "Храбрость", "Проворство полурослика"],
    "Гном":             ["Тёмное зрение 60 фт.", "Хитрость гнома"],
    "Полуорк":          ["Тёмное зрение 60 фт.", "Устрашающий", "Несгибаемость", "Жестокие удары"],
    "Тифлинг":          ["Тёмное зрение 60 фт.", "Адское сопротивление огню", "Инфернальное наследие"],
    "Драконорождённый": ["Драконье происхождение", "Оружие дыхания", "Сопротивление урону"],
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

# Спасброски (привязанные характеристики по классу)
CLASS_SAVING_THROWS: Dict[str, List[str]] = {
    "Воин":     ["strength", "constitution"],
    "Маг":      ["intelligence", "wisdom"],
    "Жрец":     ["wisdom", "charisma"],
    "Плут":     ["dexterity", "intelligence"],
    "Варвар":   ["strength", "constitution"],
    "Бард":     ["dexterity", "charisma"],
    "Паладин":  ["wisdom", "charisma"],
    "Следопыт": ["strength", "dexterity"],
}

# Навыки по умолчанию для класса (2–4 тематических)
CLASS_DEFAULT_SKILLS: Dict[str, List[str]] = {
    "Воин":     ["атлетика", "запугивание"],
    "Маг":      ["магия", "история"],
    "Жрец":     ["религия", "медицина"],
    "Плут":     ["скрытность", "ловкость рук", "обман", "восприятие"],
    "Варвар":   ["атлетика", "выживание"],
    "Бард":     ["выступление", "убеждение", "обман"],
    "Паладин":  ["религия", "убеждение"],
    "Следопыт": ["выживание", "природа", "восприятие"],
}

# Черты и особые умения 1-го уровня по классу
CLASS_FEATURES_L1: Dict[str, List[str]] = {
    "Воин":     ["Боевой стиль", "Второе дыхание (1 раз/отдых)"],
    "Маг":      ["Использование заклинаний", "Восстановление магии (1 раз/день)"],
    "Жрец":     ["Использование заклинаний", "Божественный домен"],
    "Плут":     ["Опыт (×2 к двум навыкам)", "Скрытная атака 1к6", "Воровской жаргон"],
    "Варвар":   ["Ярость (2 заряда/день)", "Защита без доспехов (10+Тел+Лов)"],
    "Бард":     ["Использование заклинаний", "Вдохновение барда к6 (Хар/день)"],
    "Паладин":  ["Чувство добра и зла", "Возложение рук (пул 5 HP/уровень/день)"],
    "Следопыт": ["Излюбленный враг", "Исследователь природы"],
}

# Владение доспехами
CLASS_ARMOR_PROFS: Dict[str, List[str]] = {
    "Воин":     ["Лёгкие", "Средние", "Тяжёлые", "Щиты"],
    "Маг":      [],
    "Жрец":     ["Лёгкие", "Средние", "Щиты"],
    "Плут":     ["Лёгкие"],
    "Варвар":   ["Лёгкие", "Средние", "Щиты"],
    "Бард":     ["Лёгкие"],
    "Паладин":  ["Лёгкие", "Средние", "Тяжёлые", "Щиты"],
    "Следопыт": ["Лёгкие", "Средние", "Щиты"],
}

# Владение оружием
CLASS_WEAPON_PROFS: Dict[str, List[str]] = {
    "Воин":     ["Простое оружие", "Воинское оружие"],
    "Маг":      ["Кинжалы", "Дротики", "Пращи", "Посохи", "Лёгкие арбалеты"],
    "Жрец":     ["Простое оружие"],
    "Плут":     ["Простое оружие", "Ручные арбалеты", "Длинные мечи", "Рапиры", "Короткие мечи"],
    "Варвар":   ["Простое оружие", "Воинское оружие"],
    "Бард":     ["Простое оружие", "Ручные арбалеты", "Длинные мечи", "Рапиры", "Короткие мечи"],
    "Паладин":  ["Простое оружие", "Воинское оружие"],
    "Следопыт": ["Простое оружие", "Воинское оружие"],
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

# Полный список навыков: название → характеристика
SKILL_MAP: Dict[str, str] = {
    'акробатика':          'dexterity',
    'атлетика':            'strength',
    'восприятие':          'wisdom',
    'выживание':           'wisdom',
    'выступление':         'charisma',
    'запугивание':         'charisma',
    'история':             'intelligence',
    'ловкость рук':        'dexterity',
    'магия':               'intelligence',
    'медицина':            'wisdom',
    'обман':               'charisma',
    'обращение с животными': 'wisdom',
    'природа':             'intelligence',
    'проницательность':    'wisdom',
    'расследование':       'intelligence',
    'религия':             'intelligence',
    'скрытность':          'dexterity',
    'убеждение':           'charisma',
}

# Порядок навыков для отображения на листе
SKILLS_ORDER: List[str] = [
    'акробатика', 'атлетика', 'восприятие', 'выживание', 'выступление',
    'запугивание', 'история', 'ловкость рук', 'магия', 'медицина',
    'обман', 'обращение с животными', 'природа', 'проницательность',
    'расследование', 'религия', 'скрытность', 'убеждение',
]

# Краткие названия характеристик
ABILITY_NAMES: Dict[str, str] = {
    'strength':     'Сил',
    'dexterity':    'Лов',
    'constitution': 'Тел',
    'intelligence': 'Инт',
    'wisdom':       'Муд',
    'charisma':     'Хар',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def modifier(stat: int) -> int:
    return (stat - 10) // 2

def modifier_str(stat: int) -> str:
    m = modifier(stat)
    return f"+{m}" if m >= 0 else str(m)

def _sign(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)

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

def proficiency_bonus(level: int) -> int:
    """Бонус мастерства по уровню (D&D 5e): +2 на 1–4, +3 на 5–8, +4 на 9–12, +5 на 13–16, +6 на 17–20."""
    return max(2, (level - 1) // 4 + 2)

def get_saving_throw(player: Dict, ability: str) -> int:
    """Итоговый спасбросок с учётом владения."""
    stat = player.get(ability, 10)
    mod  = modifier(stat)
    profs = player.get('saving_throw_profs', [])
    pb    = proficiency_bonus(player.get('level', 1)) if ability in profs else 0
    return mod + pb

def get_skill_modifier(player: Dict, skill: str) -> int:
    """Итоговый модификатор навыка с учётом владения и опыта (экспертизы)."""
    ability = SKILL_MAP.get(skill, 'dexterity')
    stat    = player.get(ability, 10)
    mod     = modifier(stat)
    level   = player.get('level', 1)
    pb      = proficiency_bonus(level)
    if skill in player.get('skill_expertises', []):
        return mod + pb * 2
    elif skill in player.get('skill_profs', []):
        return mod + pb
    return mod

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


# ── Format status — полный лист персонажа (D&D 5e) ───────────────────────────

def format_status(player: Dict, short: bool = False) -> str:
    hp, max_hp = player.get('hp', 10), player.get('max_hp', 10)
    exp      = player.get('exp', 0)
    exp_next = player.get('exp_next', 300)
    level    = player.get('level', 1)
    inv      = player.get('inventory', [])
    abl      = player.get('abilities', [])

    hp_icon = "❤️" if hp > max_hp * 0.5 else ("🟡" if hp > max_hp * 0.25 else "🔴")

    s  = player.get('strength',     10)
    d  = player.get('dexterity',    10)
    c  = player.get('constitution', 10)
    i  = player.get('intelligence', 10)
    w  = player.get('wisdom',       10)
    ch = player.get('charisma',     10)

    if short:
        return (
            f"⚔️ {player.get('name','?')} ({player.get('race','?')} {player.get('class','?')} "
            f"ур.{level})\n"
            f"{hp_icon} HP: {hp}/{max_hp}  {bar(hp,max_hp)}\n"
            f"💰 {player.get('gold',0)} зм   🛡️ КД {player.get('armor_class',10)}"
        )

    # Вычисляем числа
    pb          = proficiency_bonus(level)
    dex_mod     = modifier(d)
    initiative  = dex_mod
    speed       = player.get('speed', 30)
    ac          = player.get('armor_class', 10)
    gold        = player.get('gold', 0)
    inspiration = player.get('inspiration', 0)
    background  = player.get('background', '')
    alignment   = player.get('alignment', '')

    saving_throw_profs = player.get('saving_throw_profs', [])
    skill_profs        = player.get('skill_profs', [])
    skill_expertises   = player.get('skill_expertises', [])
    features           = player.get('features', [])
    languages          = player.get('languages', [])
    armor_profs        = player.get('armor_profs', [])
    weapon_profs       = player.get('weapon_profs', [])
    tool_profs         = player.get('tool_profs', [])
    personality        = player.get('personality', '')
    ideals             = player.get('ideals', '')
    bonds              = player.get('bonds', '')
    flaws              = player.get('flaws', '')
    death_succ         = player.get('death_saves_success', 0)
    death_fail         = player.get('death_saves_failure', 0)

    lines = ["╔══ ⚔️ ЛИСТ ПЕРСОНАЖА (D&D 5e) ══╗"]

    # ── Шапка ──────────────────────────────────────────────────────────────
    insp = " 💡" if inspiration else ""
    lines.append(f"👤 {player.get('name','?')}{insp}")
    lines.append(f"   {player.get('race','?')} • {player.get('class','?')} • {level} ур.")
    bg_parts = []
    if background: bg_parts.append(f"📖 {background}")
    if alignment:  bg_parts.append(f"⚖️ {alignment}")
    if bg_parts:   lines.append("   " + "  |  ".join(bg_parts))

    # ── HP / XP / Бой ──────────────────────────────────────────────────────
    lines.append("")
    lines.append(f"{hp_icon} HP: {hp}/{max_hp}  {bar(hp, max_hp)}")
    lines.append(f"⭐ XP: {exp}/{exp_next}  {bar(exp, exp_next)}")
    lines.append(
        f"🛡️ КД: {ac}  ⚡ Иниц.: {_sign(initiative)}  "
        f"🏃 {speed} фт.  💰 {gold} зм  🎲 к{player.get('hit_die', 8)}"
    )
    if hp == 0:
        succ_pips = "✅" * death_succ + "◻️" * (3 - death_succ)
        fail_pips = "❌" * death_fail + "◻️" * (3 - death_fail)
        lines.append(f"💀 Смерть: {succ_pips} / {fail_pips}")

    # ── Характеристики и спасброски ────────────────────────────────────────
    lines.append("")
    lines.append(f"── ХАРАКТЕРИСТИКИ & СПАСБРОСКИ (проф. бонус +{pb}) ──")

    stats_data = [
        ("💪 Сила",          "strength",     s),
        ("🏃 Ловкость",      "dexterity",    d),
        ("🧱 Телосложение",  "constitution", c),
        ("🧠 Интеллект",     "intelligence", i),
        ("🔭 Мудрость",      "wisdom",       w),
        ("✨ Харизма",       "charisma",     ch),
    ]
    for label, key, val in stats_data:
        m_val   = modifier(val)
        st_val  = get_saving_throw(player, key)
        p_mark  = "✦" if key in saving_throw_profs else " "
        lines.append(
            f"{label:<18} {val:>2} ({_sign(m_val)})  Сп: {_sign(st_val):>3} {p_mark}"
        )

    # Пассивное восприятие
    pass_perc = 10 + get_skill_modifier(player, 'восприятие')
    lines.append(f"👁 Пассивное восприятие: {pass_perc}")

    # ── Навыки ─────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("── НАВЫКИ ──────────────────────────────────────")
    for skill in SKILLS_ORDER:
        sk_mod = get_skill_modifier(player, skill)
        abn    = ABILITY_NAMES[SKILL_MAP[skill]]
        mod_s  = _sign(sk_mod)
        if skill in skill_expertises:
            mark = "✦✦"
        elif skill in skill_profs:
            mark = "✦ "
        else:
            mark = "  "
        # Форматируем имя с заглавной буквы, максимум 22 символа
        name_cap = skill.capitalize()
        lines.append(f"{mark} {name_cap:<24} ({abn}) {mod_s:>3}")

    # ── Черты и особенности ────────────────────────────────────────────────
    if features:
        lines.append("")
        lines.append("── ЧЕРТЫ И ОСОБЕННОСТИ ─────────────────────────")
        for feat in features:
            lines.append(f"• {feat}")

    # ── Особые способности (из AI / ручные) ───────────────────────────────
    if abl:
        lines.append("")
        lines.append("── ОСОБЫЕ СПОСОБНОСТИ ──────────────────────────")
        for ab in abl:
            lines.append(f"🔮 {ab}")

    # ── Владение ───────────────────────────────────────────────────────────
    if languages or armor_profs or weapon_profs or tool_profs:
        lines.append("")
        lines.append("── ВЛАДЕНИЕ ────────────────────────────────────")
        if languages:    lines.append(f"🌍 Языки:        {', '.join(languages)}")
        if armor_profs:  lines.append(f"🛡️ Доспехи:      {', '.join(armor_profs)}")
        if weapon_profs: lines.append(f"⚔️ Оружие:       {', '.join(weapon_profs)}")
        if tool_profs:   lines.append(f"🔧 Инструменты:  {', '.join(tool_profs)}")

    # ── Характер / личность ────────────────────────────────────────────────
    if any([personality, ideals, bonds, flaws]):
        lines.append("")
        lines.append("── ХАРАКТЕР ────────────────────────────────────")
        if personality: lines.append(f"🎭 Черта:   {personality}")
        if ideals:      lines.append(f"💫 Идеал:   {ideals}")
        if bonds:       lines.append(f"🔗 Связь:   {bonds}")
        if flaws:       lines.append(f"⚠️ Слабость:{flaws}")

    # ── Инвентарь ──────────────────────────────────────────────────────────
    if inv:
        lines.append("")
        lines.append("── ИНВЕНТАРЬ ───────────────────────────────────")
        lines.append(f"🎒 {', '.join(inv)}")

    # ── Слоты заклинаний ───────────────────────────────────────────────────
    slots = player.get('spell_slots', {})
    if slots:
        lines.append("")
        slot_parts = []
        for lvl in sorted(slots.keys(), key=int):
            v = slots[lvl]
            cur, mx = (v[0], v[1]) if isinstance(v, list) else (v, v)
            slot_parts.append(f"{lvl}ур:{cur}/{mx}")
        lines.append(f"🪄 Слоты заклинаний: {', '.join(slot_parts)}")
        # Заклятие-сохранение DC и бонус атаки заклинаниями
        caster_class = player.get('class', '')
        if caster_class in (FULL_CASTERS | HALF_CASTERS):
            ability_map = {
                "Маг": i, "Жрец": w, "Бард": ch,
                "Паладин": ch, "Следопыт": w,
            }
            cast_stat = ability_map.get(caster_class, 10)
            spell_dc  = 8 + pb + modifier(cast_stat)
            spell_atk = pb + modifier(cast_stat)
            lines.append(f"🔮 Сл. DC: {spell_dc}  Бонус атаки: {_sign(spell_atk)}")

    lines.append("╚═══════════════════════════════════════════╝")
    return "\n".join(lines)


# ── DM context ────────────────────────────────────────────────────────────────

def build_context(player: Dict, quests: List[Dict]) -> str:
    """Контекст персонажа для системного промпта DM (краткий, но полный)."""
    hp, max_hp = player.get('hp', 10), player.get('max_hp', 10)
    level = player.get('level', 1)
    pb    = proficiency_bonus(level)

    s  = player.get('strength',     10)
    d  = player.get('dexterity',    10)
    c  = player.get('constitution', 10)
    i  = player.get('intelligence', 10)
    w  = player.get('wisdom',       10)
    ch = player.get('charisma',     10)

    lines = [
        "=== ПЕРСОНАЖ ИГРОКА ===",
        f"Имя: {player.get('name','?')}  Раса: {player.get('race','?')}  "
        f"Класс: {player.get('class','?')}  Уровень: {level}",
        f"HP: {hp}/{max_hp}  КД: {player.get('armor_class',10)}  "
        f"Скорость: {player.get('speed',30)} фт.  "
        f"Иниц.: {_sign(modifier(d))}  Проф.бон.: +{pb}",
        f"Золото: {player.get('gold',0)} зм",
        "",
        "Характеристики (модификатор | спасбросок):",
        f"  Сила {s}({_sign(modifier(s))}|Сп{_sign(get_saving_throw(player,'strength'))})  "
        f"Ловк {d}({_sign(modifier(d))}|Сп{_sign(get_saving_throw(player,'dexterity'))})  "
        f"Тел {c}({_sign(modifier(c))}|Сп{_sign(get_saving_throw(player,'constitution'))})",
        f"  Инт {i}({_sign(modifier(i))}|Сп{_sign(get_saving_throw(player,'intelligence'))})  "
        f"Муд {w}({_sign(modifier(w))}|Сп{_sign(get_saving_throw(player,'wisdom'))})  "
        f"Хар {ch}({_sign(modifier(ch))}|Сп{_sign(get_saving_throw(player,'charisma'))})",
    ]

    # Профильные навыки
    skill_profs = player.get('skill_profs', [])
    skill_exp   = player.get('skill_expertises', [])
    if skill_profs or skill_exp:
        prof_parts = []
        for sk in skill_profs:
            m = get_skill_modifier(player, sk)
            tag = "✦✦" if sk in skill_exp else "✦"
            prof_parts.append(f"{tag}{sk.capitalize()}({_sign(m)})")
        lines.append(f"Навыки: {', '.join(prof_parts)}")

    lines.append(f"Пассивное восприятие: {10 + get_skill_modifier(player,'восприятие')}")

    # Черты и способности
    feats = player.get('features', [])
    abl   = player.get('abilities', [])
    all_feats = feats + abl
    if all_feats:
        lines.append(f"Черты/Способности: {', '.join(all_feats)}")

    # Инвентарь
    inv = player.get('inventory', [])
    if inv:
        lines.append(f"Инвентарь: {', '.join(inv)}")

    # Слоты заклинаний
    slots = player.get('spell_slots', {})
    if slots:
        sp = ', '.join(
            f"{k}ур:{v[0] if isinstance(v,list) else v}/{v[1] if isinstance(v,list) else v}"
            for k, v in sorted(slots.items(), key=lambda x: int(x[0]))
        )
        lines.append(f"Слоты заклинаний: {sp}")

    if quests:
        lines.append("\nАктивные квесты:")
        for q in quests[:5]:
            lines.append(f"  [{q['id']}] {q['title']}")

    lines.append("=== КОНЕЦ ===")
    return "\n".join(lines)


def build_party_context(players: List[Dict], quests: List[Dict]) -> str:
    lines = ["=== ПАРТИЯ ИГРОКОВ ==="]
    for p in players:
        hp, mhp = p.get('hp',10), p.get('max_hp',10)
        level   = p.get('level', 1)
        pb      = proficiency_bonus(level)
        lines.append(
            f"• {p.get('name','?')} (@{p.get('username','?')}) — "
            f"{p.get('race','?')} {p.get('class','?')} ур.{level}  "
            f"HP:{hp}/{mhp}  КД:{p.get('armor_class',10)}  Проф.бон.:+{pb}"
        )
        # Основные навыки партийца
        sp = p.get('skill_profs', [])
        if sp:
            lines.append(
                f"    Навыки: {', '.join(sk.capitalize() for sk in sp[:4])}"
            )
    if quests:
        lines.append("\nКвесты группы:")
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
    for cat, entries in by_cat.items():
        if cat in order:
            continue
        for entry in entries:
            lines.append(f"  • [{entry['key']}] {entry['value']}")
    return "\n".join(lines)


# ── AI State Parser ───────────────────────────────────────────────────────────

STATE_RE = re.compile(r'\[STATE\](.*?)\[/STATE\]', re.DOTALL | re.IGNORECASE)

def parse_ai_state(text: str) -> Tuple[str, Optional[Dict]]:
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
