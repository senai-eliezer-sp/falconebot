# VIPFALCONE Bot — Telegram (Python)

Bot de vendas com saldo, Pix via **Mercado Pago**, e entrega de chaves/cupons
com prévia mascarada.

## Fluxo

1. `/start` → mostra saldo e menu (Compre Aqui / Adicione Saldo / Carteira).
2. **Adicione Saldo** → bot pede e-mail e CPF (uma única vez, fica salvo) →
   gera cobrança Pix no Mercado Pago → envia QR code + código copia-e-cola →
   bot fica checando automaticamente a cada 15s (até 30min) se caiu, e o
   cliente também pode clicar em "Verifiquei o pagamento".
3. **Compre Aqui** → mostra o vendedor (Admin) → lista produtos com preço
   **e quantidade em estoque** → ao escolher um produto, mostra uma prévia
   mascarada (ex: `AB**-**34-EF**-**78`) → ao confirmar, debita o saldo e
   entrega o código completo.

## Administração (restock e estoque)

Só funciona para os IDs listados em `ADMIN_IDS` no `.env`.

- `/addproduct Nome do Produto | 19.90` — cria um novo produto.
- `/restock <id_do_produto>` — bot pede os códigos; envie um por linha,
  numa única mensagem, para adicionar ao estoque (pode repetir quantas
  vezes quiser, a qualquer momento).
- `/stock` — lista todos os produtos com preço e quantidade restante.

O cliente sempre vê a quantidade disponível na lista de produtos e na
tela de detalhes, então dá pra acompanhar quando está acabando.

## Configuração

1. Copie `.env.example` para `.env` e preencha:
   - `BOT_TOKEN`: token do BotFather.
   - `MP_ACCESS_TOKEN`: seu Access Token do Mercado Pago (Painel do
     desenvolvedor → Suas integrações → Credenciais de produção).
   - `ADMIN_IDS`: seu ID numérico do Telegram (pegue com @userinfobot).

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Rode o bot:
   ```bash
   python main.py
   ```

## Sobre a confirmação de pagamento

Este bot **não depende de webhook** para funcionar — ele faz polling direto
na API do Mercado Pago (`GET /v1/payments/{id}`) a cada 15 segundos, além
do botão manual "Verifiquei o pagamento". Isso evita ter que expor um
servidor HTTP público só para essa finalidade.

## Observações importantes

- O e-mail e CPF do comprador são exigidos pela API do Mercado Pago para
  processar o Pix — o bot já valida o formato de ambos antes de enviar.
- Os produtos vendidos devem ser de sua propriedade/licenciamento legítimo
  (chaves de software, cupons, etc.) — o bot foi desenhado para esse uso.
- O banco é SQLite (`vipfalcone.db`), criado automaticamente na primeira
  execução, na mesma pasta do bot.
