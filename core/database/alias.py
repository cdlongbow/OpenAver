"""core.database.alias — AliasRecord 與 AliasRepository（女優別名，spec-87 子模組）。"""
import sqlite3
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from . import connection


@dataclass
class AliasRecord:
    """新版女優別名資料模型（平坦 group schema）"""
    primary_name: str = ""
    aliases: List[str] = field(default_factory=list)  # JSON array
    source: str = "manual"  # 'manual' | 'auto'
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """轉為字典（JSON 欄位序列化）"""
        data = asdict(self)
        data["aliases"] = json.dumps(self.aliases, ensure_ascii=False)
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.updated_at:
            data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_row(cls, row: tuple, columns: List[str]) -> "AliasRecord":
        """從資料庫 row 建立"""
        data = dict(zip(columns, row, strict=True))
        if "aliases" in data and data["aliases"]:
            try:
                data["aliases"] = json.loads(data["aliases"])
            except json.JSONDecodeError:
                data["aliases"] = []
        else:
            data["aliases"] = []
        if "created_at" in data and data["created_at"]:
            if isinstance(data["created_at"], str):
                data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and data["updated_at"]:
            if isinstance(data["updated_at"], str):
                data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class AliasRepository:
    """新版女優別名資料存取層（平坦 group schema）"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or connection.get_db_path()

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連線"""
        return connection.get_connection(self.db_path)

    def _get_columns(self) -> List[str]:
        """取得欄位名稱列表"""
        return ["primary_name", "aliases", "source", "created_at", "updated_at"]

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_all(self) -> List[AliasRecord]:
        """取得所有別名組，依 primary_name 排序"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM actress_aliases ORDER BY primary_name"
            )
            rows = cursor.fetchall()
            cols = self._get_columns()
            return [AliasRecord.from_row(row, cols) for row in rows]
        finally:
            conn.close()

    def get_by_primary(self, name: str) -> Optional[AliasRecord]:
        """根據 primary_name 查詢；不存在回傳 None"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM actress_aliases WHERE primary_name = ?", (name,)
            )
            row = cursor.fetchone()
            if row:
                return AliasRecord.from_row(row, self._get_columns())
            return None
        finally:
            conn.close()

    def find_by_alias(self, alias: str) -> Optional[AliasRecord]:
        """在 aliases JSON 陣列中搜尋；不存在回傳 None"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """SELECT aa.* FROM actress_aliases aa, json_each(aa.aliases)
                   WHERE json_each.value = ?""",
                (alias,),
            )
            row = cursor.fetchone()
            if row:
                return AliasRecord.from_row(row, self._get_columns())
            return None
        finally:
            conn.close()

    def resolve(self, name: str) -> set:
        """
        解析名稱：
        - primary hit  → {primary_name} ∪ set(aliases)
        - alias hit    → {primary_name} ∪ set(aliases)
        - miss         → {name}
        """
        record = self.get_by_primary(name)
        if record is None:
            record = self.find_by_alias(name)
        if record is None:
            return {name}
        return {record.primary_name} | set(record.aliases)

    # ------------------------------------------------------------------
    # Write methods — all use BEGIN EXCLUSIVE
    # ------------------------------------------------------------------

    def add(
        self,
        primary_name: str,
        aliases: Optional[List[str]] = None,
        source: str = "manual",
    ) -> AliasRecord:
        """
        新增別名組。

        Raises:
            ValueError: primary_name 已存在（作為 primary 或 alias）
        """
        if aliases is None:
            aliases = []

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 全域唯一檢查 primary_name
            ok, msg = self._check_global_uniqueness_cursor(cursor, primary_name)
            if not ok:
                raise ValueError(msg)

            # 全域唯一檢查每個 alias
            for alias in aliases:
                ok, msg = self._check_global_uniqueness_cursor(cursor, alias)
                if not ok:
                    raise ValueError(f"alias '{alias}': {msg}")

            aliases_json = json.dumps(aliases, ensure_ascii=False)
            cursor.execute(
                """INSERT INTO actress_aliases (primary_name, aliases, source)
                   VALUES (?, ?, ?)""",
                (primary_name, aliases_json, source),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return self.get_by_primary(primary_name)

    def add_alias(self, primary_name: str, alias: str) -> tuple:
        """
        為既有 group 新增一個 alias。

        Returns:
            (True, None)       — 成功
            (False, error_msg) — 衝突
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 確認 primary 存在
            cursor.execute(
                "SELECT aliases FROM actress_aliases WHERE primary_name = ?",
                (primary_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return False, f"'{primary_name}' 不存在"

            # 全域唯一檢查（排除自己的 group）
            ok, msg = self._check_global_uniqueness_cursor(
                cursor, alias, exclude_primary=primary_name
            )
            if not ok:
                conn.rollback()
                return False, msg

            current = json.loads(row[0]) if row[0] else []
            if alias not in current:
                current.append(alias)
            cursor.execute(
                """UPDATE actress_aliases
                   SET aliases = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE primary_name = ?""",
                (json.dumps(current, ensure_ascii=False), primary_name),
            )
            conn.commit()
            return True, None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def remove_alias(self, primary_name: str, alias: str) -> bool:
        """
        從 group 中移除一個 alias。

        Returns:
            True  — 成功移除
            False — alias 不存在
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")
            cursor.execute(
                "SELECT aliases FROM actress_aliases WHERE primary_name = ?",
                (primary_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            current = json.loads(row[0]) if row[0] else []
            if alias not in current:
                return False
            current.remove(alias)
            cursor.execute(
                """UPDATE actress_aliases
                   SET aliases = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE primary_name = ?""",
                (json.dumps(current, ensure_ascii=False), primary_name),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete(self, name: str) -> bool:
        """
        刪除 group。name 可為 primary 或 alias（先 resolve 取得 primary）。

        Returns:
            True  — 成功刪除
            False — 不存在
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 解析 primary_name
            cursor.execute(
                "SELECT primary_name FROM actress_aliases WHERE primary_name = ?",
                (name,),
            )
            row = cursor.fetchone()
            if row is None:
                # 試 alias
                cursor.execute(
                    """SELECT aa.primary_name FROM actress_aliases aa, json_each(aa.aliases)
                       WHERE json_each.value = ?""",
                    (name,),
                )
                row = cursor.fetchone()
            if row is None:
                return False

            primary = row[0]
            cursor.execute(
                "DELETE FROM actress_aliases WHERE primary_name = ?", (primary,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sync_from_favorite(
        self, name: str, aliases: List[str], source: str = "auto"
    ) -> dict:
        """
        從 favorite 同步 alias group（resolve-first，CD-6）。

        Returns:
            {"primary_name": str, "skipped_aliases": list[str]}
        """
        # resolve name → 找到所屬 group (若有)
        resolved = self.resolve(name)
        target_record: Optional[AliasRecord] = None

        if len(resolved) > 1 or (len(resolved) == 1 and name not in resolved):
            # name 解析到某個 group
            primary_in_resolved = next(
                (n for n in resolved if self.get_by_primary(n) is not None), None
            )
            if primary_in_resolved:
                target_record = self.get_by_primary(primary_in_resolved)
        else:
            target_record = self.get_by_primary(name)

        target_primary = target_record.primary_name if target_record else name

        # §46 guard: 無既有記錄 + 輸入 aliases 為空 → 不建空記錄
        if target_record is None and not aliases:
            return {"primary_name": target_primary, "skipped_aliases": []}

        conn = self._get_connection()
        cursor = conn.cursor()
        skipped: List[str] = []
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 逐一檢查 incoming aliases
            merged_aliases: List[str] = list(target_record.aliases) if target_record else []
            for alias in aliases:
                if alias == target_primary or alias in merged_aliases:
                    continue
                ok, _ = self._check_global_uniqueness_cursor(
                    cursor, alias, exclude_primary=target_primary
                )
                if not ok:
                    skipped.append(alias)
                else:
                    merged_aliases.append(alias)

            aliases_json = json.dumps(merged_aliases, ensure_ascii=False)
            if target_record is None:
                cursor.execute(
                    """INSERT INTO actress_aliases (primary_name, aliases, source)
                       VALUES (?, ?, ?)""",
                    (target_primary, aliases_json, source),
                )
            else:
                cursor.execute(
                    """UPDATE actress_aliases
                       SET aliases = ?, source = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE primary_name = ?""",
                    (aliases_json, source, target_primary),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return {"primary_name": target_primary, "skipped_aliases": skipped}

    # ------------------------------------------------------------------
    # Private helper — cursor-based uniqueness check (within transaction)
    # ------------------------------------------------------------------

    def _check_global_uniqueness_cursor(
        self, cursor, name: str, exclude_primary: Optional[str] = None
    ) -> tuple:
        """
        Same as _check_global_uniqueness but uses an existing cursor (within a transaction).
        """
        # Check primary_name
        cursor.execute(
            "SELECT primary_name FROM actress_aliases WHERE primary_name = ?", (name,)
        )
        row = cursor.fetchone()
        if row and row[0] != exclude_primary:
            return False, f"'{name}' 已是 primary_name"

        # Check aliases (json_each)
        cursor.execute(
            """SELECT aa.primary_name FROM actress_aliases aa, json_each(aa.aliases)
               WHERE json_each.value = ?""",
            (name,),
        )
        row = cursor.fetchone()
        if row and row[0] != exclude_primary:
            return False, f"'{name}' 已經是 '{row[0]}' 的別名"

        return True, None
