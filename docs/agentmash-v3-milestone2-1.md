# AgentMash V3 — Marco 2.1

O Marco 2.1 separa explicitamente tecnologia, instalação autenticada e identidade de agente. `Provider` continua sendo o catálogo estático (`openai`/`claude`); `RuntimeBinding` representa uma instalação/conta com capacidade configurada e observada; `Agent` é uma identidade persistente ligada a um binding; `Session` é uma execução isolada de um Agent; e cada lease de concorrência reserva um slot do binding.

`0016_runtime_bindings.sql` adiciona a tabela de bindings, a associação opcional do Agent e da Session, capacidade, health/backoff e metadados de processo. Bindings CLI padrão são criados para OpenAI/Codex e Claude. A associação de Agents existentes é reconciliada no startup sem copiar credenciais.

O catálogo não deduplica por provider. O seed inicial tem dois trabalhadores Codex (`worker_atlas` e `worker_nova`), além de líder e revisor; usuários podem criar ou duplicar novas identidades pelo fluxo de Agents, escolhendo o `runtime_binding_id` e o limite individual de sessões. A seleção continua excluindo `agent_id` ocupado e exige independência entre trabalhador e revisor.

Leases persistentes são admitidos sob lock do repositório, com limites global, provider, binding, projeto e missão. O scheduler usa a capacidade observada do binding como backpressure. A execução CLI já abre um subprocesso por Session; o callback de processo persiste PID em artefato sanitizado e o lifecycle permanece ligado à Session.

No smoke real Codex de 20/09/2026, `Atlas`, `Nova` e `Sentinel` foram representados por três Agent IDs distintos ligados ao mesmo binding Codex. As duas Sessions de trabalhador iniciaram às 18:01:51.920 e 18:01:51.922, com PIDs distintos registrados nos artefatos; as worktrees e branches foram diferentes, ambas as entregas foram integradas em branch temporária, o gate passou, a aprovação humana foi registrada e o banco foi reaberto depois do restart. A main manteve o SHA base `c40edcbe89aeb95fb73b60d3852a1d8aa19bfa79` durante o teste.

O editor de Agent permite informar o binding e o limite individual. O editor de capacidade do binding está disponível via bridge (`runtime_binding.set_capacity`) e valida valores entre 1 e 32; a tela dedicada de administração de bindings permanece um próximo refinamento. Claude continua sujeito à quota disponível no ambiente.
