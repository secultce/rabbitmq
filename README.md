# RabbitMQ — notificações de importação de inscrições

Este repositório mantém a configuração do RabbitMQ compartilhado por diferentes módulos. O arquivo `config/definitions.json` provisiona a **Dead Letter Queue (DLQ)** e as **filas de retry com atraso** do fluxo de importação de inscrições.

> **Responsabilidades:** o RabbitMQ encaminha e armazena mensagens; o consumidor Laravel decide quando uma falha permite retry, limita as tentativas e controla a idempotência por `(opportunity_id, registration_id)`. A infraestrutura não deduplica mensagens nem envia e-mails.

## 1. Topologia

```text
Mapas Culturais
      |
      v
exchange_notification --[module_import_registration_draft]--> queue_import_registration
      ^                                                              |
      |                                                              v
      |                                                       Consumidor Laravel
      |                                                              |
      |                      +---------------------------------------+-----------------+
      |                      |                                       |                 |
      |                  Sucesso /                                Falha segura      Falha definitiva
      |                  duplicidade                               para retry       ou mensagem inválida
      |                      |                                       |                 |
      |                     ACK                                      v                 v
      |                                                exchange_notification_retry   NACK (requeue=false)
      |                                                        |                       |
      |                     +----------------------------------+                       v
      |                     |                 |                |           exchange_notification_dlx
      |                     v                 v                v                       |
      |               retry_1 (1 min)  retry_2 (5 min)  retry_3 (15 min)              v
      |                     |                 |                |           queue_import_registration_dlq
      +---------------------+-----------------+----------------+
                   (dead-letter após TTL)
```

Nomes completos das filas de espera: `queue_import_registration_retry_1`, `queue_import_registration_retry_2` e `queue_import_registration_retry_3`.

A fila principal recebe mensagens da exchange `exchange_notification`, usando a routing key `module_import_registration_draft`. Essa exchange, a fila `queue_import_registration` e seu binding **já devem existir** no broker compartilhado: **não são criados pelo `definitions.json` deste repositório**.

### Recursos configurados

| Recurso | Nome | Finalidade |
| --- | --- | --- |
| Exchange `direct` | `exchange_notification_dlx` | Recebe mensagens rejeitadas definitivamente |
| Fila durável | `queue_import_registration_dlq` | Guarda mensagens que exigem investigação |
| Binding da DLQ | `module_import_registration_draft_dlq` | Encaminha mensagens à DLQ |
| Policy | `import-registration-dlx` | Configura a DLX **somente** na fila principal |
| Exchange `direct` | `exchange_notification_retry` | Recebe publicações de retry feitas pelo Laravel |
| Fila durável | `queue_import_registration_retry_1` | Aguarda 60 segundos |
| Fila durável | `queue_import_registration_retry_2` | Aguarda 300 segundos |
| Fila durável | `queue_import_registration_retry_3` | Aguarda 900 segundos |

Os bindings da exchange `exchange_notification_retry` usam as routing keys:

- `module_import_registration_draft_retry_1`
- `module_import_registration_draft_retry_2`
- `module_import_registration_draft_retry_3`

Cada fila de retry possui `x-message-ttl` e usa **dead-lettering** para retornar à exchange principal `exchange_notification`, pela routing key `module_import_registration_draft`. **Não há consumidores nas filas de retry.**

A policy `import-registration-dlx` aplica-se somente à fila `queue_import_registration`. Mensagens rejeitadas com `nack(requeue=false)` seguem para `exchange_notification_dlx`, com routing key `module_import_registration_draft_dlq`, e daí para a DLQ; **a DLQ não devolve mensagens automaticamente** à fila principal.

## 2. Pré-requisitos

- Docker e Docker Compose disponíveis.
- Rede Docker externa `lab` existente, conforme a configuração atual do projeto (`docker network inspect lab`).
- Permissão para executar comandos no contêiner chamado `rabbitmq`.
- Virtual host `/` existente, com usuários e permissões adequadas.
- Exchange principal `exchange_notification` (do tipo esperado pelas aplicações), fila principal `queue_import_registration` e respectivo binding já provisionados.
- `docker-compose.yml` montando `config/definitions.json` como `/etc/rabbitmq/definitions.json:ro`.
- Configuração anterior de `load_definitions` no boot **removida**. Não é necessário manter `config/rabbitmq.conf` vazio se não houver outras referências ao arquivo.

Este repositório **não cria usuários, senhas, permissões nem o virtual host** por meio das definições. Em uma instância nova, permita que a inicialização normal do RabbitMQ crie os recursos iniciais conforme a configuração da imagem e do ambiente; verifique-os antes da importação.

## 3. Inicialização e importação das definições

No diretório que contém `docker-compose.yml`, inicie o contêiner caso ainda não esteja em execução:

```bash
docker compose up -d rabbitmq
```

Aguarde o broker ficar operacional:

```bash
docker exec rabbitmq rabbitmqctl await_startup --timeout 300
```

Confirme que o virtual host e os usuários esperados existem:

```bash
docker exec rabbitmq rabbitmqctl list_vhosts
docker exec rabbitmq rabbitmqctl list_users
```

Confira também se o arquivo atualizado está disponível no contêiner:

```bash
docker exec rabbitmq cat /etc/rabbitmq/definitions.json
```

**Importe as definições após a inicialização:**

```bash
docker exec rabbitmq rabbitmqctl import_definitions /etc/rabbitmq/definitions.json
```

A importação é **uma etapa obrigatória do provisionamento** de instalações novas e de deploys que modifiquem as definições. Ela **não ocorre automaticamente durante o boot**. Não considere o deploy concluído sem validar os recursos criados.

Uma reinicialização com o volume persistido conserva os recursos existentes; não é necessário limpar ou recriar o volume para atualizar as definições.

## 4. Validação da infraestrutura

Execute:

```bash
# Recursos e permissões
docker exec rabbitmq rabbitmqctl list_exchanges -p / name type durable
docker exec rabbitmq rabbitmqctl list_queues -p / name durable messages_ready messages_unacknowledged arguments policy
docker exec rabbitmq rabbitmqctl list_bindings -p /
docker exec rabbitmq rabbitmqctl list_policies -p /
docker exec rabbitmq rabbitmqctl list_permissions -p /
```

Confirme:

1. A exchange `exchange_notification_dlx`, a fila `queue_import_registration_dlq` e seu binding existem.
2. A policy `import-registration-dlx` continua apontando **somente a fila principal** para a DLQ.
3. A exchange `exchange_notification_retry` e as três filas de retry existem, com os bindings e TTLs corretos.
4. Cada fila de retry aponta seu `x-dead-letter-exchange` para `exchange_notification` e seu `x-dead-letter-routing-key` para `module_import_registration_draft`.
5. A exchange, a fila e o binding principais continuam disponíveis para os outros módulos.
6. O usuário do Laravel possui permissão para publicar na exchange de retry e consumir da fila principal, conforme a política de acesso do ambiente. Verifique também as permissões necessárias para o dead-lettering entre exchanges.

## 5. Testes

### 5.1. Teste estático das definições

Não exige um RabbitMQ em execução:

```bash
python3 -m unittest discover -s tests -v
```

O arquivo `tests/test_definitions.py` deve ser versionado. Arquivos gerados automaticamente, como `tests/__pycache__/test_definitions.cpython-310.pyc`, **não** devem ser versionados. Inclua no `.gitignore`, se necessário:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
```

### 5.2. Teste funcional da DLQ

**Executar somente em desenvolvimento ou homologação**, com dados controlados e sem possibilidade de disparar e-mails reais:

1. Publique uma mensagem deliberadamente inválida na exchange principal, com a routing key `module_import_registration_draft`.
2. Verifique que o consumidor rejeita a mensagem com `nack(requeue=false)`.
3. Confira na interface de gerenciamento se ela saiu da fila principal e chegou à `queue_import_registration_dlq`.
4. Inspecione, se necessário, os cabeçalhos de dead-lettering (por exemplo, `x-death`).

### 5.3. Teste funcional do retry

**Executar somente em homologação**, sem consumidor capaz de enviar e-mails reais:

1. Publique uma mensagem de teste na exchange `exchange_notification_retry`, com routing key `module_import_registration_draft_retry_1`.
2. Confirme que ela entrou em `queue_import_registration_retry_1`.
3. Após aproximadamente **60 segundos**, confirme que saiu da fila de retry e foi roteada para `queue_import_registration`.
4. Repita, se necessário, para as rotas `_retry_2` e `_retry_3`, com esperas aproximadas de **5 e 15 minutos**.
5. Com o PR 4B implantado em ambiente controlado, valide a classificação das falhas, os limites de tentativas e os comportamentos de `ack`/`nack`.

O TTL **não é um agendador de precisão**: o encaminhamento pode acontecer um pouco depois do intervalo configurado. As filas de retry não devem ter consumidores próprios.

**Segurança dos testes:** não utilize `purge`, `delete_queue`, remoção de volumes ou reenvio indiscriminado de mensagens da DLQ em produção.

## 6. Ordem de implantação e rollback

1. Implante o PR 4A (RabbitMQ) e importe `definitions.json` **após** o broker estar operacional.
2. Confirme filas, TTLs, bindings, DLQ e permissões do usuário do Laravel.
3. Implante o PR 4B (Laravel) inicialmente com `RABBITMQ_IMPORT_REGISTRATION_RETRY_ENABLED=false`.
4. Execute os testes do consumidor e um teste de integração em homologação.
5. Habilite `RABBITMQ_IMPORT_REGISTRATION_RETRY_ENABLED=true`, recarregue a configuração do Laravel e reinicie o consumidor.

**Rollback:** para interromper a criação de novos retries, desabilite a flag no Laravel e reinicie o worker. Não remova as filas de retry enquanto houver mensagens pendentes: mensagens já publicadas nelas poderão retornar à fila principal após o TTL, mesmo com a flag desabilitada.

## 7. Operação, monitoramento e cuidados

- **Nova instalação:** iniciar normalmente o broker, verificar vhost/usuários, importar as definições e validar os recursos.
- **Ambiente compartilhado:** não recriar ou apagar recursos de outros módulos; verificar eventuais conflitos de policies.
- **Mensagens na DLQ:** investigar a causa antes de qualquer reprocessamento; não há retorno automático da DLQ para a fila principal.
- **Estados do Laravel:** monitorar `failed`, `sending` e `unknown`. O retry automático não se aplica a mensagens inválidas nem a resultados SMTP incertos; o consumidor deve preservar a idempotência.
- **Monitoramento das filas:** acompanhar `queue_import_registration`, `queue_import_registration_dlq`, as três filas de retry e a disponibilidade do consumidor.
- **TTL:** os valores `x-message-ttl` são argumentos das filas existentes. Alterá-los diretamente em uma nova declaração pode provocar `PRECONDITION_FAILED`; planeje previamente a migração ou uma estratégia de configuração por policies.
- **Persistência e entrega:** filas duráveis e mensagens persistentes ajudam na recuperação, mas o dead-lettering tradicional e a publicação seguida de `ack` não fornecem transação única nem garantia de entrega exatamente uma vez.
- **Segurança:** não versionar credenciais reais; restringir acesso às portas `5672` e `15672`; utilizar permissões adequadas por ambiente e acesso ao painel somente pela rede autorizada.
- **Backup:** preservar o volume persistente e seguir o procedimento de backup e restauração da infraestrutura. Não apagar os dados do broker para testar o provisionamento.

## 8. Solução de problemas

**`NOT_FOUND - no exchange` ou mensagem de retry não retorna à fila principal:** confirme que `exchange_notification` e o binding `module_import_registration_draft` já existem e que as permissões são suficientes.

**DLQ não recebe mensagens:** verifique se a policy está aplicada à fila principal, se a exchange e o binding da DLQ existem e se o consumidor usa `nack` com `requeue=false` para a rejeição definitiva.

**Fila de retry não recebe mensagens:** verifique se `exchange_notification_retry`, o binding correspondente e as permissões de publicação estão corretos. Confira também se o retry está habilitado no consumidor Laravel.

**Mensagem fica na fila de retry por mais tempo que o TTL:** verifique se há falha de roteamento no dead-lettering, se a exchange principal existe e se a fila realmente recebeu os argumentos de TTL/DLX esperados. O prazo é aproximado.

**Instância nova sem virtual host ou usuário:** verifique se a importação automática durante o boot foi removida e se as variáveis de inicialização do contêiner estão corretas.

**`PRECONDITION_FAILED` ao declarar fila ou exchange:** confira a compatibilidade do tipo e dos argumentos existentes. Não exclua recursos em uso para resolver esse erro sem análise de impacto.

## 9. Referências

- [RabbitMQ — Definitions](https://www.rabbitmq.com/docs/definitions)
- [RabbitMQ — Dead Letter Exchanges](https://www.rabbitmq.com/docs/dlx)
- [RabbitMQ — TTL](https://www.rabbitmq.com/docs/ttl)
- [RabbitMQ — Policies](https://www.rabbitmq.com/docs/policies)
- [RabbitMQ — Access Control](https://www.rabbitmq.com/docs/access-control)
