"""Ferramentas nativas do Claude Code, com bula escrita à mão."""

NATIVES = [
    {
        "name": "Agent:Explore",
        "invoke": "Agent(subagent_type='Explore')",
        "description": "Subagente só-leitura para varrer muitos arquivos e responder onde algo está, sem poluir o contexto principal.",
        "bula": {
            "resumo": "Busca ampla e rápida no código, devolve só a conclusão.",
            "usar_quando": ["procurar onde algo é definido em base grande", "mapear pastas e convenções"],
            "evitar_quando": ["já sabe o arquivo exato", "precisa editar arquivos"],
            "gatilhos": ["onde fica", "procurar no código", "encontrar arquivo", "explorar codebase", "find", "search code"],
        },
    },
    {
        "name": "Agent:Plan",
        "invoke": "Agent(subagent_type='Plan')  ou  EnterPlanMode",
        "description": "Arquiteto que desenha plano de implementação passo a passo antes de codar.",
        "bula": {
            "resumo": "Planejar implementação grande antes de editar.",
            "usar_quando": ["feature grande", "refatoração em vários arquivos", "decidir arquitetura"],
            "evitar_quando": ["mudança pequena e óbvia"],
            "gatilhos": ["planejar", "plano", "arquitetura", "como implementar", "plan", "design architecture"],
        },
    },
    {
        "name": "WebSearch",
        "invoke": "WebSearch",
        "description": "Pesquisa na web por informação atual, docs, preços, notícias.",
        "bula": {
            "resumo": "Buscar informação externa e atualizada.",
            "usar_quando": ["fato recente", "documentação de lib", "comparar produtos"],
            "evitar_quando": ["resposta está no código local"],
            "gatilhos": ["pesquisar", "buscar na internet", "qual a versão", "notícia", "search web", "docs"],
        },
    },
    {
        "name": "WebFetch",
        "invoke": "WebFetch",
        "description": "Baixa e lê o conteúdo de uma URL específica.",
        "bula": {
            "resumo": "Ler uma página web conhecida.",
            "usar_quando": ["usuário passou um link", "ler doc específica"],
            "evitar_quando": ["página precisa de login ou JS pesado (use o navegador)"],
            "gatilhos": ["link", "url", "abrir site", "ler página", "fetch"],
        },
    },
    {
        "name": "Navegador embutido",
        "invoke": "mcp__Claude_Browser__* (preview_start, navigate, computer, read_page)",
        "description": "Navegador real dentro do app: testar dev server, preencher formulários, tirar screenshot, inspecionar console.",
        "bula": {
            "resumo": "Abrir e interagir com páginas web e apps locais.",
            "usar_quando": ["testar UI no navegador", "ver dev server rodando", "screenshot", "depurar console/rede"],
            "evitar_quando": ["só precisa ler texto estático (WebFetch)"],
            "gatilhos": ["abrir no navegador", "testar a página", "screenshot", "localhost", "browser", "preview"],
        },
    },
    {
        "name": "Artifact",
        "invoke": "Artifact (quickstart → publish)",
        "description": "Publica página HTML privada no claude.ai: relatórios, dashboards, explicações, protótipos para compartilhar.",
        "bula": {
            "resumo": "Gerar página web compartilhável a partir do trabalho.",
            "usar_quando": ["relatório para outras pessoas", "dashboard", "explicação visual", "slides"],
            "evitar_quando": ["código que pertence ao repositório"],
            "gatilhos": ["relatório", "dashboard", "página para compartilhar", "apresentação", "artifact", "report"],
        },
    },
    {
        "name": "show_widget (visualize)",
        "invoke": "mcp__visualize__read_me → mcp__visualize__show_widget",
        "description": "Desenha diagrama, gráfico ou widget interativo inline na conversa.",
        "bula": {
            "resumo": "Visual rápido dentro do chat.",
            "usar_quando": ["explicar com diagrama", "gráfico rápido", "fluxograma"],
            "evitar_quando": ["entregável que precisa ser salvo/compartilhado (Artifact)"],
            "gatilhos": ["diagrama", "fluxograma", "desenhe", "gráfico", "visualizar", "diagram", "chart"],
        },
    },
    {
        "name": "Sessões paralelas (start_session)",
        "invoke": "mcp__ccd_session__start_session",
        "description": "Abre outra sessão do Claude Code para tarefa independente, em paralelo ou em worktree separado.",
        "bula": {
            "resumo": "Delegar tarefa grande e independente para outra sessão.",
            "usar_quando": ["tarefa separada que gera branch/PR própria", "trabalho em paralelo"],
            "evitar_quando": ["parte pequena da tarefa atual"],
            "gatilhos": ["em paralelo", "outra sessão", "separar tarefa", "background", "parallel"],
        },
    },
    {
        "name": "Agendamento (schedule / loop)",
        "invoke": "/schedule  ou  /loop",
        "description": "Executa prompt recorrente ou agendado (cron), local ou na nuvem.",
        "bula": {
            "resumo": "Tarefas recorrentes ou em horário marcado.",
            "usar_quando": ["checar algo a cada X minutos", "rodar todo dia"],
            "evitar_quando": ["tarefa única imediata"],
            "gatilhos": ["todo dia", "a cada", "agendar", "lembrar", "cron", "recorrente", "schedule"],
        },
    },
    {
        "name": "code-review / security-review",
        "invoke": "/code-review  ou  /security-review",
        "description": "Revisão nativa de diff/PR por bugs e por falhas de segurança.",
        "bula": {
            "resumo": "Revisar mudanças antes de commitar ou dar merge.",
            "usar_quando": ["revisar diff", "auditar PR", "checar vulnerabilidades"],
            "evitar_quando": ["sem mudanças para revisar"],
            "gatilhos": ["revisar código", "review", "achar bugs", "segurança", "vulnerabilidade", "PR"],
        },
    },
    {
        "name": "Memória persistente",
        "invoke": "escrever em ~/.claude/projects/<projeto>/memory/",
        "description": "Guarda preferências e fatos do usuário/projeto entre sessões.",
        "bula": {
            "resumo": "Lembrar algo para sessões futuras.",
            "usar_quando": ["usuário pede para lembrar", "preferência recorrente"],
            "evitar_quando": ["informação que já está no código/git"],
            "gatilhos": ["lembre", "lembrar", "sempre que", "de agora em diante", "remember"],
        },
    },
]
