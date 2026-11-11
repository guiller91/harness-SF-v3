# Arquitectura del proyecto

> Refleja el estado **real** del proyecto, no el deseado. Lo mantiene `docs-writer` al cerrar cada
> feature; `solution-architect` lo lee antes de diseñar.

## Org y entrega

- **Modelo de org de desarrollo:** ver `harness.config.json` → `org.model` (`scratch` | `sandbox`).
- **API version:** la de `sfdx-project.json` (`sourceApiVersion`).
- **Entrega:** source deploy por manifest de feature (`manifest/<id>/package.xml`). La promoción a
  entornos superiores la hace el pipeline o una persona.

## Modelo de datos

| Objeto | API name | Relaciones | Sharing | Notas |
|---|---|---|---|---|
| | | | | |

## Componentes

| Componente | Tipo / capa | Responsabilidad | Feature |
|---|---|---|---|
| | | | |

## Automatización por objeto (orden de ejecución)

| Objeto | Momento | Trigger / Flow | Qué hace |
|---|---|---|---|
| | | | |

## Integraciones

| Sistema | Dirección | Mecanismo | Named Credential | Notas |
|---|---|---|---|---|
| | | | | |

## Decisiones de arquitectura

Ver `docs/adr/`.
