import sqlite3

from storage import Store


def test_store_migrates_existing_db_missing_read_plates_column(tmp_path):
    """Simulates a persistent volume created before `read_plates` existed:
    `CREATE TABLE IF NOT EXISTS` alone would silently skip adding it, so
    opening a Store against that old schema must not crash and must add
    the column (see storage.py's `_ensure_column`)."""
    data_dir = tmp_path / "data"
    (data_dir / "images").mkdir(parents=True)
    (data_dir / "clips").mkdir(parents=True)
    db_path = data_dir / "history.db"

    # Pre-create clip_searches WITHOUT read_plates, as an old deployment would have.
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE clip_searches (
               id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, task TEXT NOT NULL,
               prompt TEXT NOT NULL, generation_mode TEXT NOT NULL, status TEXT NOT NULL,
               error TEXT, frames_total INTEGER NOT NULL, frames_done INTEGER NOT NULL DEFAULT 0,
               matches_json TEXT, created_at TEXT NOT NULL, finished_at TEXT
           )""")
    conn.commit()
    conn.close()

    store = Store(str(data_dir))
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(clip_searches)")}
    assert "read_plates" in cols

    row = store.create_search(
        search_id="s1",
        clip_id="c1",
        task="ground_multi",
        prompt="a car",
        generation_mode="fast",
        frames_total=1,
        read_plates=True,
    )
    assert row["read_plates"] is True
