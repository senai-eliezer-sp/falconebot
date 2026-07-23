import sqlite3
from contextlib import contextmanager
from config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT,
                cpf TEXT,
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                login TEXT,
                senha TEXT,
                cartao TEXT,
                cvv TEXT,
                validade TEXT,
                bandeira TEXT,
                nivel TEXT,
                tipo TEXT,
                banco TEXT,
                pais TEXT,
                nome TEXT,
                cpf TEXT,
                valor REAL,
                perfil TEXT,
                is_sold INTEGER NOT NULL DEFAULT 0,
                sold_to INTEGER,
                sold_at TEXT
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                id_transaction TEXT UNIQUE,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'WAITING_FOR_APPROVAL',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                stock_id INTEGER NOT NULL,
                price REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _migrate_stock_table(conn)


def _migrate_stock_table(conn):
    """Adiciona as novas colunas em bancos criados antes desta versão."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(stock)").fetchall()}
    for column, column_type in {
        "login": "TEXT",
        "senha": "TEXT",
        "cartao": "TEXT",
        "cvv": "TEXT",
        "validade": "TEXT",
        "bandeira": "TEXT",
        "nivel": "TEXT",
        "tipo": "TEXT",
        "banco": "TEXT",
        "pais": "TEXT",
        "nome": "TEXT",
        "cpf": "TEXT",
        "valor": "REAL",
        "perfil": "TEXT",
    }.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE stock ADD COLUMN {column} {column_type}")


# ---------- Usuários ----------

def get_or_create_user(telegram_id: int, name: str) -> sqlite3.Row:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (telegram_id, name, balance) VALUES (?, ?, 0)",
                (telegram_id, name),
            )
            row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row


def get_balance(telegram_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row["balance"] if row else 0.0


def get_user(telegram_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()


def set_user_payment_info(telegram_id: int, email: str, cpf: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET email = ?, cpf = ? WHERE telegram_id = ?",
            (email, cpf, telegram_id),
        )


def add_balance(telegram_id: int, amount: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
            (amount, telegram_id),
        )


def deduct_balance(telegram_id: int, amount: float) -> bool:
    """Retorna False se saldo insuficiente (operação atômica)."""
    with get_conn() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row is None or row["balance"] < amount:
            return False
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        return True


# ---------- Produtos / Estoque ----------

def create_product(name: str, price: float = 0.0) -> int:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        return cur.lastrowid


def list_active_products():
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT p.id, p.name, p.price,
                   (SELECT COUNT(*) FROM stock s WHERE s.product_id = p.id AND s.is_sold = 0) AS qty
            FROM products p
            WHERE p.active = 1
            ORDER BY p.id
            """
        ).fetchall()


def get_product(product_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


def get_product_by_name(name: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE name = ?", (name,)).fetchone()


def get_available_count(product_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM stock WHERE product_id = ? AND is_sold = 0",
            (product_id,),
        ).fetchone()
        return row["c"]


def get_available_count_by_name(name: str) -> int:
    """Retorna a quantidade disponível em estoque para uma categoria pelo nome.
    Se a categoria (produto) não existir, retorna 0."""
    prod = get_product_by_name(name)
    if not prod:
        return 0
    return get_available_count(prod["id"]) 


def get_stock_item_at_index(product_id: int, index: int):
    """Pega (sem reservar) o item disponível na posição `index` (0-based), usado para
    navegar 'Anterior/Próximo' entre as contas em estoque de uma categoria."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM stock WHERE product_id = ? AND is_sold = 0 ORDER BY id LIMIT 1 OFFSET ?",
            (product_id, index),
        ).fetchone()


def add_stock_accounts(product_id: int, accounts: list[dict]) -> int:
    """Restock em lote para cartões, com campos opcionais de detalhes e valor."""
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO stock (product_id, login, senha, cartao, cvv, validade, bandeira, nivel, tipo, banco, pais, nome, cpf, valor, perfil) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    product_id,
                    a.get("cartao") or a.get("login"),
                    a.get("cvv") or a.get("senha"),
                    a.get("cartao") or a.get("login"),
                    a.get("cvv") or a.get("senha"),
                    a.get("validade"),
                    a.get("bandeira"),
                    a.get("nivel"),
                    a.get("tipo"),
                    a.get("banco"),
                    a.get("pais"),
                    a.get("nome"),
                    a.get("cpf"),
                    a.get("valor"),
                    a.get("perfil"),
                )
                for a in accounts
            ],
        )
        return len(accounts)


def claim_specific_stock_item(stock_id: int, buyer_id: int):
    """Reserva atomicamente o item específico (o que o cliente estava vendo), só se
    ainda estiver disponível. Retorna None se alguém já comprou ele nesse meio tempo."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE stock SET is_sold = 1, sold_to = ?, sold_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND is_sold = 0",
            (buyer_id, stock_id),
        )
        if cur.rowcount == 0:
            return None
        return conn.execute("SELECT * FROM stock WHERE id = ?", (stock_id,)).fetchone()


def record_purchase(user_id: int, product_id: int, stock_id: int, price: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO purchases (user_id, product_id, stock_id, price) VALUES (?, ?, ?, ?)",
            (user_id, product_id, stock_id, price),
        )


def get_purchases_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM purchases WHERE user_id = ?", (user_id,)).fetchone()
        return row["c"] if row else 0


def get_recharges_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM transactions WHERE user_id = ? AND status = 'PAID_OUT'",
            (user_id,),
        ).fetchone()
        return row["c"] if row else 0


# ---------- Transações Pix ----------

def create_transaction(user_id: int, id_transaction: str, amount: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (user_id, id_transaction, amount, status) VALUES (?, ?, ?, 'WAITING_FOR_APPROVAL')",
            (user_id, id_transaction, amount),
        )


def get_transaction(id_transaction: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE id_transaction = ?", (id_transaction,)
        ).fetchone()


def mark_transaction_paid(id_transaction: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE transactions SET status = 'PAID_OUT' WHERE id_transaction = ?",
            (id_transaction,),
        )
