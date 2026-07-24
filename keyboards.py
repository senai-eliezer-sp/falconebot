from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import ADMIN_DISPLAY_NAME, SUPPORT_URL, ANNOUNCEMENTS_URL, GROUP_URL


def mask_login(login: str) -> str:
    """
    Mascara um login/e-mail mantendo os 2 primeiros caracteres de cada parte visíveis.
    Ex: 'joaozinho@gmail.com' -> 'jo*******@gm***.com'
    """
    if not login:
        return ""
    if "@" in login:
        user, domain = login.split("@", 1)
        user_masked = user[:2] + "*" * max(len(user) - 2, 1)
        if "." in domain:
            dom_name, dom_ext = domain.rsplit(".", 1)
            dom_masked = dom_name[:2] + "*" * max(len(dom_name) - 2, 1)
            return f"{user_masked}@{dom_masked}.{dom_ext}"
        return f"{user_masked}@{'*' * len(domain)}"
    n = len(login)
    if n <= 4:
        return "*" * n
    return login[:2] + "*" * (n - 4) + login[-2:]


def mask_password(_senha: str) -> str:
    """A senha nunca é mostrada antes da compra, só um placeholder fixo."""
    return "********"


def mask_card_number(card: str) -> str:
    """Mostra os 6 primeiros dígitos e mascara o restante com '*'."""
    if not card:
        return ""
    s = ''.join(ch for ch in card if ch.isdigit())
    if len(s) <= 6:
        return s + '*' * max(0, 6 - len(s))
    return s[:6] + '*' * (len(s) - 6)


def mask_person_name(name: str) -> str:
    """Exibe apenas caracteres em posições pares, mascarando os demais com '*', preservando espaços."""
    if not name:
        return ""
    out = []
    for i, ch in enumerate(name):
        if ch.isspace():
            out.append(ch)
        else:
            out.append(ch if i % 2 == 0 else '*')
    return ''.join(out)


def mask_cpf(cpf: str) -> str:
    """Mascara um CPF mostrando apenas os 3 últimos dígitos."""
    if not cpf:
        return ""
    s = ''.join(ch for ch in cpf if ch.isdigit())
    if len(s) <= 3:
        return '*' * len(s)
    return '*' * (len(s) - 3) + s[-3:]


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Compre Aqui", callback_data="buy")],
            [
                InlineKeyboardButton("💠 Adicione Saldo", callback_data="add_balance"),
                InlineKeyboardButton("🗂️ Carteira", callback_data="wallet"),
            ],
            [
                InlineKeyboardButton("💬 Grupo/Comunidade", url=GROUP_URL),
                InlineKeyboardButton("📢 Canal de Avisos", url=ANNOUNCEMENTS_URL),
            ],
            [
                InlineKeyboardButton("⚠️ Suporte/Atendimento", url=SUPPORT_URL),
                InlineKeyboardButton("📄 Termos de Troca", callback_data="terms"),
            ],
        ]
    )


def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Menu Principal", callback_data="menu")]]
    )


def sellers_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"👤 {ADMIN_DISPLAY_NAME}", callback_data="seller_admin")],
            [InlineKeyboardButton("⬅️ Menu Principal", callback_data="menu")],
        ]
    )


def products_keyboard(products):
    rows = []
    for p in products:
        label = f"{p['name']} — R$ {p['price']:.2f} ({p['qty']} em estoque)"
        rows.append([InlineKeyboardButton(label, callback_data=f"product_{p['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="buy")])
    rows.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def product_browse_keyboard(product_id: int, index: int, total: int):
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"pnav_{product_id}_{index - 1}"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton("➡️ Próximo", callback_data=f"pnav_{product_id}_{index + 1}"))

    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("✅ Confirmar Compra", callback_data=f"confirm_{product_id}_{index}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="seller_admin")])
    rows.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def check_payment_keyboard(id_transaction: str):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Verifiquei o pagamento", callback_data=f"check_{id_transaction}")]]
    )


def categories_keyboard(categories):
    """Cria um teclado com categorias em duas colunas. `categories` é uma lista de
    tuples (index, name, qty). Cada botão tem callback_data 'catidx_<index>'."""
    rows = []
    # Agrupa de 2 em 2
    for i in range(0, len(categories), 2):
        row = []
        for j in range(i, min(i + 2, len(categories))):
            idx, name, qty = categories[j]
            label = f"{name} ({qty})"
            row.append(InlineKeyboardButton(label, callback_data=f"catidx_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="buy")])
    rows.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def admin_stock_keyboard(product_id: int, index: int, total: int):
    """Teclado administrativo simplificado:
    - Linha de compra (acima das setas)
    - Linha de navegação com setas (<<, >>)
    - Linhas inferiores: Voltar, Menu
    """
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton("<<", callback_data=f"pnav_admin_{product_id}_{index - 1}"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton(">>", callback_data=f"pnav_admin_{product_id}_{index + 1}"))

    rows = []
    # Botão de compra acima das setas
    rows.append([InlineKeyboardButton("✅ Comprar", callback_data=f"confirm_{product_id}_{index}")])
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="seller_admin")])
    rows.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="menu")])
    return InlineKeyboardMarkup(rows)
