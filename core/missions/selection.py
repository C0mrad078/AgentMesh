"""Transparent, deterministic eligibility and lexicographic ranking; no invented scores."""
from core.agents.models import Agent
from core.missions.models import Choice, Role
from core.utils.errors import ValidationError

ROLE_CAPABILITIES = {
    'leader': {'planning', 'architecture'},
    'worker': {'coding', 'debugging', 'refactoring'},
    'reviewer': {'code_review', 'review', 'testing'},
}


def choose_agent(agents: list[Agent], *, role: Role, connected: set[str],
                 project_id: str, excluded: set[str], busy: set[str],
                 required: list[str] | None = None) -> Choice:
    wanted = set(required or ROLE_CAPABILITIES[role])
    eligible = []
    for agent in agents:
        caps = {c.name for c in agent.capabilities}
        if (not agent.active or agent.id in excluded | busy or
                agent.project_id not in (None, project_id) or agent.provider not in connected or
                not agent.permissions.can_read_files or not caps & ROLE_CAPABILITIES[role]):
            continue
        if role == 'worker' and (not agent.permissions.can_write_files or not wanted <= caps):
            continue
        if role == 'reviewer' and not agent.permissions.can_run_terminal:
            continue
        # CLI subscription monetary pricing cannot be guaranteed. Fail closed for
        # personas with a monetary ceiling until runtime accounting can enforce it.
        if agent.config.get('max_cost_usd'):
            continue
        matched = sorted(caps & wanted)
        role_match = role in agent.role.lower()
        seniority = {'senior': 2, 'mid': 1, 'junior': 0}.get(agent.config.get('seniority', ''), 0)
        eligible.append(((-len(matched), -int(role_match), -seniority, agent.id), agent, matched))
    if not eligible:
        raise ValidationError(
            f'Nenhum agente elegível para {role}: confira especialidades {sorted(wanted)}, '
            'permissões, CLI/autenticação, concorrência e limite monetário. '
            'Implementador e revisor devem ser identidades diferentes.')
    _, agent, matched = sorted(eligible, key=lambda x: x[0])[0]
    return Choice(agent_id=agent.id, role=role, reason=(
        f'CLI {agent.provider} conectado; agente ativo e disponível; permissões compatíveis; '
        f'capacidades coincidentes: {", ".join(matched)}. '
        'Ordem: aderência, papel configurado, senioridade configurada, id estável. '
        'Sem pontuação de desempenho ou custo estimado: métricas CLI ainda insuficientes.'))
