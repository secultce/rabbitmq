"""Validação estática das definições do PR de retry (Python 3, sem dependências)."""
import json
from pathlib import Path
import unittest

DEFS = json.loads((Path(__file__).parents[1] / 'config' / 'definitions.json').read_text())


class RetryDefinitionsTest(unittest.TestCase):
    def test_preserva_dlq_existente(self):
        self.assertTrue(any(e['name'] == 'exchange_notification_dlx' for e in DEFS['exchanges']))
        self.assertTrue(any(q['name'] == 'queue_import_registration_dlq' for q in DEFS['queues']))
        self.assertTrue(any(p['name'] == 'import-registration-dlx' and
                            p['definition']['dead-letter-exchange'] == 'exchange_notification_dlx' and
                            p['pattern'] == '^queue_import_registration$'
                            for p in DEFS['policies']))

    def test_cria_as_tres_rotas_com_ttl_e_retorno_para_fila_principal(self):
        self.assertTrue(any(e['name'] == 'exchange_notification_retry' and e['type'] == 'direct'
                            for e in DEFS['exchanges']))
        for n, ms in [(1, 60000), (2, 300000), (3, 900000)]:
            name = f'queue_import_registration_retry_{n}'
            queue = next(q for q in DEFS['queues'] if q['name'] == name)
            self.assertTrue(queue['durable'])
            self.assertEqual(ms, queue['arguments']['x-message-ttl'])
            self.assertEqual('exchange_notification', queue['arguments']['x-dead-letter-exchange'])
            self.assertEqual('module_import_registration_draft',
                             queue['arguments']['x-dead-letter-routing-key'])
            self.assertTrue(any(b['source'] == 'exchange_notification_retry' and
                                b['destination'] == name and
                                b['routing_key'] == f'module_import_registration_draft_retry_{n}'
                                for b in DEFS['bindings']))

    def test_nao_altera_usuarios_permissoes_ou_exchange_principal(self):
        self.assertNotIn('users', DEFS)
        self.assertNotIn('permissions', DEFS)
        self.assertFalse(any(q['name'] == 'queue_import_registration' for q in DEFS['queues']))
        self.assertFalse(any(e['name'] == 'exchange_notification' for e in DEFS['exchanges']))


if __name__ == '__main__':
    unittest.main()
