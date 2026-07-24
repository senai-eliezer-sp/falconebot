import base64
import io
import logging
import os
import re
import unicodedata

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
import gateway_client
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
        resp = await gateway_client.create_pix_charge(
            amount=amount,
            name=user.full_name or "Cliente",
            cpf=cpf,
            description=f"Adicionar saldo - {BOT_NAME}",
        )
        parsed = gateway_client.parse_charge_response(resp)
    except Exception as e:
        logger.exception("Erro ao criar pagamento no gateway")
        await msg.edit_text(f"❌ Erro ao gerar o Pix: {e}")
        return

    payment_id = parsed["id"]
    payment_code = parsed["pix_code"]
    payment_code_b64 = parsed["qr_code_base64"]

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
    """Consulta o gateway de pagamento; se aprovado e ainda não creditado, credita o saldo. Retorna (pago_agora, valor)."""
    tx = db.get_transaction(id_transaction)
    if tx is None:
        return False, 0.0
    if tx["status"] == "PAID_OUT":
        return False, tx["amount"]  # já tinha sido creditado antes

    try:
        status_resp = await gateway_client.get_charge_status(id_transaction)
        parsed = gateway_client.parse_charge_response(status_resp)
        status = parsed["status"]
        if status in ["APPROVED", "PAID", "COMPLETED", "RECEIVED", "SETTLED", "SUCCESS"]:
            db.mark_transaction_paid(id_transaction)
            db.add_balance(user_id, tx["amount"])
            return True, tx["amount"]
    except Exception as e:
        logger.warning(f"Erro ao verificar status da transação {id_transaction}: {e}")
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

CATEGORY_RULES = {
    "MICRO BUSINESS": {
        "bandeira": "mastercard",
        "nivel": "micro business",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 45.00,
        "bins": {
            "233026": {"banco": "banco inter, s.a."},
            "250031": {"banco": "banco inter, s.a."},
        },
    },
    "MIXED PRODUCT": {
        "bandeira": "mastercard",
        "nivel": "mixed product",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 75.00,
        "bins": {
            "539090": {"banco": "itau unibanco, s.a."},
        },
    },
    "NUBANK BLACK": {
        "bandeira": "mastercard",
        "nivel": "nubank black",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 130.00,
        "bins": {
            "520048": {"banco": "nu pagamentos sa"},
        },
    },
    "NUBANK GOLD": {
        "bandeira": "mastercard",
        "nivel": "nubank gold",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 30.00,
        "bins": {
            "550209": {"banco": "nu pagamentos sa"},
        },
    },
    "NUBANK PLATINUM": {
        "bandeira": "mastercard",
        "nivel": "nubank platinum",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 35.00,
        "bins": {
            "516292": {"banco": "nu pagamentos sa"},
        },
    },
    "AMEX": {
        "bandeira": "american express",
        "nivel": "amex",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 25.00,
        "bins": {
            "374769": {"banco": "banco bradesco"},
            "374768": {"banco": "banco bradesco"},
            "377169": {"banco": "banco bradesco"},
            "376522": {"banco": "banco bradesco"},
        },
    },
    "BLACK": {
        "bandeira": "mastercard",
        "nivel": "black",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 50.00,
        "bins": {
            "523431": {"banco": "itau unibanco, s.a."},
            "553665": {"banco": "itau unibanco, s.a."},
            "559337": {"banco": "itau unibanco, s.a."},
            "512215": {"banco": "itau unibanco, s.a."},
            "543960": {"banco": "itau unibanco, s.a."},
            "531249": {"banco": "itau unibanco, s.a."},
            "553636": {"banco": "itau unibanco, s.a."},
            "522840": {"banco": "banco santander (brasil), s.a."},
            "548083": {"banco": "banco santander (brasil), s.a."},
            "534696": {"banco": "banco c6 sa"},
            "554762": {"banco": "banco c6 sa"},
            "538111": {"banco": "banco cooperativo sicredi sa"},
            "512267": {"banco": "banco cooperativo sicredi sa"},
        },
    },
    "BUSINESS": {
        "bandeira": "visa",
        "nivel": "business",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 60.00,
        "bins": {
            "424032": {"banco": "sutton bank", "pais": "united states"},
            "499817": {"banco": "cora sociedade de credito direto, s.a."},
            "498448": {"banco": "neon pagamentos, s.a."},
            "485619": {"banco": "neon pagamentos, s.a."},
            "480632": {"banco": "banco bradesco, s.a."},
            "477587": {"banco": "stone cartoes instituicao de pagamento, s.a."},
            "496045": {"banco": "banco cooperativo sicredi, s.a."},
            "466197": {"banco": "banco cooperativo sicredi, s.a."},
            "433178": {"banco": "pagseguro internet s.a"},
            "489414": {"banco": "pagseguro internet s.a"},
        },
    },
    "CORPORATE T&E": {
        "bandeira": "visa",
        "nivel": "corporate t&e",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 55.00,
        "bins": {
            "433876": {"banco": "biz instituicao de pagamento ltda."},
        },
    },
    "ELO": {
        "bandeira": "elo",
        "nivel": "elo",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 40.00,
        "bins": {
            "506741": {"banco": "caixa economica federal"},
            "650507": {"banco": "caixa economica federal"},
            "650512": {"banco": "caixa economica federal"},
            "655000": {"banco": "banco bradesco sa"},
            "650485": {"banco": "banco bradesco sa"},
            "650486": {"banco": "banco bradesco sa"},
            "650569": {"banco": "banco pan sa"},
            "650952": {"banco": "banco arbi sa"},
            "655036": {"banco": "pernambucanas financiadora sa cred fin e investimento"},
        },
    },
    "GOLD": {
        "bandeira": "visa",
        "nivel": "gold",
        "tipo": "credit",
        "pais": "brazil",
        "valor": 35.00,
        "bins": {
            "410863": {"banco": "banco santander, s.a."},
            "548514": {"banco": "itau unibanco, s.a."},
            "549202": {"banco": "itau unibanco, s.a."},
            "516306": {"banco": "itau unibanco, s.a."},
            "530994": {"banco": "itau unibanco, s.a."},
            "498407": {"banco": "banco do brasil, s.a."},
            "555507": {"banco": "banco inter, s.a."},
            "478307": {"banco": "itau unibanco holding, s.a."},
            "459078": {"banco": "itau unibanco holding, s.a."},
            "543966": {"banco": "banco votorantim s/a"},
            "407843": {"banco": "mercado pago instituicao de pagamento ltda."},
            "459384": {"banco": "caixa economica federal"},
            "455184": {"banco": "banco bradesco, s.a."},
        },
    },
}

BIN_CATEGORY_RULES = {}
for category, config in CATEGORY_RULES.items():
    for bin_prefix, bank_config in config["bins"].items():
        bank_name = bank_config.get("banco", "")
        pais = bank_config.get("pais", config["pais"])
        BIN_CATEGORY_RULES[bin_prefix] = {
            "category": category,
            "bandeira": config["bandeira"],
            "nivel": config["nivel"],
            "tipo": config["tipo"],
            "banco": bank_name,
            "pais": pais,
            "valor": config["valor"],
        }

DEFAULT_CATEGORY_PRICES = {
    category: config["valor"] for category, config in CATEGORY_RULES.items()
}


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe a lista fixa de categorias em duas colunas com quantidades do estoque."""
    cats = []
    for idx, name in enumerate(CATEGORIES):
        qty = db.get_available_count_by_name(name)
        cats.append((idx, name, qty))
    await render_text(update, context, "🛒 Escolha a categoria:", categories_keyboard(cats))


def _extract_stock_fields(item):
    if item is None:
        return {}, {}
    if not isinstance(item, dict):
        item = dict(item)

    extra = {}
    perf = item.get('perfil') or ''
    for line in (perf or '').splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            extra[k.strip().lower()] = v.strip()

    raw_card = str(item.get('cartao') or item.get('login') or extra.get('cartao') or '').strip()
    raw_cvv = str(item.get('cvv') or item.get('senha') or extra.get('cvv') or '').strip()
    raw_val = str(item.get('validade') or extra.get('validade') or '').strip()

    card_num = raw_card
    if '|' in raw_card or '/' in raw_card or ';' in raw_card:
        pipe_match = re.search(r"(\d{13,19})\s*[|/;:]\s*(\d{1,2})\s*[|/;:]\s*(\d{2,4})\s*[|/;:]\s*(\d{3})\b", raw_card)
        if pipe_match:
            card_num = pipe_match.group(1)
            if not raw_val:
                raw_val = f"{pipe_match.group(2)}/{pipe_match.group(3)}"
            if not raw_cvv:
                raw_cvv = pipe_match.group(4)
        else:
            card_match = re.search(r"(\d{13,19})", raw_card)
            if card_match:
                card_num = card_match.group(1)

    # CVV deve ter estritamente 3 dígitos
    cvv_clean = re.search(r"\b(\d{3})\b", raw_cvv)
    cvv_val = cvv_clean.group(1) if cvv_clean else (raw_cvv[:3] if len(raw_cvv) >= 3 else raw_cvv)

    raw_nome = item.get('nome') or extra.get('nome') or ''
    raw_cpf = item.get('cpf') or extra.get('cpf') or ''

    # Remove SCORE e sujeiras ao final do campo
    raw_nome = re.sub(r"(?:[|/-]?\s*SCORE\s*[:=]?\s*\d+)", "", str(raw_nome), flags=re.IGNORECASE).strip()
    raw_cpf = re.sub(r"(?:[|/-]?\s*SCORE\s*[:=]?\s*\d+)", "", str(raw_cpf), flags=re.IGNORECASE).strip()

    # Se o CPF estiver em branco mas o nome contiver um CPF de 11 dígitos:
    cpf_val = raw_cpf
    if not cpf_val:
        cpf_found = re.search(r"\b(\d{11})\b|\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b", raw_nome)
        if cpf_found:
            cpf_val = re.sub(r"\D", "", cpf_found.group(0))

    # Limpa o CPF e prefixos do campo Nome para não ficarem misturados
    nome_val = raw_nome
    if cpf_val and cpf_val in nome_val:
        nome_val = nome_val.replace(cpf_val, "")
    nome_val = re.sub(r"\b\d{11}\b", "", nome_val)
    nome_val = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "", nome_val)
    nome_val = re.sub(r"^(?:NOME|CPF)\s*[:=]?", "", nome_val, flags=re.IGNORECASE)
    nome_val = _clean_text(re.sub(r"[|/-]+$", "", nome_val).strip())

    valor = item.get('valor')
    if valor is None and extra.get('valor'):
        try:
            valor = float(str(extra['valor']).replace(',', '.'))
        except ValueError:
            valor = extra['valor']

    bin_prefix = card_num[:6] if card_num and len(card_num) >= 6 else ""
    rule = BIN_CATEGORY_RULES.get(bin_prefix, {})

    bandeira = item.get('bandeira') or extra.get('bandeira') or rule.get('bandeira') or ''
    nivel = item.get('nivel') or extra.get('nivel') or rule.get('nivel') or ''
    tipo = item.get('tipo') or extra.get('tipo') or rule.get('tipo') or ''
    banco = item.get('banco') or extra.get('banco') or rule.get('banco') or ''
    pais = item.get('pais') or extra.get('pais') or rule.get('pais') or ''

    return {
        'cartao': card_num,
        'cvv': cvv_val,
        'validade': raw_val,
        'bandeira': bandeira,
        'nivel': nivel,
        'tipo': tipo,
        'banco': banco,
        'pais': pais,
        'nome': nome_val,
        'cpf': cpf_val,
        'valor': valor,
    }, extra



async def show_product_browse(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, index: int):
    query = update.callback_query
    product = db.get_product(product_id)
    if product is None:
        await render_text(update, context, "⚠️ Produto não encontrado.", back_to_menu_keyboard())
        return

    total = db.get_available_count(product_id)

    if total == 0:
        await render_text(
            update,
            context,
            f"📦 {product['name']}\n\n⚠️ Este produto está esgotado no momento.",
            back_to_menu_keyboard(),
        )
        return

    index = max(0, min(index, total - 1))
    item = db.get_stock_item_at_index(product_id, index)
    if item is None:
        await render_text(update, context, "⚠️ Item de estoque não encontrado.", back_to_menu_keyboard())
        return

    balance = db.get_balance(query.from_user.id)
    stock_data, _ = _extract_stock_fields(item)

    lines = []
    lines.append(f"🔎 Mostrando {index + 1} de {total}")
    lines.append("")
    lines.append(f"💳 Cartão: {mask_card_number(stock_data['cartao']) if stock_data.get('cartao') else '—'}")
    lines.append(f"📆 Validade: {stock_data['validade'] if stock_data.get('validade') else '—'}")
    lines.append(f"🔐 Cvv: {mask_password(stock_data['cvv']) if stock_data.get('cvv') else '***'}")
    lines.append("")
    lines.append(f"🏳️ Bandeira: {stock_data['bandeira'] if stock_data.get('bandeira') else '—'}")
    lines.append(f"💠 Nível: {stock_data['nivel'] if stock_data.get('nivel') else '—'}")
    lines.append(f"⚜️ Tipo: {stock_data['tipo'] if stock_data.get('tipo') else '—'}")
    lines.append(f"🏛️ Banco: {stock_data['banco'] if stock_data.get('banco') else '—'}")
    lines.append(f"🌍 Pais: {stock_data['pais'] if stock_data.get('pais') else '—'}")
    lines.append("")
    lines.append("👤Nome:")
    lines.append(mask_person_name(stock_data['nome']) if stock_data.get('nome') else '—')
    lines.append("")
    lines.append("🪪 cpf:")
    lines.append(mask_cpf(stock_data['cpf']) if stock_data.get('cpf') else '—')

    valor = stock_data.get('valor')
    if valor is None or str(valor).strip() == "":
        valor = product['price']

    try:
        price_val = float(str(valor).replace(",", "."))
    except (ValueError, TypeError):
        price_val = 0.0

    lines.append("")
    lines.append(f"💰 Valor: R$ {price_val:.2f}")
    lines.append(f"💰 Seu saldo: R$ {balance:.2f}")
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
    lines.append(f"💳 Cartão: {mask_card_number(stock_data['cartao']) if stock_data.get('cartao') else '—'}")
    lines.append(f"📆 Validade: {stock_data['validade'] if stock_data.get('validade') else '—'}")
    lines.append("🔐 Cvv: ***")
    lines.append("")
    lines.append(f"🏳️ Bandeira: {stock_data['bandeira'] if stock_data.get('bandeira') else '—'}")
    lines.append(f"💠 Nível: {stock_data['nivel'] if stock_data.get('nivel') else '—'}")
    lines.append(f"⚜️ Tipo: {stock_data['tipo'] if stock_data.get('tipo') else '—'}")
    lines.append(f"🏛️ Banco: {stock_data['banco'] if stock_data.get('banco') else '—'}")
    lines.append(f"🌍 Pais: {stock_data['pais'] if stock_data.get('pais') else '—'}")
    lines.append("")
    lines.append("👤Nome:")
    lines.append(mask_person_name(stock_data['nome']) if stock_data.get('nome') else '—')
    lines.append("")
    lines.append("🪪 cpf:")
    lines.append(mask_cpf(stock_data['cpf']) if stock_data.get('cpf') else '—')

    valor = stock_data.get('valor')
    if valor is None:
        valor = product['price']
    try:
        price_val = float(str(valor).replace(",", "."))
    except (ValueError, TypeError):
        price_val = 0.0

    lines.append("")
    lines.append(f"💰 Valor: R$ {price_val:.2f}")
    lines.append(f"💰 Seu saldo: R$ {balance:.2f}")

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

    stock_data, _ = _extract_stock_fields(item)
    valor = stock_data.get('valor')
    if valor is None or str(valor).strip() == "":
        valor = product['price']

    try:
        price_val = float(str(valor).replace(",", "."))
    except (ValueError, TypeError):
        price_val = float(product['price'])

    if price_val <= 0:
        price_val = float(product['price'])

    if not db.deduct_balance(user_id, price_val):
        await query.answer("Saldo insuficiente. Adicione saldo antes de comprar.", show_alert=True)
        return

    claimed = db.claim_specific_stock_item(item["id"], user_id)
    if claimed is None:
        # Alguém comprou esse item específico entre a navegação e a confirmação -> estorna
        db.add_balance(user_id, price_val)
        await query.answer("Esse item acabou de ser vendido para outra pessoa. Veja outro.", show_alert=True)
        await show_product_browse(update, context, product_id, 0)
        return

    db.record_purchase(user_id, product_id, claimed["id"], price_val)
    # Mostrar os dados completos para o comprador
    new_balance = db.get_balance(user_id)
    purchases_count = db.get_purchases_count(user_id)

    stock_data, _ = _extract_stock_fields(claimed)
    lines = [
        f"✅ Compra concluída: {product['name']}",
        "",
        f"💳 Cartão: {stock_data['cartao'] or '—'}",
        f"📆 Validade: {stock_data['validade'] or '—'}",
        f"🔐 Cvv: {stock_data['cvv'] or '—'}",
        "",
        f"🏳️ Bandeira: {stock_data['bandeira'] or '—'}",
        f"💠 Nível: {stock_data['nivel'] or '—'}",
        f"⚜️ Tipo: {stock_data['tipo'] or '—'}",
        f"🏛️ Banco: {stock_data['banco'] or '—'}",
        f"🌍 Pais: {stock_data['pais'] or '—'}",
        "",
        "👤Nome:",
        f"{stock_data['nome'] or '—'}",
        "",
        "🪪 cpf:",
        f"{stock_data['cpf'] or '—'}",
        "",
        f"💰 Valor: R$ {price_val:.2f}",
        "",
        f"💳 Cartões comprados: {purchases_count}",
        f"💰 Seu saldo: R$ {new_balance:.2f}",
    ]

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

    text = update.message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("Uso: /restock <id_da_categoria> ou envie o bloco de dados diretamente.")
        return

    payload = parts[1].strip()
    if payload.isdigit():
        product_id = int(payload)
        product = db.get_product(product_id)
        if product is None:
            await update.message.reply_text("Categoria não encontrada.")
            return

        context.user_data["awaiting"] = "restock_accounts"
        context.user_data["restock_product_id"] = product_id
        await update.message.reply_text(
            f"Envie agora os cartões para '{product['name']}'.\n\n"
            "Você também pode colar o bloco de dados diretamente no comando e ele será processado automaticamente."
        )
        return

    await handle_restock_accounts(update, context, payload=payload)


def _clean_text(value: str) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    if not cleaned:
        return ""
    if cleaned.upper() in {"NULL", "NONE", "NIL", "-", "—"}:
        return ""
    return " ".join(cleaned.split())


def _parse_restock_block(block_text: str) -> dict | None:
    text = _clean_text(block_text)
    if not text:
        return None

    # Strip SCORE from the block text if present (e.g. SCORE: 800, SCORE 850, |SCORE: 700)
    text = re.sub(r"(?:[|/-]?\s*SCORE\s*[:=]?\s*\d+)", "", text, flags=re.IGNORECASE).strip()

    card = ""
    month = ""
    year = ""
    cvv = ""

    # Match de padrão pipe/barra/espaco: cartao|mm|aa|cvv ou cartao|mm|aaaa|cvv
    # CVV estritamente 3 dígitos (\d{3})
    pipe_match = re.search(r"(\d{13,19})\s*[|/;:]\s*(\d{1,2})\s*[|/;:]\s*(\d{2,4})\s*[|/;:]\s*(\d{3})\b", text)
    if pipe_match:
        card = pipe_match.group(1)
        month = pipe_match.group(2)
        year = pipe_match.group(3)
        cvv = pipe_match.group(4)
        rest = text[pipe_match.end():].strip()
    else:
        # Busca o número do cartão (13 a 19 dígitos)
        card_match = re.search(r"(\d{13,19})", text)
        if not card_match:
            return None
        card = card_match.group(1)
        rest = text.replace(card, "", 1).strip()

        val_match = re.search(r"\b(0[1-9]|1[0-2])\s*[/|-]\s*(20\d{2}|\d{2})\b", text)
        if val_match:
            month = val_match.group(1)
            year = val_match.group(2)

        cvv_match = re.search(r"(?:cvv|cvc)\s*[:=]?\s*(\d{3})\b", text, flags=re.IGNORECASE) or re.search(r"\b(\d{3})\b", rest)
        if cvv_match:
            cvv = cvv_match.group(1)

    name = ""
    cpf = ""
    celular = ""
    email = ""

    # 1. Busca por rotuladores explícitos (NOME:, CPF:, CELULAR:, EMAIL:)
    for key, value in re.findall(
        r"(NOME|CPF|CELULAR|EMAIL)\s*:\s*(.+?)(?=(?:\s*-\s*(?:NOME|CPF|CELULAR|EMAIL):)|\s*\||$)",
        rest,
        flags=re.IGNORECASE,
    ):
        normalized_key = key.strip().lower()
        cleaned_value = _clean_text(value)
        if normalized_key == "nome":
            name = cleaned_value
        elif normalized_key == "cpf":
            cpf = cleaned_value
        elif normalized_key == "celular":
            celular = cleaned_value
        elif normalized_key == "email":
            email = cleaned_value

    # 2. Se CPF não foi capturado via rótulo "CPF:", busca 11 dígitos numéricos isolados
    if not cpf:
        cpf_match = re.search(r"\b(\d{11})\b|\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b", rest)
        if cpf_match:
            cpf = re.sub(r"\D", "", cpf_match.group(0))

    # 3. Se NOME não foi capturado via rótulo "NOME:", isola o nome do restante do texto
    if not name:
        clean_rest = rest
        if cpf:
            clean_rest = clean_rest.replace(cpf, "")
            clean_rest = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "", clean_rest)
        clean_rest = re.sub(r"(?:NOME|CPF|CELULAR|EMAIL|SCORE)\s*[:=]?", "", clean_rest, flags=re.IGNORECASE)
        parts = [p.strip() for p in re.split(r"[|/-]", clean_rest) if p.strip()]
        for p in parts:
            if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", p):
                name = _clean_text(p)
                break

    # Garante a separação estrita de Nome e CPF
    if name and cpf and cpf in name:
        name = _clean_text(name.replace(cpf, ""))
    if name:
        name = re.sub(r"\b\d{11}\b", "", name).strip()
        name = _clean_text(re.sub(r"[|/-]+$", "", name).strip())

    validade = f"{month}/{year}" if month and year else ""
    bin_prefix = card[:6]
    rule = BIN_CATEGORY_RULES.get(bin_prefix)

    category = (rule or {}).get("category", "UNIDENTIFIED")
    account = {
        "cartao": card,
        "cvv": cvv,
        "validade": validade,
        "bandeira": (rule or {}).get("bandeira", ""),
        "nivel": (rule or {}).get("nivel", ""),
        "tipo": (rule or {}).get("tipo", ""),
        "banco": (rule or {}).get("banco", ""),
        "pais": (rule or {}).get("pais", ""),
        "nome": name,
        "cpf": cpf,
        "valor": (rule or {}).get("valor"),
        "perfil": "\n".join(
            [
                f"celular: {celular}" if celular else "",
                f"email: {email}" if email else "",
            ]
        ).strip(),
        "category": category,
    }
    return account


def parse_restock_accounts(raw_text: str):
    """
    Faz o parse de múltiplos blocos/linhas de cartão enviados de uma só vez.
    Garante que CADA linha ou bloco contendo um cartão (13 a 19 dígitos)
    seja processado individualmente, verificando os 6 primeiros dígitos (BIN).
    """
    lines = raw_text.strip().splitlines()
    blocks = []
    current_block = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_block:
                blocks.append("\n".join(current_block))
                current_block = []
            continue

        # Se a linha contém um cartão (13 a 19 dígitos)
        has_card = bool(re.search(r"\b\d{13,19}\b", stripped) or re.search(r"\d{13,19}", stripped))
        if has_card and current_block:
            blocks.append("\n".join(current_block))
            current_block = [stripped]
        else:
            current_block.append(stripped)

    if current_block:
        blocks.append("\n".join(current_block))

    accounts = []
    error_count = 0
    for block in blocks:
        if not block.strip():
            continue
        account = _parse_restock_block(block)
        if account:
            accounts.append(account)
        else:
            error_count += 1
    return accounts, error_count


async def handle_restock_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str | None = None):
    context.user_data.pop("awaiting", None)

    raw_text = payload if payload is not None else update.message.text

    try:
        accounts, error_count = parse_restock_accounts(raw_text)
        if not accounts:
            await update.message.reply_text("❌ Nenhum bloco de dados reconhecido para processar.")
            return

        grouped_accounts = {}
        selected_product_id = context.user_data.get("restock_product_id")
        selected_product = db.get_product(selected_product_id) if selected_product_id else None
        selected_category_name = selected_product["name"] if selected_product else None

        for account in accounts:
            category_name = account.get("category") or "UNIDENTIFIED"
            if category_name == "UNIDENTIFIED":
                category_name = selected_category_name or "STANDARD"
            account["category"] = category_name
            grouped_accounts.setdefault(category_name, []).append(account)

        inserted_total = 0
        inserted_categories = []
        for category_name, category_accounts in grouped_accounts.items():
            product = db.get_product_by_name(category_name)
            if product is None:
                price = DEFAULT_CATEGORY_PRICES.get(category_name, 0.0)
                product_id = db.create_product(category_name, price)
            else:
                product_id = product["id"]

            db.add_stock_accounts(product_id, category_accounts)
            inserted_total += len(category_accounts)
            inserted_categories.append(f"{category_name} ({len(category_accounts)})")

        total_message = ", ".join(inserted_categories) if inserted_categories else "nenhuma categoria identificada"
        msg = f"✅ {inserted_total} conta(s) adicionada(s) automaticamente. Categorias: {total_message}."
        if error_count:
            msg += f"\n⚠️ {error_count} bloco(s) ignorado(s) por não conter dados reconhecíveis."
        await update.message.reply_text(msg)
    except Exception as exc:
        logger.exception("Falha ao salvar estoque via /stock")
        await update.message.reply_text(f"❌ Não foi possível salvar o estoque: {exc}")


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
        price = DEFAULT_CATEGORY_PRICES.get(category_name, 0.0)
        product_id = db.create_product(category_name, price)
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
    """/stock -> processa automaticamente os blocos enviados e distribui por categoria com base no BIN."""
    if not await admin_only(update):
        return

    text = update.message.text.strip()
    parts = text.split(None, 1)
    if len(parts) >= 2:
        payload = parts[1].strip()
        await handle_restock_accounts(update, context, payload=payload)
        return

    context.user_data["awaiting"] = "restock_accounts"
    await update.message.reply_text(
        "📦 Envie os blocos de dados para processamento automático.\n\n"
        "O bot vai ler os 6 primeiros números do cartão, identificar a categoria correspondente e organizar os dados automaticamente.\n\n"
        "Exemplo de entrada:\n"
        "5526933079536203|07|2028|210 NOME: Isadora Kiebler - CPF: 12205144979 - CELULAR: +5547992534296 - EMAIL: isadorakieber@hotmail.com"
    )


# ---------------------------------------------------------------------------
# Handler de arquivo .txt para restock
# ---------------------------------------------------------------------------


async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe um arquivo .txt enviado pelo admin e processa os cartões automaticamente."""
    if not is_admin(update.effective_user.id):
        return

    doc = update.message.document
    file_name = doc.file_name or ""

    if not file_name.lower().endswith(".txt"):
        await update.message.reply_text("⚠️ Apenas arquivos .txt são aceitos.")
        return

    await update.message.reply_text("⏳ Lendo arquivo, aguarde...")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = await tg_file.download_as_bytearray()
        raw_text = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.exception("Erro ao baixar arquivo .txt")
        await update.message.reply_text(f"❌ Não foi possível ler o arquivo: {exc}")
        return

    if not raw_text.strip():
        await update.message.reply_text("❌ O arquivo está vazio.")
        return

    await handle_restock_accounts(update, context, payload=raw_text)


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
        elif data.startswith("pnav_admin_"):
            parts = data.split("_")
            if len(parts) >= 4:
                product_id = int(parts[2])
                index = int(parts[3])
                await admin_show_stock_browse(update, context, product_id, index)
        elif data.startswith("pnav_"):
            parts = data.split("_")
            if len(parts) >= 3:
                product_id = int(parts[1])
                index = int(parts[2])
                await show_product_browse(update, context, product_id, index)
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
    except Exception as exc:
        logger.exception(f"Erro no callback_router: {exc}")
        try:
            await query.answer("Ocorreu um erro ao processar. Tente novamente.", show_alert=True)
        except Exception:
            pass
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
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_txt_file))

    logger.info(f"{BOT_NAME} iniciado.")
    app.run_polling()


if __name__ == "__main__":
    main()
