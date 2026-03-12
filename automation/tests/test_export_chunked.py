"""
AC 검증: competitor_users CSV 추출이 청크 단위(fetchmany)로만 동작하는지,
메모리에 전체를 올리지 않는지 검증합니다.
"""
import csv
import os
import tempfile
from unittest.mock import patch

from app.db import (
    ensure_db,
    export_competitor_users_to_csv_file,
    save_competitor_user,
)


def test_export_competitor_users_to_csv_file_uses_fetchmany_not_fetchall():
    """AC2 검증: export_competitor_users_to_csv_file 구현이 fetchmany만 사용하고 fetchall 미사용."""
    import app.db as db_module

    with open(db_module.__file__, encoding="utf-8") as f:
        source = f.read()
    start = source.find("def export_competitor_users_to_csv_file")
    end = source.find("\ndef ", start + 1)
    func_body = source[start:end] if end != -1 else source[start:]
    assert "fetchmany" in func_body, "must use fetchmany (chunked read)"
    assert "fetchall" not in func_body, "must not use fetchall (AC2: no full load in memory)"


def test_export_competitor_users_to_csv_file_row_count_and_columns():
    """청크 단위 내보내기 시 행 수와 컬럼 수가 올바른지 검증."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "posts.db")
        with patch("app.db.DATA_DIR", tmpdir), patch("app.db.DB_PATH", db_path):
            ensure_db()
            for i in range(700):
                save_competitor_user(
                    source="test",
                    group_url="https://t.me/test",
                    telegram_user_id=10000 + i,
                    username=f"u{i}",
                    last_seen="",
                )
            out_path = os.path.join(tmpdir, "export.csv")
            row_count = export_competitor_users_to_csv_file(out_path, chunk_size=500)
            assert row_count == 700

        with open(out_path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["id", "source", "group_url", "telegram_user_id", "username", "last_seen", "scraped_at"]
            data_rows = list(reader)
        assert len(data_rows) == 700
