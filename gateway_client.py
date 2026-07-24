import uuid
import httpx
import logging
from config import CLIENT_ID, CLIENT_SECRET, CHARGES_URL

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {CLIENT_SECRET}",
        "X-Client-Id": CLIENT_ID,
        "Content-Type": "application/json",
    }


async def create_pix_charge(
    amount: float,
    name: str,
    cpf: str,
    description: str,
    external_id: str = None,
) -> dict:
    """
    Cria uma cobrança Pix no gateway de pagamento próprio via POST /api/v1/charges.
    Headers:
      Authorization: Bearer <CLIENT_SECRET>
      X-Client-Id: <CLIENT_ID>
      Content-Type: application/json
    Payload:
      {
        "amount": 100.00,
        "external_id": "pedido-123",
        "payer": {
          "name": "Cliente",
          "document": "CPF"
        },
        "description": "Pedido 123"
      }
    """
    if not external_id:
        external_id = f"charge-{uuid.uuid4().hex[:12]}"

    payload = {
        "amount": round(float(amount), 2),
        "external_id": external_id,
        "payer": {
            "name": name or "Cliente",
            "document": cpf,
        },
        "description": description,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(CHARGES_URL, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def get_charge_status(charge_id: str) -> dict:
    """
    Consulta o status de uma cobrança existente via GET /api/v1/charges/{charge_id}.
    """
    url = f"{CHARGES_URL}/{charge_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def parse_charge_response(data: dict) -> dict:
    """
    Normaliza a resposta do gateway para extração segura de:
      - id (ID da transação/cobrança)
      - pix_code (Código copia e cola do Pix)
      - qr_code_base64 (Imagem do QR Code em base64, se disponível)
      - status (Status em maiúsculas: PENDING, APPROVED, PAID, etc.)
    """
    if not isinstance(data, dict):
        return {"id": None, "pix_code": None, "qr_code_base64": None, "status": "UNKNOWN", "raw": data}

    inner_data = data.get("data") if isinstance(data.get("data"), dict) else data

    # Extrai o ID da transação
    charge_id = (
        inner_data.get("id")
        or inner_data.get("charge_id")
        or inner_data.get("external_id")
        or inner_data.get("txid")
        or data.get("id")
        or data.get("external_id")
    )

    # Extrai o código Pix Copia e Cola
    pix_code = (
        inner_data.get("pix_code")
        or inner_data.get("qr_code")
        or inner_data.get("copy_paste")
        or inner_data.get("pix_copy_paste")
        or inner_data.get("emv")
        or inner_data.get("code")
    )
    if isinstance(pix_code, dict):
        pix_code = (
            pix_code.get("qr_code")
            or pix_code.get("copy_paste")
            or pix_code.get("code")
            or pix_code.get("emv")
        )

    if not pix_code and isinstance(data.get("pix"), dict):
        pix_code = data["pix"].get("qr_code") or data["pix"].get("copy_paste") or data["pix"].get("code")
    if not pix_code and isinstance(data.get("point_of_interaction"), dict):
        poi = data.get("point_of_interaction", {}).get("transaction_data", {})
        pix_code = poi.get("qr_code") or poi.get("qr_code_base64")

    # Extrai imagem QR Code Base64 se disponível
    qr_code_b64 = (
        inner_data.get("qr_code_base64")
        or inner_data.get("image_base64")
        or inner_data.get("qrcode_base64")
        or data.get("qr_code_base64")
    )

    # Extrai status
    raw_status = (
        inner_data.get("status")
        or data.get("status")
        or "PENDING"
    )

    return {
        "id": str(charge_id) if charge_id else None,
        "pix_code": str(pix_code) if pix_code else None,
        "qr_code_base64": str(qr_code_b64) if qr_code_b64 else None,
        "status": str(raw_status).upper(),
        "raw": data,
    }
