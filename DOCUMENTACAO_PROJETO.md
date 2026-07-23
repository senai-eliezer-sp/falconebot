# Documentação completa do projeto VIPFALCONE Bot

## 1. Visão geral

O VIPFALCONE Bot é um bot de Telegram desenvolvido em Python para gerenciar vendas de produtos, recargas de saldo via Pix e entrega de conteúdo após confirmação de pagamento.

O projeto foi pensado para funcionar como uma plataforma simples de vendas internas, com:

- cadastro de usuários;
- carteira/saldo interno;
- cobrança via Mercado Pago (Pix);
- compra de produtos/itens com estoque;
- painel administrativo para criar categorias, adicionar estoque e acompanhar vendas;
- armazenamento local em banco SQLite.

---

## 2. Objetivo do projeto

O bot permite que um administrador venda itens ou conteúdos através do Telegram, enquanto o cliente:

1. recarrega saldo no bot;
2. escolhe um produto ou categoria;
3. confirma a compra;
4. recebe o conteúdo após a validação do pagamento e da reserva do estoque.

Ele é especialmente útil para cenários de venda de chaves, cupons, contas ou qualquer material que seja entregue digitalmente.

---

## 3. Funcionalidades principais

### 3.1 Fluxo de cadastro e carteira

Quando o usuário inicia o bot com /start, o sistema:

- cria ou atualiza o cadastro do usuário;
- mostra o saldo atual;
- exibe um menu principal com opções de compra, recarga e carteira.

### 3.2 Recarga de saldo via Pix

O usuário pode adicionar saldo ao bot utilizando Pix pelo Mercado Pago.

O fluxo funciona assim:

- o usuário informa o valor desejado;
- o bot solicita e-mail e CPF (apenas uma vez, salvo no cadastro);
- o bot cria uma cobrança Pix;
- o usuário paga pelo QR code ou código copia-e-cola;
- o bot verifica automaticamente o pagamento e, quando aprovado, credita o saldo.

### 3.3 Compra de produtos

Depois de entrar na área de compra, o usuário pode:

- selecionar um vendedor/admin;
- navegar por categorias;
- visualizar itens disponíveis com quantidade em estoque;
- confirmar a compra;
- receber o conteúdo completo se houver saldo suficiente.

A compra debita o saldo do usuário e reserva o item do estoque para evitar duplicidade.

### 3.4 Administração

Os administradores têm acesso a comandos especiais para:

- criar novos produtos/categorias;
- adicionar estoque em lote;
- visualizar estoque;
- gerenciar itens disponíveis para venda.

---

## 4. Estrutura do projeto

Os principais arquivos do projeto são:

- main.py: núcleo do bot, rotas, comandos, fluxo de compra e integração com o Telegram.
- db.py: gerenciamento do banco SQLite, criação de tabelas e operações de usuários, produtos, estoque e transações.
- config.py: carregamento de variáveis de ambiente e configurações gerais do projeto.
- mercadopago_client.py: integração com a API do Mercado Pago para gerar cobranças Pix e consultar pagamentos.
- keyboards.py: construção dos botões interativos do Telegram.
- requirements.txt: dependências do projeto.
- assets/: pasta para arquivos estáticos, como banners visuais do bot.

---

## 5. Arquitetura e funcionamento interno

### 5.1 Telegram Bot

O projeto utiliza a biblioteca python-telegram-bot para:

- receber mensagens e callbacks do Telegram;
- exibir menus com botões inline;
- processar comandos como /start, /addproduct, /restock e /stock.

### 5.2 Banco de dados

O banco é local, em SQLite, e é criado automaticamente na primeira execução.

As principais tabelas são:

- users: dados dos usuários, saldo, e-mail, CPF e cadastro.
- products: categorias ou produtos disponíveis para venda.
- stock: itens reais em estoque, contendo os dados entregues após a compra.
- transactions: histórico das cobranças Pix e status do pagamento.
- purchases: registro de cada compra do usuário.

### 5.3 Mercado Pago

A integração com Mercado Pago é feita por meio de requisições HTTP usando httpx.

O fluxo de pagamento usa:

- criação de pagamento Pix;
- consulta periódica do status do pagamento;
- confirmação automática quando aprovado.

---

## 6. Fluxo principal de uso

### Usuário comum

1. Inicia o bot com /start.
2. Visualiza o saldo e o menu principal.
3. Pode:
   - adicionar saldo via Pix;
   - consultar a carteira;
   - comprar produtos.

### Administrador

1. Usa comandos especiais.
2. Cria categorias/produtos.
3. Adiciona estoque com blocos de dados.
4. Mantém o bot operacional com itens disponíveis para venda.

---

## 7. Comandos administrativos

### /addproduct

Cria um novo produto ou categoria.

Exemplo:

```bash
/addproduct Nome do Produto | 19.90
```

### /restock

Adiciona itens ao estoque de uma categoria.

Exemplo:

```bash
/restock 1
```

### /stock

Lista ou navega o estoque de uma categoria.

---

## 8. Configuração do ambiente

Antes de rodar o projeto, é necessário criar um arquivo .env com as variáveis principais:

- BOT_TOKEN: token gerado pelo BotFather.
- MP_ACCESS_TOKEN: token de acesso do Mercado Pago.
- ADMIN_IDS: IDs dos administradores no Telegram.
- BOT_NAME: nome do bot exibido nas mensagens.
- DB_PATH: caminho do banco SQLite, se necessário.
- BANNER_PATH: imagem de banner para o menu.

### Instalação

```bash
pip install -r requirements.txt
```

### Execução

```bash
python main.py
```

---

## 9. Dependências principais

As dependências do projeto são:

- python-telegram-bot
- httpx
- python-dotenv

Essas bibliotecas permitem o funcionamento do bot, as requisições HTTP e a leitura das variáveis de ambiente.

---

## 10. Pontos importantes do projeto

### Segurança e boas práticas

- O bot valida e-mail e CPF antes de gerar cobrança Pix.
- O saldo é controlado internamente no banco.
- A compra reserva o item para evitar que o mesmo estoque seja vendido duas vezes.
- As informações sensíveis são mascaradas antes de serem exibidas ao usuário.

### Observações

- O sistema foi pensado para uso legítimo e responsável.
- O banco é local, o que simplifica a implantação, mas exige cuidado com backups.
- O fluxo de pagamento depende da API do Mercado Pago e do token configurado corretamente.

---

## 11. Resumo do projeto

Este projeto é um bot de Telegram completo para vender produtos e recarregar saldo com Pix, com:

- interface interativa no Telegram;
- controle de saldo;
- integração com Mercado Pago;
- gestão de estoque;
- painel administrativo simples;
- armazenamento local em SQLite.

Em resumo, ele une automação, pagamento, estoque e interface de chat em uma solução prática para venda digital via Telegram.

---

## 12. Sugestões futuras

Possíveis melhorias para o projeto:

- adicionar painel web para administração;
- implementar logs mais detalhados;
- criar suporte a múltiplos vendedores;
- adicionar webhook para pagamentos em vez de polling;
- implementar notificações para o administrador sobre novas vendas.
