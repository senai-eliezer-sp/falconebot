from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import ADMIN_DISPLAY_NAME


def mask_code(code: str) -> str:
    """
    Mascara uma chave/cupom mantendo os primeiros e últimos 2 caracteres de cada
    bloco (separado por - ou espaço), substituindo o meio por *.
    Ex: 'ABCD-1234-EFGH-5678' -> 'AB**-**34-EF**-**78'
    """
    def mask_block(block: str) -> str:
        n = len(block)
        if n <= 4:
            return "*" * n
        return block[:2] + "*" * (n - 4) + block[-2:]

    for sep in ("-", " "):
        if sep in code:
            return sep.join(mask_block(b) for b in code.split(sep))
    return mask_block(code)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Compre Aqui", callback_data="buy")],
            [
                InlineKeyboardButton("💳 Adicione Saldo", callback_data="add_balance"),
                InlineKeyboardButton("👛 Carteira", callback_data="wallet"),
            ],
        ]
    )


def sellers_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"👤 {ADMIN_DISPLAY_NAME}", callback_data="seller_admin")]]
    )


def products_keyboard(products):
    rows = []
    for p in products:
        label = f"{p['name']} — R$ {p['price']:.2f} ({p['qty']} em estoque)"
        rows.append([InlineKeyboardButton(label, callback_data=f"product_{p['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Voltar", callback_data="buy")])
    return InlineKeyboardMarkup(rows)


def product_detail_keyboard(product_id: int):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar Compra", callback_data=f"confirm_{product_id}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="seller_admin")],
        ]
    )


def check_payment_keyboard(id_transaction: str):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Verifiquei o pagamento", callback_data=f"check_{id_transaction}")]]
    )
