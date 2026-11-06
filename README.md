# Outbound Email Triage & Tracking Engine

Sistema automatizado de monitoramento, triagem e classificação de e-mails enviados em lote. O serviço inspeciona a caixa de saída periodicamente, identifica falhas de entrega (*bounces*), contabiliza dias sem retorno, extrai contatos alternativos em redirecionamentos e classifica a intenção das respostas utilizando o **Google Gemini 2.5 Flash**, mantendo uma fila operacional atualizada no **Google Sheets**.

> **Especificação Técnica (RFC):** Detalhes sobre o desenho do sistema, escopo, requisitos não-funcionais, alternativas consideradas e contratos de dados estão documentados na **[RFC-0001 (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md)**.

---

## Contexto e Problema

Equipes operacionais, recursos humanos, projetos de extensão e áreas comerciais frequentemente realizam disparos em lote que dependem de acompanhamento individual. Após o envio inicial, o controle manual sobre quem respondeu torna-se um gargalo operacional:

* **Atraso no tempo de resposta:** Retornos relevantes ficam dispersos na caixa de entrada em meio a notificações e respostas automáticas.
* **Baixa eficiência na verificação:** Inspecionar *thread* por *thread* na pasta de enviados para identificar quem respondeu, quem ignorou e quais endereços falharam consome horas de trabalho manual.
* **Perda de contexto em redirecionamentos:** Quando um e-mail retorna com erro de entrega (*bounce*), cai em aviso de ausência (*out of office*) ou o destinatário indica outro responsável, a informação precisa ser extraída e repassada rapidamente para não interromper o fluxo de contato.

### Aplicações Práticas

Por operar sobre os cabeçalhos do protocolo de e-mail e analisar a semântica do histórico da conversa, o motor atende diferentes fluxos de comunicação ativa (*outbound*):

1. **Processos Seletivos e Recrutamento:** Controle de convocações para entrevistas, envio de etapas técnicas e confirmação de interesse (identificando confirmações, pedidos de reagendamento, desistências e candidatos sem retorno).
2. **Prospecção Comercial e Parcerias:** Triagem de abordagens corporativas, separando contatos interessados, capturando indicações internas de novos responsáveis e higienizando listas com e-mails inválidos.
3. **Gestão de Convites e Eventos:** Acompanhamento de confirmações de presença (*RSVP*) para palestrantes, bancas avaliadoras, professores ou convidados externos.
4. **Follow-up Operacional:** Monitoramento de cobranças de documentos, formulários ou aprovações pendentes, com cálculo automático de dias corridos sem resposta.

---

## Funcionamento e Categorização

A ferramenta não envia respostas automáticas em nome da equipe. O objetivo do sistema é automatizar a varredura e a leitura de triagem, consolidando o estado de cada conversa na planilha para que a equipe execute a ação adequada com acesso direto à *thread*:

| Status | Critério de Detecção | Ação Operacional |
| :--- | :--- | :--- |
| **`RESPONDIDO`** | Resposta humana identificada. O classificador define a intenção (`POSITIVO_CONFIRMADO`, `DUVIDA_OU_REAGENDAR` ou `RECUSADO`) e gera um resumo objetivo. | Acessar a conversa pelo link direto na planilha e dar andamento ao atendimento. |
| **`PIVOTAR_REDIRECIONADO`** | O destinatário (ou mensagem automática de ausência) indicou outra pessoa ou setor para tratar do assunto. O novo endereço é extraído automaticamente. | Iniciar contato com o endereço registrado na coluna `Contato_Alternativo`. |
| **`AUSENTE_AUTO_REPLY`** | Resposta automática de férias ou licença que não indica um contato substituto. | Aguardar o retorno informado no resumo antes de realizar novo *follow-up*. |
| **`INVALIDO_BOUNCE`** | Falha de entrega reportada pelo servidor de destino (`mailer-daemon` / códigos SMTP `5xx` ou `4xx`). | Verificar erros de digitação no endereço ou acionar o contato por outro canal. |
| **`SEM_RESPOSTA`** | Nenhuma interação externa registrada desde o envio. O sistema atualiza a contagem de dias sem retorno. | Filtrar registros estagnados há mais de $X$ dias e enviar mensagem de acompanhamento. |

---

## Estrutura da Planilha Operacional

A aba **`Rastreamento`** no Google Sheets atua como painel de controle da operação. As colunas **`A` a `J`** (e o cursor técnico na coluna **`M`**) são gerenciadas pelo sistema, enquanto as colunas **`K` e `L`** são reservadas para preenchimento manual da equipe e nunca são sobrescritas durante as sincronizações:

| Coluna | Campo | Exemplo | Descrição |
| :-: | :--- | :--- | :--- |
| **A** | `Thread_ID` | `18f4a9b2c...` | *(Oculto)* Identificador único da conversa no Gmail. |
| **B** | `Destinatario` | `contato@empresa.com` | Endereço de destino da mensagem original. |
| **C** | `Assunto` | `[Convite] Banca Avaliadora` | Assunto original da conversa. |
| **D** | `Data_Envio` | `2026-11-01` | Data do disparo inicial. |
| **E** | `Dias_Vacuo` | `3` | Dias corridos sem resposta (zerado após interação do destinatário). |
| **F** | `Status` | `RESPONDIDO` | Estado macro da conversa para filtragem rápida. |
| **G** | `Intencao` | `DUVIDA_OU_REAGENDAR` | Classificação detalhada da resposta ou da falha de entrega. |
| **H** | `Contato_Alternativo` | `suporte@empresa.com` | Novo e-mail extraído em casos de redirecionamento ou ausência. |
| **I** | `Resumo_Contexto` | *"Solicitou reagendamento para sexta-feira às 15h."* | Síntese em uma linha do conteúdo recebido. |
| **J** | `Link_Direto` | `[Abrir no Gmail]` | Atalho direto para a conversa correspondente no Gmail. |
| **K** | `Responsavel` | `Maria` | **(Manual)** Membro da equipe designado para o acompanhamento. |
| **L** | `Notas_Equipe` | `Horário confirmado` | **(Manual)** Observações internas da operação. |
| **M** | `Last_Message_ID` | `18f4c001...` | *(Oculto)* Identificador da última mensagem processada (controle de idempotência). |

---

## Configuração e Implantação

O serviço foi projetado para execução autônoma via **GitHub Actions** (por agendamento periódico a cada 30 minutos ou acionamento manual), sem necessidade de infraestrutura dedicada.

### 1. Credenciais no Google Cloud Console
1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/) e habilite a **Gmail API** e a **Google Sheets API**.
2. **Service Account (Acesso ao Google Sheets):**
   * Em *IAM & Admin > Service Accounts*, crie uma conta de serviço e exporte a chave privada em formato JSON.
   * Compartilhe a planilha operacional com o `client_email` da Service Account atribuindo permissão de **Editor**.
3. **Credencial OAuth 2.0 (Leitura do Gmail):**
   * Em *APIs & Services > OAuth consent screen*, configure a tela de consentimento e altere o status de publicação para **"In Production"** (evitando a expiração de tokens de teste a cada 7 dias).
   * Em *Credentials*, crie um *OAuth Client ID* do tipo **Desktop App** e execute o fluxo de autorização local (`uv run python -m src.gmail_client --auth`) na conta responsável pelos envios para gerar o arquivo `token.json`.

### 2. Variáveis de Ambiente no GitHub
No repositório do projeto, acesse **Settings > Secrets and variables > Actions** e cadastre os seguintes *Repository Secrets*:
* `GEMINI_API_KEY`: Chave de acesso da API gerada no [Google AI Studio](https://aistudio.google.com/).
* `SPREADSHEET_ID`: Identificador da planilha (presente na URL do Google Sheets).
* `GOOGLE_SERVICE_ACCOUNT_JSON`: Conteúdo integral do arquivo JSON da Service Account.
* `GMAIL_OAUTH_TOKEN_JSON`: Conteúdo integral do arquivo `token.json` gerado na etapa de autenticação.

---

## Execução Local e Desenvolvimento

```bash
# 1. Instalar o gerenciador de pacotes uv (caso não esteja instalado)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sincronizar dependências do ambiente virtual
uv sync

# 3. Executar a suíte de testes automatizados
uv run pytest

# 4. Rodar um ciclo de sincronização localmente (requer arquivo .env configurado)
uv run python -m src.main
```
