import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_NAME = os.getenv("BOT_NAME", "VIPFALCONE")

# Payment Gateway
CLIENT_ID = os.getenv("CLIENT_ID", "vxp_3b3ba4815eaaeb55e71ee098")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "vxs_9e58050f86be645e6ce94e7288974380852f99db48287181")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "vwh_a70c9b190e2aaa13b167b759d2274f7e098da223a65ca1c9")
GATEWAY_BASE_URL = os.getenv("GATEWAY_BASE_URL", "https://vexapay.site").rstrip("/")
CHARGES_URL = os.getenv("CHARGES_URL", f"{GATEWAY_BASE_URL}/api/v1/charges")


# Admin
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
ADMIN_DISPLAY_NAME = os.getenv("ADMIN_DISPLAY_NAME", "Admin")

DB_PATH = os.getenv("DB_PATH", "vipfalcone.db")

# Banner exibido no menu principal (imagem local dentro da pasta assets/)
BANNER_PATH = os.getenv("BANNER_PATH", "banner.png")
WELCOME_TEXT = os.getenv(
    "WELCOME_TEXT",
    "Bem-vindo(a) ao nosso bot! Aqui você encontra tudo que precisa, direto por aqui."
)

# Links/textos extras do menu principal (edite depois pelo painel de Variáveis, sem precisar mexer no código)
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/seu_usuario_suporte")
ANNOUNCEMENTS_URL = os.getenv("ANNOUNCEMENTS_URL", "https://t.me/seu_canal_de_avisos")
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/seu_grupo_ou_canal")
TERMS_TEXT = os.getenv(
    "TERMS_TEXT",
    "📄 Termos de Troca\n\n"
    "- Todo produto é verificado antes da entrega.\n"
    "- Problemas com o produto devem ser reportados em até 24h.\n"
    "- Não fazemos reembolso após a entrega do conteúdo completo.\n\n"
    "Edite este texto na variável TERMS_TEXT."
)

# Intervalo (segundos) do polling que verifica se um pagamento Pix já caiu
PAYMENT_CHECK_INTERVAL = 15
# Tempo máximo (segundos) que o bot continua checando um pagamento pendente
PAYMENT_CHECK_TIMEOUT = 60 * 30  # 30 minutos
