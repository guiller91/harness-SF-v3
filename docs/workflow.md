# Flujo de trabajo

## Fases y puertas

```
 humano describe ──► draft ──[OK humano]──► approved ──► design ──► build ──► verify ──► release ──[OK humano]──► done
                     propose     approve       start       advance    advance    advance       close
                                                              ▲           │  rework  │
                                                              └───────────┴──────────┘
```

| Fase | Quién trabaja | Cómo | Se sale cuando (lo comprueba `./hx`) |
|---|---|---|---|
| **design** | business-analyst → org-analyst → solution-architect | en orden | existen los artefactos con sus secciones, hay scope y, si es L, el humano aprueba el diseño |
| **build** | implementers según el cambio | **en serie**, orden canónico | hay cambios, todos en scope, cada implementer dejó informe |
| **verify** | gates + revisores | gates primero; revisores **en paralelo** | todos los gates y veredictos en PASS sobre el árbol actual; criterios trazados |
| **release** | release-manager, docs-writer | en paralelo | manifest, release.md, deploy-validate en verde, y el humano cierra |

`./hx status` dice en cada momento qué falta y cuál es el siguiente paso; `./hx plan` lista los
roles, gates y reviews que exige **este** cambio.

## El pipeline se deriva del cambio

No todas las features necesitan a los 20 roles. `harness/pipeline.json` decide según el tipo de
metadata (del scope, antes de construir; de los ficheros realmente cambiados, después):

| Si la feature toca… | Construyen | Gates | Revisan |
|---|---|---|---|
| Apex | apex-developer, security-admin, test-engineer | apex-tests | qa, code, security, performance* |
| LWC | lwc-developer, test-engineer | lwc-tests | qa, code, security, performance*, accessibility |
| Flows | flow-developer | apex-tests | qa, code, security, performance* |
| Modelo de datos | data-modeler, security-admin | — | qa, code, security |
| Integraciones | integration-developer, test-engineer | apex-tests | qa, code, security, performance* |
| Agentforce | agentforce-developer, security-admin | agent-validate | qa, code, security |
| UI declarativa | admin-configurator | — | qa, code, security |
| Permisos | security-admin | — | qa, code, security |

Todo cambio de producto pasa además por `format` (prettier), `secrets` (credenciales en el código) y
`static` (Code Analyzer). En release: `deploy-validate` siempre y `regression` (tests locales contra una
línea base de fallos conocidos) en M/L.

El tamaño (`S`/`M`/`L`) ajusta el coste: S solo arquitecto en diseño, sin `performance-reviewer`(*),
sin `docs-writer` y sin `regression`; M y L añaden analista de negocio y de org; L exige aprobar el
diseño. La seguridad (gate `secrets` y `security-reviewer`) no se recorta nunca.

`./hx advance` de build a verify formatea con prettier los ficheros cambiados **antes** de generar
evidencia, para que el commit (lint-staged) no cambie el árbol después.

## Evidencia atada al código

Cada gate y cada veredicto guardan el **hash del árbol de fuente** sobre el que se ejecutaron
(`.harness/evidence/<id>/*.json`). Si después cambia un solo fichero de producto, esa evidencia
pasa a `stale` y la CLI no deja avanzar hasta repetirla. Consecuencias:

- No se puede "arreglar una cosita" después de las reviews y cerrar.
- Tras un rework se repiten gates y reviews: se aprueba el código que sale, no el que había.
- En `verify` y `release` el código está congelado (los hooks bloquean la escritura).

## Rework

`./hx rework <id> --reason "…"` devuelve la feature a `build`. Corrige el **dueño** del fichero con
el hallazgo exacto. Al tercer ciclo (configurable) la feature se bloquea sola y se escala al humano:
si tres vueltas no bastan, el problema está en el diseño o en los criterios.

No todo lo rojo es un rework:

- **Gate en `error`** (exit 3): el entorno impidió comprobar (falta prettier, la CLI no devuelve JSON,
  un motor del analyzer no arranca). Se arregla el entorno y se repite el gate. No consume ciclo.
- **Evidencia caducada en release** sin nada en rojo: `./hx reverify <id> --reason "…"` vuelve a
  verify sin consumir ciclo; `./hx metrics` lo cuenta aparte.

## Traspasos

Los agentes no comparten memoria. Se pasan el trabajo por ficheros:

| Fichero | Lo escribe | Para |
|---|---|---|
| `docs/specs/<id>/requirements.md` | business-analyst | arquitecto, qa |
| `docs/specs/<id>/org-context.md` | org-analyst | arquitecto, flow/apex, performance |
| `docs/specs/<id>/design.md` | solution-architect | todos |
| `progress/<id>/<rol>.md` | cada agente | el siguiente rol y el orquestador (sección **Pendiente**) |
| `docs/specs/<id>/acceptance.md` | qa-verifier | humano |
| `docs/specs/<id>/release.md`, `manifest/<id>/` | release-manager | pipeline / humano |
| `progress/<id>/notes.md` | orquestador | la próxima sesión |
| `progress/current.md`, `progress/history.md` | `./hx` | todos |

Un subagente no puede terminar sin su entregable (hook `SubagentStop`), y al arrancar recibe la
feature, la fase, el scope y qué debe entregar (hook `SubagentStart`).

## Continuidad entre sesiones

Al iniciar, reanudar o compactar una sesión, el hook `SessionStart` reinyecta el estado desde disco
(`./hx status` + últimas notas). Una sesión nueva continúa donde se quedó la anterior.

## Métricas

`./hx metrics` (o `--json`): por feature, lead time, tiempo por fase, ejecuciones de gates y % en
verde a la primera, reviews rechazadas, ciclos de rework, ampliaciones de scope y acciones
bloqueadas por los guardas. Sale de `.harness/events.jsonl`.

## Personalizar

| Quieres… | Toca (como humano, con `HARNESS_MAINTENANCE=1`) |
|---|---|
| Cambiar org, cobertura mínima, umbral del analyzer | `harness.config.json` |
| Cambiar qué roles/gates exige cada tipo de cambio | `harness/pipeline.json` |
| Cambiar quién es dueño de qué metadata | `harness/roles.json` |
| Añadir un gate | `harness/gates/<nombre>.sh` + `pipeline.json` |
| Añadir un rol | `.claude/agents/<rol>.md` + `roles.json` + `pipeline.json` (`./hx check` valida la coherencia) |
| Cambiar el modelo de un rol | `model:` en el frontmatter del agente |
