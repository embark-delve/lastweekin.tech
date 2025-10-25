import sqlite3
from pathlib import Path

# The database will be stored in the data directory
DB_FILE = Path(__file__).parent.parent / "data" / "lastweekintech.db"

def get_db_connection() -> sqlite3.Connection:
    """Establishes a connection to the SQLite database."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def create_schema(conn: sqlite3.Connection):
    """Creates the necessary database tables if they don't already exist."""
    cursor = conn.cursor()

    # Articles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            published_ts INTEGER NOT NULL,
            hn_points INTEGER,
            hn_comments INTEGER,
            content TEXT,
            fetch_status TEXT NOT NULL
        )
    """)

    # Clusters table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id TEXT PRIMARY KEY,
            repr_article_id INTEGER,
            source_hits INTEGER NOT NULL,
            hn_points_max INTEGER NOT NULL,
            published_min_ts INTEGER NOT NULL,
            score REAL,
            FOREIGN KEY (repr_article_id) REFERENCES articles (id)
        )
    """)

    # Cluster members table (junction table)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cluster_members (
            cluster_id TEXT NOT NULL,
            article_id INTEGER NOT NULL,
            PRIMARY KEY (cluster_id, article_id),
            FOREIGN KEY (cluster_id) REFERENCES clusters (cluster_id),
            FOREIGN KEY (article_id) REFERENCES articles (id)
        )
    """)

    conn.commit()

if __name__ == '__main__':
    # A simple script to initialize the database
    print("Initializing database schema...")
    connection = get_db_connection()
    create_schema(connection)
    connection.close()
    print(f"Database created and schema initialized at {DB_FILE}")
