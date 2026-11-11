# AGENTS.md — Mapa del harness

Harness de ingeniería para proyectos **Salesforce** sobre **Claude Code**: un orquestador y 19
especialistas que diseñan, construyen, verifican y entregan features. Reglas comunes en
[`CLAUDE.md`](CLAUDE.md); criterios de hecho en [`CHECKPOINTS.md`](CHECKPOINTS.md); flujo en
[`docs/workflow.md`](docs/workflow.md).

## Roles

| Fase | Agente | Modelo | Escribe | Responsabilidad |
|---|---|---|---|---|
| — | `orchestrator` | el de la sesión | estado (vía `./hx`), notas | Única voz con el humano. Planifica, delega, exige evidencia. |
| Diseño | `business-analyst` | sonnet | `requirements.md` | Historia, criterios Dado/Cuando/Entonces, casos límite. |
| Diseño | `org-analyst` | sonnet | `org-context.md` | Qué existe ya en la org y dónde puede chocar la feature. |
| Diseño | `solution-architect` | opus | `design.md` | Enfoque, modelo de datos, contratos, mapa de archivos, seguridad, plan de pruebas. |
| Build | `data-modeler` | sonnet | objetos, campos, validation rules, CMDT | Modelo de datos. |
| Build | `apex-developer` | sonnet | clases (no tests), triggers | Lógica de servidor bulk-safe y en modo usuario. |
| Build | `integration-developer` | sonnet | credenciales, eventos, clientes de callout | Integraciones fiables. |
| Build | `flow-developer` | sonnet | flows | Automatización declarativa. |
| Build | `lwc-developer` | sonnet | LWC (no tests) | Interfaz. |
| Build | `agentforce-developer` | sonnet | bundles de agente, prompt templates | Agentes de Agentforce como código. |
| Build | `admin-configurator` | sonnet | páginas, layouts, tabs, labels | Que lo construido llegue al usuario. |
| Build | `security-admin` | sonnet | permission sets, sharing | Acceso de mínimo privilegio. |
| Build | `test-engineer` | sonnet | tests Apex y Jest | Pruebas desde el diseño, no desde el código. |
| Verify | `qa-verifier` | sonnet | `acceptance.md`, veredicto | Cada criterio de aceptación, con evidencia. |
| Verify | `code-reviewer` | sonnet | veredicto | Corrección, capas, bulk, calidad de tests. |
| Verify | `security-reviewer` | opus | veredicto | Sharing, CRUD/FLS, inyección, privilegios, secretos. |
| Verify | `performance-reviewer` | sonnet | veredicto | Límites de gobierno con 200 registros, selectividad. |
| Verify | `accessibility-reviewer` | sonnet | veredicto | Teclado, lector de pantalla, estados (si hay LWC). |
| Release | `release-manager` | sonnet | `manifest/<id>/`, `release.md` | Manifest, pasos manuales, rollback. |
| Release | `docs-writer` | haiku | arquitectura, ADR, changelog | Documentar lo construido. |

**Por qué estos modelos:** el más capaz donde un error sale caro y no lo caza un gate (diseño y
seguridad); uno equilibrado donde el trabajo se verifica mecánicamente después (construcción y el
resto de revisiones); el más ligero para documentación. Se cambia en el `model:` de cada agente.

**Por qué quien construye no prueba ni aprueba:** `test-engineer` escribe los tests desde el diseño
(un test calcado del código hereda sus errores), y la matriz de propiedad impide que un implementer
edite los tests o que un revisor edite el código.

## Reglas de ejecución

- **Implementers en serie**, en el orden de `./hx plan`: comparten una org y un deploy es global.
- **Revisores en paralelo**: solo leen.
- **Los subagentes no lanzan subagentes** (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`).
- **Solo el orquestador** cambia el estado, hace commits y habla con el humano.

## Árbol

```
.
├── CLAUDE.md · AGENTS.md · CHECKPOINTS.md      reglas, mapa y criterios de hecho
├── hx                                          CLI del harness (./hx --help)
├── harness.config.json                         org, cobertura, analyzer, flujo
├── feature_list.json                           features y su estado (solo vía ./hx)
├── harness/
│   ├── cli.py · lib/                           máquina de estados, evidencia, métricas
│   ├── roles.json                              matriz de propiedad por rol
│   ├── pipeline.json                           qué exige cada tipo de cambio
│   ├── gates/                                  static · apex-tests · lwc-tests · agent-validate · deploy-validate
│   └── tests/                                  tests del propio harness
├── .claude/
│   ├── settings.json                           permisos + hooks
│   ├── agents/                                 20 roles
│   ├── skills/                                 protocolo + 11 skills de Salesforce
│   └── hooks/                                  guardas (escritura, shell), revisión rápida, traspasos, sesión
├── .harness/                                   evidencia y eventos (los escribe ./hx)
├── docs/
│   ├── architecture.md · conventions.md        estado y normas del proyecto
│   ├── workflow.md · security-model.md         cómo funciona el harness
│   ├── specs/<id>/                             requirements · org-context · design · acceptance · release
│   └── adr/
├── progress/
│   ├── current.md · history.md                 generados por ./hx
│   └── <id>/                                   informes por rol + notes.md
├── manifest/<id>/                              package.xml de cada feature
├── benchmarks/                                 features de referencia para medir el harness
└── force-app/ · sfdx-project.json · config/    el proyecto Salesforce
```
