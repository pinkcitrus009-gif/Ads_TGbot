import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = os.environ.get("DB_PATH", "dnd_bot_v3.db")


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.create_tables()

    def create_tables(self):
        self.conn.executescript('''
            -- Per-player character data keyed by (group_id, user_id)
            -- For private chats group_id == user_id (Telegram private chat id == user id)
            CREATE TABLE IF NOT EXISTS players (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                username     TEXT    DEFAULT '',
                name         TEXT    DEFAULT 'Герой',
                race         TEXT    DEFAULT 'Человек',
                class        TEXT    DEFAULT 'Авантюрист',
                level        INTEGER DEFAULT 1,
                hp           INTEGER DEFAULT 10,
                max_hp       INTEGER DEFAULT 10,
                armor_class  INTEGER DEFAULT 10,
                exp          INTEGER DEFAULT 0,
                exp_next     INTEGER DEFAULT 300,
                gold         INTEGER DEFAULT 0,
                strength     INTEGER DEFAULT 10,
                dexterity    INTEGER DEFAULT 10,
                constitution INTEGER DEFAULT 10,
                intelligence INTEGER DEFAULT 10,
                wisdom       INTEGER DEFAULT 10,
                charisma     INTEGER DEFAULT 10,
                inventory    TEXT    DEFAULT '[]',
                abilities    TEXT    DEFAULT '[]',
                spell_slots  TEXT    DEFAULT NULL,
                combat_state TEXT    DEFAULT NULL,
                hit_die      INTEGER DEFAULT 8,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );

            -- Shared narrative history per group
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

            -- Quests are per group (shared story)
            CREATE TABLE IF NOT EXISTS quests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                status      TEXT    DEFAULT 'active',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Who is playing in each group (for multi-player)
            CREATE TABLE IF NOT EXISTS party (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                username   TEXT    DEFAULT '',
                initiative INTEGER DEFAULT 0,
                joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            );

            -- Turn state per group (combat / exploration turns)
            CREATE TABLE IF NOT EXISTS turn_state (
                group_id     INTEGER PRIMARY KEY,
                turn_order   TEXT    DEFAULT '[]',
                current_idx  INTEGER DEFAULT 0,
                round_number INTEGER DEFAULT 1,
                mode         TEXT    DEFAULT 'exploration',
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Save slots
            CREATE TABLE IF NOT EXISTS saved_games (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                save_name    TEXT    NOT NULL,
                player_data  TEXT    NOT NULL,
                history_data TEXT    NOT NULL,
                quest_data   TEXT    NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id, save_name)
            );
        ''')
        self.conn.commit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _decode_player(self, row) -> Dict:
        data = dict(row)
        data['inventory']    = json.loads(data.get('inventory')    or '[]')
        data['abilities']    = json.loads(data.get('abilities')    or '[]')
        data['spell_slots']  = json.loads(data['spell_slots'])  if data.get('spell_slots')  else {}
        data['combat_state'] = json.loads(data['combat_state']) if data.get('combat_state') else None
        return data

    # ── Players ───────────────────────────────────────────────────────────────

    def get_player(self, group_id: int, user_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            'SELECT * FROM players WHERE group_id=? AND user_id=?', (group_id, user_id)
        ).fetchone()
        return self._decode_player(row) if row else None

    def create_player(self, group_id: int, user_id: int, username: str = '') -> Dict:
        self.conn.execute(
            'INSERT OR IGNORE INTO players (group_id, user_id, username) VALUES (?,?,?)',
            (group_id, user_id, username)
        )
        self.conn.commit()
        return self.get_player(group_id, user_id)

    def update_player(self, group_id: int, user_id: int, **kwargs) -> Dict:
        for key in ('inventory', 'abilities', 'spell_slots', 'combat_state'):
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
        self.conn.execute(
            'DELETE FROM players WHERE group_id=? AND user_id=?', (group_id, user_id)
        )
        self.conn.commit()
        return self.create_player(group_id, user_id, username)

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
        # Ensure player record exists
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
        return d

    def set_turn_state(self, group_id: int, turn_order: List[int],
                       current_idx: int = 0, round_number: int = 1,
                       mode: str = 'combat'):
        self.conn.execute(
            '''INSERT INTO turn_state (group_id, turn_order, current_idx, round_number, mode, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(group_id) DO UPDATE SET
                 turn_order=excluded.turn_order,
                 current_idx=excluded.current_idx,
                 round_number=excluded.round_number,
                 mode=excluded.mode,
                 updated_at=excluded.updated_at''',
            (group_id, json.dumps(turn_order), current_idx, round_number, mode,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def advance_turn(self, group_id: int) -> Optional[Dict]:
        ts = self.get_turn_state(group_id)
        if not ts or not ts['turn_order']:
            return None
        next_idx = (ts['current_idx'] + 1) % len(ts['turn_order'])
        new_round = ts['round_number'] + (1 if next_idx == 0 else 0)
        self.conn.execute(
            'UPDATE turn_state SET current_idx=?, round_number=?, updated_at=? WHERE group_id=?',
            (next_idx, new_round, datetime.now().isoformat(), group_id)
        )
        self.conn.commit()
        return self.get_turn_state(group_id)

    def clear_turn_state(self, group_id: int):
        self.conn.execute('DELETE FROM turn_state WHERE group_id=?', (group_id,))
        self.conn.commit()

    # ── Save / Load ───────────────────────────────────────────────────────────

    def save_game(self, group_id: int, user_id: int, save_name: str) -> bool:
        player = self.get_player(group_id, user_id)
        if not player:
            return False
        self.conn.execute(
            '''INSERT OR REPLACE INTO saved_games
               (group_id, user_id, save_name, player_data, history_data, quest_data)
               VALUES (?,?,?,?,?,?)''',
            (
                group_id, user_id, save_name,
                json.dumps(player,                           ensure_ascii=False),
                json.dumps(self.get_history(group_id, 60),  ensure_ascii=False),
                json.dumps(self.get_quests(group_id, 'all'),ensure_ascii=False),
            )
        )
        self.conn.commit()
        return True

    def load_game(self, group_id: int, user_id: int, save_name: str) -> bool:
        row = self.conn.execute(
            'SELECT * FROM saved_games WHERE group_id=? AND user_id=? AND save_name=?',
            (group_id, user_id, save_name)
        ).fetchone()
        if not row:
            return False
        player_data  = json.loads(row['player_data'])
        history_data = json.loads(row['history_data'])
        quest_data   = json.loads(row['quest_data'])
        for k in ('id', 'created_at', 'updated_at'):
            player_data.pop(k, None)
        self.conn.execute('DELETE FROM players WHERE group_id=? AND user_id=?', (group_id, user_id))
        self.conn.execute('INSERT OR IGNORE INTO players (group_id, user_id) VALUES (?,?)', (group_id, user_id))
        self.conn.commit()
        self.update_player(group_id, user_id, **player_data)
        self.clear_history(group_id)
        for msg in history_data:
            self.add_message(group_id, msg['role'], msg['content'])
        self.conn.execute('DELETE FROM quests WHERE group_id=?', (group_id,))
        for q in quest_data:
            self.conn.execute(
                'INSERT INTO quests (group_id, title, description, status) VALUES (?,?,?,?)',
                (group_id, q['title'], q.get('description',''), q['status'])
            )
        self.conn.commit()
        return True

    def list_saves(self, group_id: int, user_id: int) -> List[Dict]:
        rows = self.conn.execute(
            'SELECT save_name, created_at FROM saved_games '
            'WHERE group_id=? AND user_id=? ORDER BY created_at DESC',
            (group_id, user_id)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if self.conn:
            self.conn.close()
