import uuid
import httpx

from config import MP_ACCESS_TOKEN, MP_PAYMENTS_URL


def _headers(idempotency_key: str):
    return {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": idempotency_key,
    }


async def create_pix_payment(amount: float, email: str, cpf: str, description: str):
    """
    Cria um pagamento Pix no Mercado Pago.
    Retorna o JSON de resposta, que contém:
      - id: identificador do pagamento (usado para consultar o status depois)
      - point_of_interaction.transaction_data.qr_code: código copia-e-cola
      - point_of_interaction.transaction_data.qr_code_base64: imagem do QR code em base64
    """
    payload = {
        "transaction_amount": round(amount, 2),
        "description": description,
        "payment_method_id": "pix",
        "payer": {
            "email": email,
            "identification": {"type": "CPF", "number": cpf},
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            MP_PAYMENTS_URL, json=payload, headers=_headers(str(uuid.uuid4()))
        )
        resp.raise_for_status()
        return resp.json()


async def get_payment_status(payment_id: str):
    """Consulta o status de um pagamento existente."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{MP_PAYMENTS_URL}/{payment_id}",
            headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"},
        )
        resp.raise_for_status()
        return resp.json()
