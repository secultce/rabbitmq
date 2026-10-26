# RabbitMQ — configuração da DLQ de importação de inscrições

Este repositório mantém a configuração de RabbitMQ utilizada por diferentes módulos. O arquivo `config/definitions.json` adiciona recursos para receber mensagens rejeitadas no fluxo de **importação de inscrições**.

> **Escopo:** esta configuração não deduplica mensagens nem reenvia e-mails. A prevenção de notificações duplicadas é responsabilidade do consumidor, que controla a idempotência por inscrição.

## Pré-requisitos

- Docker e Docker Compose disponíveis no ambiente de implantação.
- Rede Docker externa `lab` previamente criada ou disponibilizada pela infraestrutura (`docker network inspect lab`).
- Permissão para executar comandos no contêiner `rabbitmq`.
- Virtual host `/` existente e usuário com permissões adequadas. Em uma instância nova, a inicialização normal do broker cria os recursos iniciais conforme as variáveis de ambiente suportadas pela imagem.
- A exchange principal `exchange_notification` e a fila principal `queue_import_registration` já existem no ambiente compartilhado. **O arquivo de definições deste PR não as cria.**

## Recursos adicionados

| Tipo | Nome | Finalidade |
| --- | --- | --- |
| Exchange (`direct`) | `exchange_notification_dlx` | Recebe mensagens rejeitadas |
| Fila | `queue_import_registration_dlq` | Armazena mensagens rejeitadas |
| Binding | `module_import_registration_draft_dlq` | Encaminha mensagens da DLX à DLQ |
| Policy | `import-registration-dlx` | Aplica a DLX somente a `queue_import_registration` |

A policy configura `dead-letter-exchange=exchange_notification_dlx` e `dead-letter-routing-key=module_import_registration_draft_dlq`. Quando o consumidor rejeita uma mensagem com `nack(requeue=false)`, o RabbitMQ pode encaminhá-la à DLQ por esse caminho. O funcionamento depende da topologia e das permissões corretas.

## Inicializar o broker

No diretório que contém `docker-compose.yml`:

```bash
docker compose up -d rabbitmq
```

Aguardar a inicialização:

```bash
docker exec rabbitmq rabbitmqctl await_startup --timeout 300
```

O `config/definitions.json` é montado no contêiner em `/etc/rabbitmq/definitions.json`. **A importação não ocorre automaticamente no boot.** O arquivo `rabbitmq.conf` não é necessário para este procedimento e pode ser removido se não houver outras referências a ele.

## Importar as definições (etapa obrigatória de implantação)

Executar **após a inicialização do RabbitMQ**:

```bash
docker exec rabbitmq rabbitmqctl import_definitions /etc/rabbitmq/definitions.json
```

Esta etapa deve fazer parte do procedimento de deploy: é necessária tanto em uma instalação limpa quanto quando as definições do repositório forem alteradas. O comando deve terminar sem erros; não considerar a implantação concluída antes das verificações abaixo.

**Importante:** a importação de definições não deve ser confundida com a criação automática de usuários e vhosts. Em uma instância vazia, iniciar o broker sem importação no boot permite que o procedimento normal de inicialização configure esses recursos; confirme-os antes de importar. Não use este arquivo para substituir a configuração global do RabbitMQ compartilhado.

## Validar a instalação

Verificar o virtual host e os usuários (não exibe senhas):

```bash
docker exec rabbitmq rabbitmqctl list_vhosts
docker exec rabbitmq rabbitmqctl list_users
```

Verificar exchanges e filas:

```bash
docker exec rabbitmq rabbitmqctl list_exchanges -p / name type durable
docker exec rabbitmq rabbitmqctl list_queues -p / name durable messages_ready messages_unacknowledged policy
```

Verificar bindings e a policy:

```bash
docker exec rabbitmq rabbitmqctl list_bindings -p /
docker exec rabbitmq rabbitmqctl list_policies -p /
```

Confirmar especialmente:

- Exchange `exchange_notification_dlx` do tipo `direct`.
- Fila `queue_import_registration_dlq` durável.
- Binding da DLX para a DLQ com routing key `module_import_registration_draft_dlq`.
- Policy `import-registration-dlx` associada à fila `queue_import_registration`.
- Exchange principal `exchange_notification`, fila principal `queue_import_registration` e binding principal presentes no ambiente.

### Teste funcional da DLQ

Realizar **somente em desenvolvimento/homologação**, com mensagem de teste controlada e sem risco de disparar e-mails reais:

1. Publicar uma mensagem inválida na fila principal.
2. Confirmar que o consumidor a rejeita com `nack(requeue=false)`.
3. Verificar na interface de gerenciamento (`Queues`) se a mensagem saiu da fila principal e apareceu em `queue_import_registration_dlq`.
4. Se necessário, inspecionar os cabeçalhos da mensagem na DLQ (por exemplo, `x-death`) para identificar a causa da rejeição.

**Não utilize `purge`, `delete_queue` ou remova volumes de produção para executar testes.** Não reencaminhe mensagens da DLQ diretamente à fila principal sem análise prévia: isso pode gerar novas tentativas de envio.

## Operação e manutenção

- **Nova instalação / volume vazio:** subir o broker, confirmar a criação do vhost e usuário, importar `definitions.json` e validar os recursos.
- **Ambiente existente:** não excluir nem recriar filas ou exchanges utilizadas por outros módulos; importar somente as definições necessárias e verificar se a policy não conflita com outra policy aplicável à mesma fila.
- **Reinicialização com dados preservados:** a topologia já persistida deve continuar disponível. A importação é especialmente importante após provisionamento limpo ou atualização das definições.
- **Mensagens na DLQ:** são indícios de falhas ou mensagens inválidas; investigar antes de qualquer reprocessamento. A DLQ não possui retry automático nesta configuração.
- **Monitoramento:** acompanhar o volume da DLQ, a fila principal e a disponibilidade do consumidor.
- **Segurança:** não versionar credenciais reais; restringir o acesso a `5672` e `15672` e utilizar contas e permissões adequadas ao ambiente. O acesso à interface de gerenciamento deve permanecer restrito à rede autorizada.
- **Backup:** preservar o volume de dados e seguir o procedimento de backup/restauração estabelecido pela infraestrutura. Não apagar `storage/rabbitmq` em produção.

## Solução de problemas

**`NOT_FOUND - no exchange` ou binding principal ausente:** verificar se a exchange `exchange_notification` já foi provisionada. Este PR apenas configura a DLQ.

**DLQ não recebe mensagens:** verificar policy aplicada, binding da DLX, permissão de escrita na DLX e se o consumidor usa `nack` com `requeue=false`.

**Instalação nova não tem vhost/usuário esperado:** verificar se a importação automática no boot foi de fato removida, se o volume está vazio e se as variáveis de inicialização do contêiner foram configuradas corretamente.

**`PRECONDITION_FAILED` ao declarar fila/exchange:** conferir se tipo e propriedades dos recursos existentes são compatíveis com as declarações feitas pelas aplicações; não os exclua para resolver o erro sem analisar o impacto nos demais módulos.

## Referências

- [Importação e exportação de definições](https://www.rabbitmq.com/docs/definitions)
- [Dead Letter Exchanges](https://www.rabbitmq.com/docs/dlx)
- [Policies](https://www.rabbitmq.com/docs/policies)
- [Controle de acesso](https://www.rabbitmq.com/docs/access-control)
