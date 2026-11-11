# CLAUDE.md — Reglas comunes del harness

Este repositorio es un **harness de ingeniería para Salesforce**: un orquestador y 19 agentes
especializados construyen, verifican y entregan features con evidencia. Este fichero lo leen
**todos** los agentes. El rol de cada uno está en `.claude/agents/<rol>.md`; el mapa completo, en
[`AGENTS.md`](AGENTS.md).

## Las diez reglas

1. **El estado vive en disco.** `feature_list.json`, `progress/` y `docs/specs/` son la memoria del
   proyecto. Lo que no está escrito no existe para el siguiente agente ni para la siguiente sesión.
2. **El estado solo cambia con `./hx`.** Nadie edita `feature_list.json` ni la evidencia a mano.
   `./hx status` dice siempre dónde estamos y cuál es el siguiente paso.
3. **Una feature activa a la vez**, y pasa por fases con puerta: `design → build → verify → release`.
4. **Cada fichero tiene dueño.** Solo el rol dueño de un tipo de metadata lo escribe, solo en su
   fase y solo dentro del scope aprobado de la feature (`harness/roles.json`).
5. **El orquestador no escribe producto; los revisores no editan.** Quien construye no se aprueba
   a sí mismo.
6. **Implementers en serie, revisores en paralelo.** La org es compartida: dos despliegues a la vez
   se pisan. Leer no colisiona.
7. **Nada se da por bueno sin evidencia.** Los gates se ejecutan con `./hx gate run`; su resultado
   queda atado al hash del código verificado. Si el código cambia, la evidencia caduca y se repite.
   Lo que no se pudo comprobar se escribe como `NO VERIFICADO`, nunca como hecho.
8. **Solo la org de desarrollo.** Todo comando `sf` lleva `--target-org` explícito con el alias de
   `harness.config.json`. Ni credenciales, ni otras orgs, ni producción. La promoción a entornos
   superiores la hace un pipeline o una persona.
9. **Las decisiones de negocio y lo irreversible son del humano.** Aprobar una feature, cerrarla,
   publicar una rama, borrar datos o ampliar permisos pasa por él.
10. **No se inventa.** Ni nombres de API, ni flags de la CLI, ni límites, ni reglas de negocio. Se
    comprueba (en el repo, en la org, con `--help`, en la documentación) o se marca `A VERIFICAR`.

Estas reglas no dependen de la buena voluntad: las aplican los hooks de `.claude/hooks/`. Si una
acción se bloquea, el mensaje explica por qué y qué hacer. No busques rodeos; si crees que la regla
está mal, díselo al humano.

## Dónde está cada cosa

| Necesitas | Mira |
|---|---|
| Estado y siguiente paso | `./hx status` · `progress/current.md` |
| Qué exige esta feature (roles, gates, reviews) | `./hx plan` |
| Requisitos, diseño, contexto de org, aceptación, release | `docs/specs/<id>/` |
| Qué hizo cada agente | `progress/<id>/<rol>.md` |
| Criterios de "hecho" | [`CHECKPOINTS.md`](CHECKPOINTS.md) |
| Convenciones de código y metadata | [`docs/conventions.md`](docs/conventions.md) |
| Arquitectura actual del proyecto | [`docs/architecture.md`](docs/architecture.md) |
| Cómo funciona el flujo y sus puertas | [`docs/workflow.md`](docs/workflow.md) |
| Qué bloquean los guardas y por qué | [`docs/security-model.md`](docs/security-model.md) |
| Conocimiento Salesforce por materia | skills `sf-*` en `.claude/skills/` |

## Estilo de trabajo

- Lee antes de escribir: diseño, informes previos, convenciones.
- Cambios mínimos y dentro de tu encargo. Lo que no es tuyo se anota para su dueño.
- Salidas reales de comandos, no resúmenes optimistas.
- Idioma del proyecto: español en documentación e informes; nombres de API según `docs/conventions.md`.
