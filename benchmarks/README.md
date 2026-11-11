# Benchmarks — features de referencia

Cinco features pequeñas y realistas, una por tipo de trabajo, para **medir** el harness en tu org
en lugar de fiarte de la intuición. Cada `.json` es un borrador listo para `./hx propose`.

| Fichero | Ejercita | Roles que entran |
|---|---|---|
| `01-trigger-apex.json` | Trigger + service + tests bulk | architect, apex, security-admin, test, 4 revisores |
| `02-lwc.json` | LWC con LDS/Apex + Jest + a11y | + lwc-developer, admin-configurator, accessibility |
| `03-flow.json` | Record-triggered flow + test Apex | + flow-developer, data-modeler |
| `04-integracion.json` | Callout asíncrono con Named Credential | + integration-developer |
| `05-agentforce.json` | Acción invocable + agente | + agentforce-developer |

## Cómo ejecutarlo

1. Org de desarrollo limpia (`./hx org setup`) y `./hx doctor` en verde.
2. Por cada fichero, en una sesión de Claude Code:
   > Propón la feature de `benchmarks/01-trigger-apex.json` y llévala hasta el final.

   Aprueba cuando te lo pida y **no intervengas más** salvo que te pregunte. Apunta cada intervención.
3. Al terminar: `./hx metrics` (o `./hx metrics --json > benchmarks/resultados.json`).

## Qué mirar

| Métrica | Qué te dice |
|---|---|
| Lead time y tiempo por fase | Dónde se va el tiempo |
| % de gates en verde a la primera | Calidad de lo que entregan los implementers |
| Reviews rechazadas / ciclos de rework | Si diseño y construcción aciertan a la primera |
| Ampliaciones de scope en build | Calidad del mapa de archivos del diseño |
| Acciones bloqueadas por los guardas | Cuántas veces un agente intentó salirse de su carril |
| Intervenciones humanas (apúntalas tú) | Autonomía real |

Repite tras cambiar un prompt, un modelo o una regla: es la única forma de saber si el cambio mejora
o empeora. Comparar entre modelos por rol (`model:` en cada agente) también sale de aquí.
