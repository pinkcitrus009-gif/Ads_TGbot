import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Tuple

DB_PATH = os.environ.get("DB_PATH", "dnd_bot_v3.db")

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.create_tables()
        self._migrate()

    def create_tables(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS players (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id            INTEGER NOT NULL,
                user_id             INTEGER NOT NULL,
                username            TEXT    DEFAULT '',
                name                TEXT    DEFAULT 'Герой',
                race                TEXT    DEFAULT 'Человек',
                class               TEXT    DEFAULT 'Авантюрист',
                level               INTEGER DEFAULT 1,
                hp                  INTEGER DEFAULT 10,
                max_hp              INTEGER DEFAULT 10,
                armor_class         INTEGER DEFAULT 10,
                exp                 INTEGER DEFAULT 0,
                exp_next            INTEGER DEFAULT 300,
                gold                INTEGER DEFAULT 0,
                strength            INTEGER DEFAULT 10,
                dexterity           INTEGER DEFAULT 10,
                constitution        INTEGER DEFAULT 10,
                intelligence        INTEGER DEFAULT 10,
                wisdom              INTEGER DEFAULT 10,
                charisma            INTEGER DEFAULT 10,
                inventory           TEXT    DEFAULT '[]',
                abilities           TEXT    DEFAULT '[]',
                spell_slots         TEXT    DEFAULT NULL,
                combat_state        TEXT    DEFAULT NULL,
                hit_die             INTEGER DEFAULT 8,
                -- D&D 5e расширенные поля
                speed               INTEGER DEFAULT 30,
                background          TEXT    DEFAULT '',
                alignment           TEXT    DEFAULT '',
                inspiration         INTEGER DEFAULT 0,
                saving_throw_profs  TEXT    DEFAULT '[]',
                skill_profs         TEXT    DEFAULT '[]',
                skill_expertises    TEXT    DEFAULT '[]',
                languages           TEXT    DEFAULT '[]',
                armor_profs         TEXT    DEFAULT '[]',
                weapon_profs        TEXT    DEFAULT '[]',
                tool_profs          TEXT    DEFAULT '[]',
                features            TEXT    DEFAULT '[]',
                personality         TEXT    DEFAULT '',
                ideals              TEXT    DEFAULT '',
                bonds               TEXT    DEFAULT '',
                flaws               TEXT    DEFAULT '',
                death_saves_success INTEGER DEFAULT 0,
                death_saves_failure INTEGER DEFAULT 0,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                user_id    INTEGER DEFAULT NULL,
                is_summary INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_history ON history(group_id, created_at);

            CREATE TABLE IF NOT EXISTS quests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                status      TEXT    DEFAULT 'active',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS party (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                username   TEXT    DEFAULT '',
                initiative INTEGER DEFAULT 0,
                joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS turn_state (
                group_id              INTEGER PRIMARY KEY,
                turn_order            TEXT    DEFAULT '[]',
                current_idx           INTEGER DEFAULT 0,
                round_number          INTEGER DEFAULT 1,
                mode                  TEXT    DEFAULT 'exploration',
                pending_clarification TEXT    DEFAULT NULL,
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Глобальные сохранения (привязаны только к user_id, не к group_id)
            -- История и квесты не сохраняются — они остаются локальными для группы
            CREATE TABLE IF NOT EXISTS saved_games (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                save_name   TEXT    NOT NULL,
                player_data TEXT    NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, save_name)
            );

            CREATE TABLE IF NOT EXISTS game_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                category   TEXT    NOT NULL,
                key        TEXT    NOT NULL,
                value      TEXT    NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, category, key) ON CONFLICT REPLACE
            );

            CREATE INDEX IF NOT EXISTS idx_memory ON game_memory(group_id, category);
        ''')
        self.conn.commit()

    def _migrate(self):
        """Безопасные миграции схемы БД (no-op если уже выполнено)."""

        # ── turn_state: добавить pending_clarification если нет ────────────────
        for col_def in ["pending_clarification TEXT DEFAULT NULL"]:
            col_name = col_def.split()[0]
            try:
                self.conn.execute(f"ALTER TABLE turn_state ADD COLUMN {col_def}")
                self.conn.commit()
            except Exception:
                pass

        # ── game_memory: создать если нет (старая БД) ──────────────────────────
        try:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS game_memory ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "group_id INTEGER NOT NULL, "
                "category TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "value TEXT NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "UNIQUE(group_id, category, key) ON CONFLICT REPLACE)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory ON game_memory(group_id, category)"
            )
            self.conn.commit()
        except Exception:
            pass

        # ── players: добавить D&D 5e поля если их нет (миграция старых БД) ──────
        new_player_cols = [
            "speed               INTEGER DEFAULT 30",
            "background          TEXT    DEFAULT ''",
            "alignment           TEXT    DEFAULT ''",
            "inspiration         INTEGER DEFAULT 0",
            "saving_throw_profs  TEXT    DEFAULT '[]'",
            "skill_profs         TEXT    DEFAULT '[]'",
            "skill_expertises    TEXT    DEFAULT '[]'",
            "languages           TEXT    DEFAULT '[]'",
            "armor_profs         TEXT    DEFAULT '[]'",
            "weapon_profs        TEXT    DEFAULT '[]'",
            "tool_profs          TEXT    DEFAULT '[]'",
            "features            TEXT    DEFAULT '[]'",
            "personality         TEXT    DEFAULT ''",
            "ideals              TEXT    DEFAULT ''",
            "bonds               TEXT    DEFAULT ''",
            "flaws               TEXT    DEFAULT ''",
            "death_saves_success INTEGER DEFAULT 0",
            "death_saves_failure INTEGER DEFAULT 0",
        ]
        existing_cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(players)").fetchall()
        }
        for col_def in new_player_cols:
            col_name = col_def.strip().split()[0]
            if col_name not in existing_cols:
                try:
                    self.conn.execute(f"ALTER TABLE players ADD COLUMN {col_def}")
                    self.conn.commit()
                    logger.info("Migration: added players.%s", col_name)
                except Exception as exc:
                    logger.warning("Migration players.%s skipped: %s", col_name, exc)

        # ── saved_games: миграция со старой схемы (с group_id) на глобальную ──
        # Определяем, есть ли колонка group_id в saved_games
        try:
            cols = [
                row[1]
                for row in self.conn.execute("PRAGMA table_info(saved_games)").fetchall()
            ]
            if "group_id" in cols:
                logger.info("Migrating saved_games to global schema...")
                self.conn.executescript('''
                    CREATE TABLE IF NOT EXISTS saved_games_global_new (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     INTEGER NOT NULL,
                        save_name   TEXT    NOT NULL,
                        player_data TEXT    NOT NULL,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, save_name)
                    );

                    -- Копируем существующие сохранения; при конфликте имён оставляем последнее по времени
                    INSERT OR REPLACE INTO saved_games_global_new
                        (user_id, save_name, player_data, created_at)
                    SELECT user_id, save_name, player_data, created_at
                    FROM saved_games
                    ORDER BY created_at ASC;

                    DROP TABLE saved_games;
                    ALTER TABLE saved_games_global_new RENAME TO saved_games;
                ''')
                self.conn.commit()
                logger.info("saved_games migration complete.")
        except Exception as e:
            logger.warning("saved_games migration failed (may already be new schema): %s", e)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _decode_player(self, row) -> Dict:
        data = dict(row)
        # Базовые списки
        data['inventory']    = json.loads(data.get('inventory')    or '[]')
        data['abilities']    = json.loads(data.get('abilities')    or '[]')
        data['spell_slots']  = json.loads(data['spell_slots'])  if data.get('spell_slots')  else {}
        data['combat_state'] = json.loads(data['combat_state']) if data.get('combat_state') else None
        # D&D 5e расширенные поля
        for list_field in (
            'saving_throw_profs', 'skill_profs', 'skill_expertises',
            'languages', 'armor_profs', 'weapon_profs', 'tool_profs', 'features',
        ):
            raw = data.get(list_field)
            data[list_field] = json.loads(raw) if raw else []
        # Текстовые поля — гарантируем строку
        for str_field in ('background', 'alignment', 'personality', 'ideals', 'bonds', 'flaws'):
            data[str_field] = data.get(str_field) or ''
        # Числовые поля с дефолтами
        data.setdefault('speed', 30)
        data.setdefault('inspiration', 0)
        data.setdefault('death_saves_success', 0)
        data.setdefault('death_saves_failure', 0)
        return data

    # ── Players ───────────────────────────────────────────────────────────────

    def get_player(self, group_id: int, user_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            'SELECT * FROM players WHERE group_id=? AND user_id=?', (group_id, user_id)
        ).fetchone()
        return self._decode_player(row) if row else None

    def get_any_player(self, user_id: int) -> Optional[Dict]:
        """Найти любого персонажа пользователя в любом чате (самый свежий по обновлению)."""
        row = self.conn.execute(
            'SELECT * FROM players WHERE user_id=? ORDER BY updated_at DESC LIMIT 1',
            (user_id,)
        ).fetchone()
        return self._decode_player(row) if row else None

    def _copy_player_from_any_group(
        self, user_id: int, target_group_id: int, username: str = ''
    ) -> bool:
        """Скопировать персонажа пользователя из любой другой группы в target_group_id.

        Возвращает True если копирование выполнено, False если не нашли источник.
        """
        row = self.conn.execute(
            'SELECT * FROM players WHERE user_id=? AND group_id!=? '
            'ORDER BY updated_at DESC LIMIT 1',
            (user_id, target_group_id)
        ).fetchone()
        if not row:
            return False

        src = dict(row)
        # Убираем поля, специфичные для исходной записи
        for k in ('id', 'group_id', 'created_at', 'updated_at'):
            src.pop(k, None)

        src['group_id'] = target_group_id
        src['username'] = username or src.get('username', '')

        cols         = ', '.join(src.keys())
        placeholders = ', '.join('?' for _ in src)
        self.conn.execute(
            f'INSERT OR IGNORE INTO players ({cols}) VALUES ({placeholders})',
            list(src.values())
        )
        self.conn.commit()
        return True

    def create_player(
        self, group_id: int, user_id: int, username: str = ''
    ) -> Tuple[Dict, bool]:
        """Создать персонажа для (group_id, user_id).

        Если у пользователя уже есть персонаж в другом чате — копирует его.
        Если нет ни одного — создаёт заготовку с дефолтными значениями.

        Возвращает (player_dict, was_copied: bool).
        """
        existing = self.get_player(group_id, user_id)
        if existing:
            return existing, False

        copied = self._copy_player_from_any_group(user_id, group_id, username)
        if not copied:
            self.conn.execute(
                'INSERT OR IGNORE INTO players (group_id, user_id, username) VALUES (?,?,?)',
                (group_id, user_id, username)
            )
            self.conn.commit()

        return self.get_player(group_id, user_id), copied

    def update_player(self, group_id: int, user_id: int, **kwargs) -> Dict:
        json_fields = (
            'inventory', 'abilities', 'spell_slots', 'combat_state',
            'saving_throw_profs', 'skill_profs', 'skill_expertises',
            'languages', 'armor_profs', 'weapon_profs', 'tool_profs', 'features',
        )
        for key in json_fields:
            if key in kwargs and not isinstance(kwargs[key], str):
                kwargs[key] = (json.dumps(kwargs[key], ensure_ascii=False)
                               if kwargs[key] is not None else None)
        kwargs['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join(f'{k} = ?' for k in kwargs)
        values     = list(kwargs.values()) + [group_id, user_id]
        self.conn.execute(
            f'UPDATE players SET {set_clause} WHERE group_id=? AND user_id=?', values
        )
        self.conn.commit()
        return self.get_player(group_id, user_id)

    def reset_player(self, group_id: int, user_id: int, username: str = '') -> Dict:
        """Сбросить персонажа в текущем чате. Глобальные сохранения НЕ затрагиваются."""
        self.conn.execute(
            'DELETE FROM players WHERE group_id=? AND user_id=?', (group_id, user_id)
        )
        self.conn.commit()
        player, _ = self.create_player(group_id, user_id, username)
        return player

    def get_all_players_in_group(self, group_id: int) -> List[Dict]:
        rows = self.conn.execute(
            'SELECT p.* FROM players p '
            'JOIN party m ON p.group_id=m.group_id AND p.user_id=m.user_id '
            'WHERE p.group_id=?', (group_id,)
        ).fetchall()
        return [self._decode_player(r) for r in rows]

    # ── History ───────────────────────────────────────────────────────────────

    def add_message(self, group_id: int, role: str, content: str,
                    user_id: int = None, is_summary: bool = False):
        self.conn.execute(
            'INSERT INTO history (group_id, role, content, user_id, is_summary) VALUES (?,?,?,?,?)',
            (group_id, role, content, user_id, 1 if is_summary else 0)
        )
        self.conn.commit()

    def get_history(self, group_id: int, limit: int = 30) -> List[Dict]:
        rows = self.conn.execute(
            'SELECT role, content FROM history WHERE group_id=? '
            'ORDER BY created_at DESC LIMIT ?', (group_id, limit)
        ).fetchall()
        return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]

    def get_oldest_history(self, group_id: int, n: int) -> List[Dict]:
        rows = self.conn.execute(
            'SELECT id, role, content FROM history '
            'WHERE group_id=? AND is_summary=0 '
            'ORDER BY created_at ASC LIMIT ?', (group_id, n)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_history_ids(self, group_id: int, ids: List[int]):
        placeholders = ','.join('?' for _ in ids)
        self.conn.execute(
            f'DELETE FROM history WHERE group_id=? AND id IN ({placeholders})',
            [group_id] + ids
        )
        self.conn.commit()

    def clear_history(self, group_id: int):
        self.conn.execute('DELETE FROM history WHERE group_id=?', (group_id,))
        self.conn.commit()

    def count_history(self, group_id: int) -> int:
        return self.conn.execute(
            'SELECT COUNT(*) FROM history WHERE group_id=?', (group_id,)
        ).fetchone()[0]

    # ── Quests ────────────────────────────────────────────────────────────────

    def add_quest(self, group_id: int, title: str, description: str = '') -> Dict:
        cur = self.conn.execute(
            'INSERT INTO quests (group_id, title, description) VALUES (?,?,?)',
            (group_id, title, description)
        )
        self.conn.commit()
        return dict(self.conn.execute('SELECT * FROM quests WHERE id=?', (cur.lastrowid,)).fetchone())

    def get_quests(self, group_id: int, status: str = 'active') -> List[Dict]:
        if status == 'all':
            rows = self.conn.execute(
                'SELECT * FROM quests WHERE group_id=? ORDER BY created_at', (group_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                'SELECT * FROM quests WHERE group_id=? AND status=? ORDER BY created_at',
                (group_id, status)
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_quest(self, group_id: int, quest_id: int) -> bool:
        cur = self.conn.execute(
            'UPDATE quests SET status="completed" WHERE id=? AND group_id=?',
            (quest_id, group_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── Party ─────────────────────────────────────────────────────────────────

    def join_party(self, group_id: int, user_id: int, username: str) -> bool:
        self.conn.execute(
            'INSERT OR REPLACE INTO party (group_id, user_id, username) VALUES (?,?,?)',
            (group_id, user_id, username)
        )
        self.conn.commit()
        # create_player теперь возвращает (player, was_copied) — нам нужен только player
        self.create_player(group_id, user_id, username)
        return True

    def leave_party(self, group_id: int, user_id: int):
        self.conn.execute(
            'DELETE FROM party WHERE group_id=? AND user_id=?', (group_id, user_id)
        )
        self.conn.commit()

    def get_party(self, group_id: int) -> List[Dict]:
        rows = self.conn.execute(
            'SELECT * FROM party WHERE group_id=? ORDER BY initiative DESC, joined_at',
            (group_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def set_initiative(self, group_id: int, user_id: int, value: int):
        self.conn.execute(
            'UPDATE party SET initiative=? WHERE group_id=? AND user_id=?',
            (value, group_id, user_id)
        )
        self.conn.commit()

    def reset_initiatives(self, group_id: int):
        self.conn.execute(
            'UPDATE party SET initiative=0 WHERE group_id=?', (group_id,)
        )
        self.conn.commit()

    def is_in_party(self, group_id: int, user_id: int) -> bool:
        row = self.conn.execute(
            'SELECT 1 FROM party WHERE group_id=? AND user_id=?', (group_id, user_id)
        ).fetchone()
        return row is not None

    # ── Turn state ────────────────────────────────────────────────────────────

    def get_turn_state(self, group_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            'SELECT * FROM turn_state WHERE group_id=?', (group_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d['turn_order'] = json.loads(d['turn_order'])
        d['pending_clarification'] = (
            json.loads(d['pending_clarification'])
            if d.get('pending_clarification') else None
        )
        return d

    def set_turn_state(self, group_id: int, turn_order: List[int],
                       current_idx: int = 0, round_number: int = 1,
                       mode: str = 'combat'):
        self.conn.execute(
            '''INSERT INTO turn_state
               (group_id, turn_order, current_idx, round_number, mode, pending_clarification, updated_at)
               VALUES (?,?,?,?,?,NULL,?)
               ON CONFLICT(group_id) DO UPDATE SET
                 turn_order=excluded.turn_order,
                 current_idx=excluded.current_idx,
                 round_number=excluded.round_number,
                 mode=excluded.mode,
                 pending_clarification=NULL,
                 updated_at=excluded.updated_at''',
            (group_id, json.dumps(turn_order), current_idx, round_number, mode,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def advance_turn(self, group_id: int) -> Optional[Dict]:
        ts = self.get_turn_state(group_id)
        if not ts or not ts['turn_order']:
            return None
        next_idx  = (ts['current_idx'] + 1) % len(ts['turn_order'])
        new_round = ts['round_number'] + (1 if next_idx == 0 else 0)
        self.conn.execute(
            '''UPDATE turn_state
               SET current_idx=?, round_number=?, pending_clarification=NULL, updated_at=?
               WHERE group_id=?''',
            (next_idx, new_round, datetime.now().isoformat(), group_id)
        )
        self.conn.commit()
        return self.get_turn_state(group_id)

    def set_pending_clarification(self, group_id: int, data: Optional[Dict]):
        val = json.dumps(data, ensure_ascii=False) if data else None
        self.conn.execute(
            'UPDATE turn_state SET pending_clarification=?, updated_at=? WHERE group_id=?',
            (val, datetime.now().isoformat(), group_id)
        )
        self.conn.commit()

    def clear_pending_clarification(self, group_id: int):
        self.set_pending_clarification(group_id, None)

    def clear_turn_state(self, group_id: int):
        self.conn.execute('DELETE FROM turn_state WHERE group_id=?', (group_id,))
        self.conn.commit()

    # ── Save / Load (глобальные — привязаны только к user_id) ────────────────

    def save_game(self, group_id: int, user_id: int, save_name: str) -> bool:
        """Сохранить персонажа глобально (group_id игнорируется при хранении).

        Сохраняется только player_data. История и квесты остаются локальными.
        """
        player = self.get_player(group_id, user_id)
        if not player:
            return False

        # Убираем служебные поля перед сохранением
        player_copy = {
            k: v for k, v in player.items()
            if k not in ('id', 'group_id', 'created_at', 'updated_at')
        }

        self.conn.execute(
            '''INSERT OR REPLACE INTO saved_games
               (user_id, save_name, player_data)
               VALUES (?,?,?)''',
            (user_id, save_name, json.dumps(player_copy, ensure_ascii=False))
        )
        self.conn.commit()
        return True

    def load_game(self, group_id: int, user_id: int, save_name: str) -> bool:
        """Загрузить персонажа из глобального сохранения в текущую группу.

        Ищет по (user_id, save_name) без учёта group_id.
        Обновляет только данные персонажа — история и квесты группы не затрагиваются.
        Если персонажа в группе ещё нет — создаёт запись.
        """
        row = self.conn.execute(
            'SELECT * FROM saved_games WHERE user_id=? AND save_name=?',
            (user_id, save_name)
        ).fetchone()
        if not row:
            return False

        player_data = json.loads(row['player_data'])

        # Убираем поля, которые не должны перезаписываться
        for k in ('id', 'group_id', 'created_at', 'updated_at'):
            player_data.pop(k, None)

        # Убеждаемся, что запись игрока в этой группе существует
        self.conn.execute(
            'INSERT OR IGNORE INTO players (group_id, user_id) VALUES (?,?)',
            (group_id, user_id)
        )
        self.conn.commit()

        # Применяем данные персонажа (история и квесты НЕ трогаются)
        self.update_player(group_id, user_id, **player_data)
        return True

    def list_saves(self, group_id: int, user_id: int) -> List[Dict]:
        """Список сохранений пользователя (глобальные — group_id игнорируется)."""
        rows = self.conn.execute(
            'SELECT save_name, created_at FROM saved_games '
            'WHERE user_id=? ORDER BY created_at DESC',
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_save(self, user_id: int, save_name: str) -> bool:
        """Удалить конкретное сохранение пользователя."""
        cur = self.conn.execute(
            'DELETE FROM saved_games WHERE user_id=? AND save_name=?',
            (user_id, save_name)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── Game Memory ───────────────────────────────────────────────────────────

    def add_memory(self, group_id: int, category: str, key: str, value: str):
        """Добавить или обновить запись в долгосрочной памяти DM."""
        now = datetime.now().isoformat()
        self.conn.execute(
            '''INSERT INTO game_memory (group_id, category, key, value, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(group_id, category, key) DO UPDATE SET
                 value=excluded.value,
                 updated_at=excluded.updated_at''',
            (group_id, category.lower(), key, value, now, now)
        )
        self.conn.commit()

    def get_memory(self, group_id: int, category: str = None) -> List[Dict]:
        """Получить записи памяти. category=None → все категории."""
        if category:
            rows = self.conn.execute(
                'SELECT category, key, value FROM game_memory '
                'WHERE group_id=? AND category=? ORDER BY category, key',
                (group_id, category.lower())
            ).fetchall()
        else:
            rows = self.conn.execute(
                'SELECT category, key, value FROM game_memory '
                'WHERE group_id=? ORDER BY category, key',
                (group_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_memory(self, group_id: int, key: str) -> bool:
        """Удалить запись памяти по ключу (ищет во всех категориях)."""
        cur = self.conn.execute(
            'DELETE FROM game_memory WHERE group_id=? AND key=?', (group_id, key)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def clear_memory(self, group_id: int):
        """Очистить всю память для группы."""
        self.conn.execute('DELETE FROM game_memory WHERE group_id=?', (group_id,))
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
