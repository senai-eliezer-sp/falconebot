import base64
import io
import logging
import os
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import db
import mercadopago_client
from config import (
    BOT_TOKEN,
    BOT_NAME,
    ADMIN_IDS,
    PAYMENT_CHECK_INTERVAL,
    PAYMENT_CHECK_TIMEOUT,
    BANNER_PATH,
    WELCOME_TEXT,
    TERMS_TEXT,
)
from keyboards import (
    main_menu_keyboard,
    back_to_menu_keyboard,
    sellers_keyboard,
    products_keyboard,
    product_browse_keyboard,
    check_payment_keyboard,
    mask_login,
    mask_password,
    mask_card_number,
    mask_person_name,
    mask_cpf,
)
from keyboards import categories_keyboard, admin_stock_keyboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CPF_RE = re.compile(r"^\d{11}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------------------------------------------------------------------------
# Helpers de navegação: cada troca de tela apaga a mensagem anterior e envia
# uma nova, o que permite alternar livremente entre telas com foto (banner)
# e telas de texto simples sem dar erro de edição incompatível no Telegram.
# ---------------------------------------------------------------------------


async def _delete_if_callback(update: Update):
    """Mantém o comportamento sem apagar a mensagem atual para evitar o efeito de piscar."""
    return None


async def render_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard, parse_mode=None):
    if update.callback_query and getattr(update.callback_query, "message", None):
        msg = update.callback_query.message
        try:
            await msg.edit_text(text, reply_markup=keyboard, parse_mode=parse_mode)
            return
        except Exception:
            try:
                await msg.edit_caption(caption=text, reply_markup=keyboard, parse_mode=parse_mode)
                return
            except Exception:
                pass

    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=parse_mode)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.full_name)
    balance = db.get_balance(user.id)
    caption = (
        f"🦅 {BOT_NAME}\n\n"
        f"{WELCOME_TEXT}\n\n"
        f"💰 Saldo Atual: R$ {balance:.2f}\n\n"
        "Escolha uma opção abaixo:"
    )
    chat_id = update.effective_chat.id

    if update.callback_query and getattr(update.callback_query, "message", None):
        msg = update.callback_query.message
        try:
            await msg.edit_text(caption, reply_markup=main_menu_keyboard())
            return
        except Exception:
            try:
                await msg.edit_caption(caption=caption, reply_markup=main_menu_keyboard())
                return
            except Exception:
                pass

    if os.path.exists(BANNER_PATH):
        try:
            with open(BANNER_PATH, "rb") as photo_file:
                await context.bot.send_photo(
                    chat_id, photo=photo_file, caption=caption, reply_markup=main_menu_keyboard()
                )
            return
        except Exception:
            logger.exception("Falha ao enviar banner, caindo para menu em texto")

    await context.bot.send_message(chat_id, caption, reply_markup=main_menu_keyboard())


# ---------------------------------------------------------------------------
# /start e menu principal
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_main_menu(update, context)


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    # Garantir que o usuário exista na base
    user_row = db.get_or_create_user(user.id, user.full_name)

    username = f"@{user.username}" if user.username else "@"
    is_admin_flag = "Sim" if is_admin(user.id) else "Não"
    support_flag = "Não"
    banned_flag = "Não"
    created_at = user_row["created_at"] if user_row else "-"

    wallet_id = str(user.id)
    balance = db.get_balance(user.id)
    cards_bought = db.get_purchases_count(user.id)
    pix_recharges = db.get_recharges_count(user.id)

    text_lines = [
        "Suas Informações",
        "",
        f"📛 Nome: {user.full_name}",
        f"🌐 User: {username}",
        f"👮‍♀️ Admin: {is_admin_flag}",
        f"⛑ Suporte: {support_flag}",
        f"🚫 Banido: {banned_flag}",
        f"📅 Data de cadastro: {created_at}",
        "",
        f"🆔 ID da carteira: {wallet_id}",
        f"💰 Saldo: {balance:.2f}",
        "",
        f"💳 Cartões comprados: {cards_bought}",
        f"💠 Recargas com pix's: {pix_recharges}",
    ]

    await render_text(update, context, "\n".join(text_lines), back_to_menu_keyboard())


async def show_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_text(update, context, TERMS_TEXT, back_to_menu_keyboard())


# ---------------------------------------------------------------------------
# Fluxo: Adicionar Saldo (Mercado Pago Pix)
# ---------------------------------------------------------------------------


async def start_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "amount"
    await render_text(
        update, context, "💳 Digite o valor que deseja adicionar (ex: 20.00):", back_to_menu_keyboard()
    )


async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Valor inválido. Digite um número, ex: 20.00")
        return

    context.user_data["pending_amount"] = amount

    user_row = db.get_or_create_user(update.effective_user.id, update.effective_user.full_name)
    if user_row["email"] and user_row["cpf"]:
        await generate_pix_charge(update, context, amount, user_row["email"], user_row["cpf"])
    else:
        context.user_data["awaiting"] = "email"
        await update.message.reply_text("Para gerar o Pix, preciso do seu e-mail:")


async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("E-mail inválido. Tente novamente:")
        return
    context.user_data["pending_email"] = email
    context.user_data["awaiting"] = "cpf"
    await update.message.reply_text("Agora digite seu CPF (somente números):")


async def handle_cpf_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cpf = re.sub(r"\D", "", update.message.text)
    if not CPF_RE.match(cpf):
        await update.message.reply_text("CPF inválido. Digite os 11 números, sem pontos ou traços:")
        return

    email = context.user_data.pop("pending_email")
    db.set_user_payment_info(update.effective_user.id, email, cpf)
    context.user_data.pop("awaiting", None)

    amount = context.user_data.pop("pending_amount")
    await generate_pix_charge(update, context, amount, email, cpf)


async def generate_pix_charge(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, email: str, cpf: str):
    user = update.effective_user
    chat = update.effective_chat
    msg = await context.bot.send_message(chat.id, "⏳ Gerando cobrança Pix...")

    try:
        resp = await mercadopago_client.create_pix_payment(
            amount=amount,
            email=email,
            cpf=cpf,
            description=f"Adicionar saldo - {BOT_NAME}",
        )
    except Exception as e:
        logger.exception("Erro ao criar pagamento Mercado Pago")
        await msg.edit_text(f"❌ Erro ao gerar o Pix: {e}")
        return

    payment_id = resp.get("id")
    poi = resp.get("point_of_interaction", {}).get("transaction_data", {})
    payment_code = poi.get("qr_code")
    payment_code_b64 = poi.get("qr_code_base64")

    if not payment_id or not payment_code:
        await msg.edit_text(f"❌ Não foi possível gerar o Pix. Resposta: {resp}")
        return

    id_transaction = str(payment_id)
    db.create_transaction(user.id, id_transaction, amount)

    caption = (
        f"💠 Pix gerado — R$ {amount:.2f}\n\n"
        f"Copia e cola:\n`{payment_code}`\n\n"
        "Após pagar, clique no botão abaixo para confirmar."
    )

    await msg.delete()
    if payment_code_b64:
        try:
            image_bytes = base64.b64decode(payment_code_b64)
            await context.bot.send_photo(
                chat.id,
                photo=io.BytesIO(image_bytes),
                caption=caption,
                parse_mode="Markdown",
                reply_markup=check_payment_keyboard(id_transaction),
            )
        except Exception:
            await context.bot.send_message(
                chat.id, caption, parse_mode="Markdown", reply_markup=check_payment_keyboard(id_transaction)
            )
    else:
        await context.bot.send_message(
            chat.id, caption, parse_mode="Markdown", reply_markup=check_payment_keyboard(id_transaction)
        )

    # Agenda verificações automáticas em background, além do botão manual
    context.job_queue.run_repeating(
        auto_check_payment,
        interval=PAYMENT_CHECK_INTERVAL,
        first=PAYMENT_CHECK_INTERVAL,
        last=PAYMENT_CHECK_TIMEOUT,
        data={"id_transaction": id_transaction, "chat_id": chat.id, "user_id": user.id},
        name=f"check_{id_transaction}",
    )


async def _confirm_payment_if_paid(id_transaction: str, user_id: int) -> tuple[bool, float]:
    """Consulta o Mercado Pago; se aprovado e ainda não creditado, credita o saldo. Retorna (pago_agora, valor)."""
    tx = db.get_transaction(id_transaction)
    if tx is None:
        return False, 0.0
    if tx["status"] == "PAID_OUT":
        return False, tx["amount"]  # já tinha sido creditado antes

    status_resp = await mercadopago_client.get_payment_status(id_transaction)
    status = status_resp.get("status", "")
    if status == "approved":
        db.mark_transaction_paid(id_transaction)
        db.add_balance(user_id, tx["amount"])
        return True, tx["amount"]
    return False, tx["amount"]


async def check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    id_transaction = query.data.split("check_", 1)[1]
    user_id = query.from_user.id

    paid_now, amount = await _confirm_payment_if_paid(id_transaction, user_id)
    if paid_now:
        await query.answer("Pagamento confirmado! Saldo adicionado.", show_alert=True)
        balance = db.get_balance(user_id)
        await context.bot.send_message(
            query.message.chat.id,
            f"✅ Pagamento de R$ {amount:.2f} confirmado!\n💰 Novo saldo: R$ {balance:.2f}",
        )
    else:
        tx = db.get_transaction(id_transaction)
        if tx and tx["status"] == "PAID_OUT":
            await query.answer("Esse pagamento já havia sido confirmado.", show_alert=True)
        else:
            await query.answer("Pagamento ainda não identificado. Tente novamente em instantes.", show_alert=True)


async def auto_check_payment(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    id_transaction = data["id_transaction"]
    user_id = data["user_id"]
    chat_id = data["chat_id"]

    paid_now, amount = await _confirm_payment_if_paid(id_transaction, user_id)
    if paid_now:
        balance = db.get_balance(user_id)
        await context.bot.send_message(
            chat_id,
            f"✅ Pagamento de R$ {amount:.2f} confirmado automaticamente!\n💰 Novo saldo: R$ {balance:.2f}",
        )
        context.job.schedule_removal()


# ---------------------------------------------------------------------------
# Fluxo: Compra
# ---------------------------------------------------------------------------


async def show_sellers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_text(update, context, "🛒 Escolha o vendedor:", sellers_keyboard())


async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Mantido para compatibilidade, mas o fluxo principal de vendedor agora usa categorias
    products = db.list_active_products()
    if not products:
        await render_text(update, context, "Nenhum produto disponível no momento.", sellers_keyboard())
        return
    await render_text(update, context, "📦 Produtos disponíveis:", products_keyboard(products))


CATEGORIES = [
    "AMEX",
    "BLACK",
    "BUSINESS",
    "CLASSIC",
    "CORPORATE T&E",
    "ELO",
    "GOLD",
    "GOVERNMENT COMMER",
    "INFINITE",
    "MICRO BUSINESS",
    "MIXED PRODUCT",
    "NUBANK BLACK",
    "NUBANK GOLD",
    "NUBANK MICRO BUSINESS",
    "NUBANK PLATINUM",
    "PERSONAL",
    "PLATINUM",
    "PREPAID",
    "PREPAID CLASSIC",
    "SIGNATURE",
    "STANDARD",
    "WORLD",
]


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe a lista fixa de categorias em duas colunas com quantidades do estoque."""
    cats = []
    for idx, name in enumerate(CATEGORIES):
        qty = db.get_available_count_by_name(name)
        cats.append((idx, name, qty))
    await render_text(update, context, "🛒 Escolha a categoria:", categories_keyboard(cats))


def _extract_stock_fields(item):
    extra = {}
    perf = item.get('perfil') or ''
    for line in (perf or '').splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            extra[k.strip().lower()] = v.strip()

    valor = item.get('valor')
    if valor is None and extra.get('valor'):
        try:
            valor = float(str(extra['valor']).replace(',', '.'))
        except ValueError:
            valor = extra['valor']

    return {
        'cartao': item.get('cartao') or item.get('login') or extra.get('cartao'),
        'cvv': item.get('cvv') or item.get('senha') or extra.get('cvv'),
        'validade': item.get('validade') or extra.get('validade'),
        'bandeira': item.get('bandeira') or extra.get('bandeira'),
        'nivel': item.get('nivel') or extra.get('nivel'),
        'tipo': item.get('tipo') or extra.get('tipo'),
        'banco': item.get('banco') or extra.get('banco'),
        'pais': item.get('pais') or extra.get('pais'),
        'nome': item.get('nome') or extra.get('nome'),
        'cpf': item.get('cpf') or extra.get('cpf'),
        'valor': valor,
    }, extra


async def show_product_browse(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, index: int):
    query = update.callback_query
    product = db.get_product(product_id)
    total = db.get_available_count(product_id)

    if total == 0:
        await query.answer("Produto esgotado no momento.", show_alert=True)
        return

    index = max(0, min(index, total - 1))
    item = db.get_stock_item_at_index(product_id, index)
    if item is None:
        await query.answer("Item não encontrado.", show_alert=True)
        return

    balance = db.get_balance(query.from_user.id)
    stock_data, _ = _extract_stock_fields(item)

    lines = []
    lines.append(f"🔎 Mostrando {index + 1} de {total}")
    lines.append("")
    lines.append("✨ Detalhes do cartão")
    lines.append(f"💳 Cartão: {mask_card_number(stock_data['cartao']) if stock_data.get('cartao') else '—'}")
    if stock_data.get('validade'):
        lines.append(f"📆 Validade: {stock_data['validade']}")
    lines.append(f"🔐 Cvv: {mask_password(stock_data['cvv']) if stock_data.get('cvv') else '***'}")
    lines.append("")
    if stock_data.get('bandeira'):
        lines.append(f"🏳️ Bandeira: {stock_data['bandeira']}")
    if stock_data.get('nivel'):
        lines.append(f"💠 Nível: {stock_data['nivel']}")
    if stock_data.get('tipo'):
        lines.append(f"⚜️ Tipo: {stock_data['tipo']}")
    if stock_data.get('banco'):
        lines.append(f"🏛️ Banco: {stock_data['banco']}")
    if stock_data.get('pais'):
        lines.append(f"🌍 País: {stock_data['pais']}")

    if stock_data.get('nome'):
        lines.append("")
        lines.append("👤Nome:")
        lines.append(mask_person_name(stock_data['nome']))
    if stock_data.get('cpf'):
        lines.append("🪪 cpf:")
        lines.append(mask_cpf(stock_data['cpf']))

    valor = stock_data.get('valor')
    if valor is None:
        valor = product['price']
    lines.append("")
    lines.append(f"💸 Valor: R$ {float(valor):.2f}")
    lines.append(f"💰 Seu saldo: {balance:.2f}")
    lines.append("")
    lines.append("O conteúdo completo (cartão, cvv, nome, cpf) só é liberado após a confirmação da compra e se houver saldo suficiente.")

    text = f"📦 {product['name']}\n\n" + "\n".join(lines)
    await render_text(update, context, text, product_browse_keyboard(product_id, index, total))


async def admin_show_stock_browse(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, index: int):
    query = update.callback_query if update.callback_query else None
    product = db.get_product(product_id)
    if product is None:
        if query:
            await query.answer("Produto não encontrado.", show_alert=True)
        else:
            await update.message.reply_text("Produto não encontrado.")
        return

    total = db.get_available_count(product_id)
    if total == 0:
        if query:
            await query.answer("Nenhum item em estoque para essa categoria.", show_alert=True)
        else:
            await update.message.reply_text("Nenhum item em estoque para essa categoria.")
        return

    index = max(0, min(index, total - 1))
    item = db.get_stock_item_at_index(product_id, index)
    if item is None:
        if query:
            await query.answer("Item não encontrado.", show_alert=True)
        else:
            await update.message.reply_text("Item não encontrado.")
        return

    user_id_for_balance = query.from_user.id if query else update.effective_user.id
    balance = db.get_balance(user_id_for_balance)

    stock_data, _ = _extract_stock_fields(item)

    lines = []
    lines.append(f"🔎 Mostrando {index + 1} de {total}")
    lines.append("")
    lines.append("✨ Detalhes do cartão")
    lines.append(f"💳 Cartão: {mask_card_number(stock_data['cartao']) if stock_data.get('cartao') else '—'}")
    if stock_data.get('validade'):
        lines.append(f"📆 Validade: {stock_data['validade']}")
    lines.append("🔐 Cvv: ***")
    lines.append("")
    if stock_data.get('bandeira'):
        lines.append(f"🏳️ Bandeira: {stock_data['bandeira']}")
    if stock_data.get('nivel'):
        lines.append(f"💠 Nível: {stock_data['nivel']}")
    if stock_data.get('tipo'):
        lines.append(f"⚜️ Tipo: {stock_data['tipo']}")
    if stock_data.get('banco'):
        lines.append(f"🏛️ Banco: {stock_data['banco']}")
    if stock_data.get('pais'):
        lines.append(f"🌍 País: {stock_data['pais']}")

    if stock_data.get('nome'):
        lines.append("")
        lines.append("👤Nome:")
        lines.append(mask_person_name(stock_data['nome']))
    if stock_data.get('cpf'):
        lines.append("🪪 cpf:")
        lines.append(mask_cpf(stock_data['cpf']))

    valor = stock_data.get('valor')
    if valor is None:
        valor = product['price']
    lines.append("")
    lines.append(f"💸 Valor: R$ {float(valor):.2f}")
    lines.append(f"💰 Seu saldo: {balance:.2f}")

    await render_text(update, context, "\n".join(lines), admin_stock_keyboard(product_id, index, total))


async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, product_id_str, index_str = query.data.split("_")
    product_id = int(product_id_str)
    index = int(index_str)
    product = db.get_product(product_id)
    user_id = query.from_user.id

    item = db.get_stock_item_at_index(product_id, index)
    if item is None:
        await query.answer("Esse item não está mais disponível. Escolha outro.", show_alert=True)
        await show_product_browse(update, context, product_id, 0)
        return

    if not db.deduct_balance(user_id, product["price"]):
        await query.answer("Saldo insuficiente. Adicione saldo antes de comprar.", show_alert=True)
        return

    claimed = db.claim_specific_stock_item(item["id"], user_id)
    if claimed is None:
        # Alguém comprou esse item específico entre a navegação e a confirmação -> estorna
        db.add_balance(user_id, product["price"])
        await query.answer("Esse item acabou de ser vendido para outra pessoa. Veja outro.", show_alert=True)
        await show_product_browse(update, context, product_id, 0)
        return

    db.record_purchase(user_id, product_id, claimed["id"], product["price"])
    # Mostrar os dados completos para o comprador
    new_balance = db.get_balance(user_id)
    purchases_count = db.get_purchases_count(user_id)

    stock_data, _ = _extract_stock_fields(claimed)
    lines = [
        f"✅ Compra concluída: {product['name']}",
        "",
        "✨ Detalhes do cartão",
        f"💳 Cartão: {stock_data['cartao'] or '—'}",
    ]
    if stock_data.get('validade'):
        lines.append(f"📆 Validade: {stock_data['validade']}")
    if stock_data.get('cvv'):
        lines.append(f"🔐 Cvv: {stock_data['cvv']}")
    if stock_data.get('bandeira'):
        lines.append(f"🏳️ Bandeira: {stock_data['bandeira']}")
    if stock_data.get('nivel'):
        lines.append(f"💠 Nível: {stock_data['nivel']}")
    if stock_data.get('tipo'):
        lines.append(f"⚜️ Tipo: {stock_data['tipo']}")
    if stock_data.get('banco'):
        lines.append(f"🏛️ Banco: {stock_data['banco']}")
    if stock_data.get('pais'):
        lines.append(f"🌍 País: {stock_data['pais']}")
    if stock_data.get('nome'):
        lines.append("")
        lines.append(f"👤Nome: {stock_data['nome']}")
    if stock_data.get('cpf'):
        lines.append(f"🪪 cpf: {stock_data['cpf']}")

    valor = stock_data.get('valor')
    if valor is None:
        valor = product['price']
    lines.append("")
    lines.append(f"💸 Valor: R$ {float(valor):.2f}")
    lines.append("")
    lines.append(f"💳 Cartões comprados: {purchases_count}")
    lines.append(f"💰 Seu saldo: R$ {new_balance:.2f}")

    await render_text(update, context, "\n".join(lines), back_to_menu_keyboard())


# ---------------------------------------------------------------------------
# Painel administrativo (restock de produtos)
# ---------------------------------------------------------------------------


async def admin_only(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Você não tem permissão para usar este comando.")
        return False
    return True


async def cmd_addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addproduct Nome do Produto | 19.90"""
    if not await admin_only(update):
        return
    try:
        raw = update.message.text.split(" ", 1)[1]
        name, price_str = [p.strip() for p in raw.split("|")]
        price = float(price_str.replace(",", "."))
    except Exception:
        await update.message.reply_text("Uso: /addproduct Nome do Produto | 19.90")
        return

    product_id = db.create_product(name, price)
    await update.message.reply_text(
        f"✅ Categoria criada (ID {product_id}): {name} — R$ {price:.2f}\n"
        f"Use /restock {product_id} e envie os dados do cartão no formato abaixo para adicionar estoque."
    )


async def cmd_restock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/restock <product_id>  -> em seguida o admin envia as contas, em blocos separados
    por linha em branco (pode mandar quantas quiser de uma vez, e repetir o comando
    para adicionar mais depois)."""
    if not await admin_only(update):
        return
    try:
        product_id = int(update.message.text.split(" ", 1)[1].strip())
    except Exception:
        await update.message.reply_text("Uso: /restock <id_da_categoria>")
        return

    product = db.get_product(product_id)
    if product is None:
        await update.message.reply_text("Categoria não encontrada.")
        return

    context.user_data["awaiting"] = "restock_accounts"
    context.user_data["restock_product_id"] = product_id
    await update.message.reply_text(
        f"Envie agora os cartões para '{product['name']}'.\n\n"
        "Um cartão por bloco, separadas por uma linha em branco. Exemplo com 2 cartões:\n\n"
        "cartao: 4111111111111111\n"
        "cvv: 123\n"
        "validade: 12/2028\n"
        "bandeira: Visa\n"
        "nivel: Gold\n"
        "tipo: Crédito\n"
        "banco: Banco do Brasil\n"
        "pais: Brasil\n"
        "nome: João Silva\n"
        "cpf: 12345678900\n"
        "valor: 50.00\n\n"
        "cartao: 5555555555554444\n"
        "cvv: 999\n"
        "validade: 10/2027\n"
        "bandeira: Mastercard\n"
        "nivel: Platinum\n"
        "tipo: Débito\n"
        "banco: Nubank\n"
        "pais: Brasil\n"
        "nome: Maria Souza\n"
        "cpf: 98765432100\n"
        "valor: 70.00\n\n"
        "(todos os campos são opcionais, exceto o cartão e o cvv quando quiserem identificar o item)"
    )


def parse_restock_accounts(raw_text: str):
    """Faz o parse de vários blocos de cartão (separados por linha em branco), cada um
    com campos 'label: valor'. Retorna (contas_validas, quantidade_de_blocos_com_erro)."""
    field_aliases = {
        "cartao": "cartao",
        "cartão": "cartao",
        "card": "cartao",
        "numero": "cartao",
        "numero do cartao": "cartao",
        "cvv": "cvv",
        "cvc": "cvv",
        "validade": "validade",
        "mes/ano": "validade",
        "vencimento": "validade",
        "bandeira": "bandeira",
        "flag": "bandeira",
        "nivel": "nivel",
        "nível": "nivel",
        "tipo": "tipo",
        "banco": "banco",
        "pais": "pais",
        "país": "pais",
        "nome": "nome",
        "name": "nome",
        "cpf": "cpf",
        "valor": "valor",
        "valor do cartao": "valor",
        "preco": "valor",
        "preço": "valor",
        "price": "valor",
        "login": "cartao",
        "email": "cartao",
        "e-mail": "cartao",
        "usuario": "cartao",
        "usuário": "cartao",
        "senha": "cvv",
        "password": "cvv",
        "pass": "cvv",
        "perfil": "perfil",
        "tela": "perfil",
        "pin": "perfil",
    }
    blocks = re.split(r"\n\s*\n", raw_text.strip())
    accounts = []
    error_count = 0
    for block in blocks:
        if not block.strip():
            continue
        fields = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            mapped = field_aliases.get(key.strip().lower())
            if mapped:
                fields[mapped] = value.strip()

        if fields.get("cartao") or fields.get("cvv") or fields.get("validade") or fields.get("bandeira") or fields.get("nivel") or fields.get("tipo") or fields.get("banco") or fields.get("pais") or fields.get("nome") or fields.get("cpf") or fields.get("valor"):
            accounts.append(fields)
        else:
            error_count += 1
    return accounts, error_count


async def handle_restock_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_id = context.user_data.pop("restock_product_id")
    context.user_data.pop("awaiting", None)

    accounts, error_count = parse_restock_accounts(update.message.text)
    inserted = db.add_stock_accounts(product_id, accounts) if accounts else 0
    total = db.get_available_count(product_id)

    msg = f"✅ {inserted} conta(s) adicionada(s). Estoque atual: {total} unidade(s)."
    if error_count:
        msg += f"\n⚠️ {error_count} bloco(s) ignorado(s) por faltar login ou senha."
    await update.message.reply_text(msg)


async def handle_stock_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_name = update.message.text.strip().upper()
    if not category_name:
        await update.message.reply_text("Categoria inválida. Envie o nome da categoria.")
        return

    if category_name not in CATEGORIES:
        await update.message.reply_text(
            "Categoria inválida. Escolha uma das opções abaixo:\n\n"
            + "\n".join(CATEGORIES)
        )
        return

    product = db.get_product_by_name(category_name)
    if product is None:
        product_id = db.create_product(category_name, 0.0)
        product = db.get_product(product_id)

    context.user_data["awaiting"] = "restock_accounts"
    context.user_data["restock_product_id"] = product["id"]
    await update.message.reply_text(
        f"Categoria selecionada: {category_name}.\n\n"
        "Agora envie os dados para adicionar ao estoque.\n\n"
        "Exemplo:\n\n"
        "cartao: 4111111111111111\n"
        "cvv: 123\n"
        "validade: 12/2028\n"
        "bandeira: Visa\n"
        "nivel: Gold\n"
        "tipo: Crédito\n"
        "banco: Banco do Brasil\n"
        "pais: Brasil\n"
        "nome: João Silva\n"
        "cpf: 12345678900\n"
        "valor: 50.00"
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stock -> adiciona estoque em uma categoria, ou navega pelos itens de uma categoria."""
    if not await admin_only(update):
        return

    parts = update.message.text.split()
    if len(parts) >= 2:
        try:
            product_id = int(parts[1])
        except Exception:
            await update.message.reply_text("Uso: /stock ou /stock <id_da_categoria>")
            return
        await admin_show_stock_browse(update, context, product_id, 0)
        return

    context.user_data["awaiting"] = "stock_category_prompt"
    await update.message.reply_text(
        "📦 Para adicionar estoque, envie a categoria desejada.\n\n"
        "Exemplos: AMEX, GOLD, NUBANK BLACK, PLATINUM"
    )


# ---------------------------------------------------------------------------
# Roteador de mensagens de texto (baseado no estado "awaiting")
# ---------------------------------------------------------------------------


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if awaiting == "amount":
        await handle_amount_input(update, context)
    elif awaiting == "email":
        await handle_email_input(update, context)
    elif awaiting == "cpf":
        await handle_cpf_input(update, context)
    elif awaiting == "stock_category_prompt" and is_admin(update.effective_user.id):
        await handle_stock_category_selection(update, context)
    elif awaiting == "restock_accounts" and is_admin(update.effective_user.id):
        await handle_restock_accounts(update, context)


# ---------------------------------------------------------------------------
# Callback router
# ---------------------------------------------------------------------------


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return

    try:
        await query.answer()
    except Exception:
        pass

    user_data = context.user_data
    if user_data.get("_cb_locked"):
        try:
            await query.answer("Aguarde...", show_alert=False)
        except Exception:
            pass
        return

    user_data["_cb_locked"] = True
    try:
        data = query.data
        if data == "menu":
            await send_main_menu(update, context)
        elif data == "terms":
            await show_terms(update, context)
        elif data == "buy":
            await show_sellers(update, context)
        elif data == "seller_admin":
            await show_categories(update, context)
        elif data == "add_balance":
            await start_add_balance(update, context)
        elif data == "wallet":
            await show_wallet(update, context)
        elif data.startswith("product_"):
            product_id = int(data.split("product_", 1)[1])
            await show_product_browse(update, context, product_id, 0)
        elif data.startswith("catidx_"):
            try:
                idx = int(data.split("catidx_", 1)[1])
            except Exception:
                await query.answer("Erro interno.", show_alert=True)
                return
            if idx < 0 or idx >= len(CATEGORIES):
                await query.answer("Categoria inválida.", show_alert=True)
                return
            name = CATEGORIES[idx]
            prod = db.get_product_by_name(name)
            if not prod:
                await render_text(update, context, f"{name} — estoque: 0\n\nNenhum produto cadastrado para essa categoria.", back_to_menu_keyboard())
                return
            await show_product_browse(update, context, prod["id"], 0)
        elif data.startswith("pnav_"):
            _, product_id_str, index_str = data.split("_")
            await show_product_browse(update, context, int(product_id_str), int(index_str))
        elif data.startswith("pnav_admin_"):
            _, product_id_str, index_str = data.split("_")
            await admin_show_stock_browse(update, context, int(product_id_str), int(index_str))
        elif data.startswith("confirm_"):
            await confirm_purchase(update, context)
        elif data.startswith("check_"):
            await check_payment_callback(update, context)
            return
        elif data.startswith("admin_checked_"):
            await query.answer("Marcado como Checado.", show_alert=False)
            return
        elif data.startswith("admin_virgin_"):
            await query.answer("Marcado como Virgem.", show_alert=False)
            return
    finally:
        user_data.pop("_cb_locked", None)


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restock", cmd_restock))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info(f"{BOT_NAME} iniciado.")
    app.run_polling()


if __name__ == "__main__":
    main()
