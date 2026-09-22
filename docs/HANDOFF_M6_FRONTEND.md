# Marco 6 — Frontend Product handoff

## Escopo entregue

Implementação da camada de confiabilidade e das páginas de onboarding e diagnóstico:

- `desktop/src/types/reliability.ts`: DTOs alinhados aos modelos de confiabilidade e relatório de diagnóstico do backend, guards para respostas conhecidas e representação explícita dos campos de resposta ainda não especificados.
- `desktop/src/services/reliabilityApi.ts`: cliente tipado para os seis comandos `system.diagnostics.collect`, `system.diagnostics.export`, `system.backup.create`, `system.backup.list`, `system.backup.restore` e `system.onboarding.status`.
- `desktop/src/stores/reliabilityStore.ts`: estado Zustand para diagnóstico, backups, onboarding, operações em andamento, progresso e erros. Sucesso só é registrado após resposta válida do bridge/backend; erros visíveis têm credenciais e caminhos locais redigidos.
- `desktop/src/pages/OnboardingPage.tsx`: seleção/criação de projeto, detecção reportada de CLIs e autenticação, leitura/criação de RuntimeBindings, capacidade observada, configuração de agente, e criação/análise da primeira missão. Credenciais não são coletadas nesta tela.
- `desktop/src/pages/DiagnosticsCenterPage.tsx`: versão RC, sistema, integridade e resumo SQLite, providers, bindings, migrações, logs sanitizados, exportação de bundle, e backup/restore com revisão de impacto e confirmação humana.

## Contratos ainda não especificados

O contrato M6 não define a estrutura de retorno de `system.onboarding.status` nem o formato/localização do resultado de `system.diagnostics.export`. Esses retornos permanecem `unknown`; a UI não infere campos nem apresenta caminho de arquivo/exportação não confirmado. Para completar integração, o backend/bridge deve publicar os schemas dessas respostas. A ligação das páginas ao shell, rotas e bridge compartilhada fica para a onda do Lead.

Detecção de Codex/Claude Code/Gemini usa o endpoint de status de CLI existente; Antigravity, `gh` e `git` são exibidos somente quando reportados pelo diagnóstico. Estados ausentes são identificados como “não reportado”, não como ausentes do sistema.

## Segurança e recuperação

O restore exige confirmação explícita e mostra o impacto, SHA-256, schema e tamanho antes de invocar o backend. A página faz verificações preliminares de formato do hash e compatibilidade de schema, sem substituir as validações autoritativas do backend. Caminhos de arquivo não são expostos no manifesto. O resultado de recuperação/rollback só é exibido se o backend o retornar; detalhes não definidos pelo contrato não são fabricados.

## Validação

Testes de página: `npm --prefix desktop test -- --run src/pages/__tests__/DiagnosticsCenterPage.test.tsx src/pages/__tests__/OnboardingPage.test.tsx` — 9 testes aprovados.

Validação da suíte completa: `npm --prefix desktop test -- --run` — 41 arquivos e 220 testes aprovados. Lint e build finais são registrados na solicitação da janela de commit após a última execução.
