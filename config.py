import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_NAME = os.getenv("BOT_NAME", "VIPFALCONE")

# Mercado Pago
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
MP_PAYMENTS_URL = "https://api.mercadopago.com/v1/payments"

# Admin
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
ADMIN_DISPLAY_NAME = os.getenv("ADMIN_DISPLAY_NAME", "Admin")

DB_PATH = os.getenv("DB_PATH", "vipfalcone.db")

# Intervalo (segundos) do polling que verifica se um pagamento Pix já caiu
PAYMENT_CHECK_INTERVAL = 15
# Tempo máximo (segundos) que o bot continua checando um pagamento pendente
PAYMENT_CHECK_TIMEOUT = 60 * 30  # 30 minutos
