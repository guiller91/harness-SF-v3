# Convenciones del proyecto

Vinculantes para los implementers; los revisores validan contra este documento. Adáptalo a tu
equipo: es de los pocos ficheros que **debes** personalizar. El detalle técnico por materia está en
las skills `sf-*` (`.claude/skills/`); aquí va lo que es decisión del proyecto.

## Nombres

| Elemento | Convención | Ejemplo |
|---|---|---|
| Objeto / campo custom | `PascalCase_Con_Guiones__c`, sin abreviaturas | `Pedido__c`, `Fecha_Entrega__c` |
| Clase Apex | `PascalCase` + sufijo de capa | `PedidoService`, `PedidoSelector`, `PedidoController`, `PedidoTriggerHandler` |
| Test Apex | `<Clase>Test` · método `metodo_condicion_resultado` | `PedidoServiceTest.confirmar_sinStock_lanzaError` |
| Trigger | `<Objeto>Trigger` (uno por objeto) | `PedidoTrigger` |
| LWC | `camelCase` | `listaPedidos` |
| Flow | `Objeto_Momento_Proposito` | `Case_AfterSave_EscaladoPorSLA` |
| Permission set | `Dominio_Capacidad` | `Pedidos_Gestion`, `Pedidos_Lectura` |
| Custom permission | `Verbo_Objeto` | `Bypass_Validaciones` |
| Named Credential | `Sistema_Proposito` | `ERP_Stock` |
| Platform Event | `Hecho_En_Pasado__e` | `Pedido_Confirmado__e` |

Idioma: **inglés** para nombres de API y código (objetos, campos, clases, métodos, flows);
**español** para documentación, informes y comentarios. Los ejemplos de esta tabla y de las skills
están en español solo para ilustrar el patrón. Labels y textos de usuario, en Custom Labels.

## Apex

- Capas: selector (consultas) → service (negocio) → controller / trigger handler (entrada).
- Framework de triggers: **patrón Trigger Handler al estilo de Kevin O'Hara** — una clase base
  `TriggerHandler` (enrutado por contexto, bypass y control de recursión) y un
  `<Objeto>TriggerHandler` por objeto. Si el proyecto aún no la tiene, la primera feature con
  trigger la incluye en su diseño. Un trigger por objeto, sin lógica.
- Sharing declarado en toda clase; modo usuario por defecto.
- `Assert.*` en tests; `TestDataFactory` como única fuente de datos de prueba.
- ApexDoc en clases y métodos públicos.

## Declarativo

- Solo Flow. Before-save para el propio registro; after-save para el resto.
- Descripción obligatoria en objetos, campos, flows, permission sets y validation rules.
- El acceso se concede por permission set. No se versionan perfiles.

## Git

- Rama por feature: `feat/<id>-<slug>` (la crea `./hx start`).
- Commits del orquestador al cerrar cada fase: `<id>: <fase> — <resumen>`.
- A `main` solo por pull request.

## Formato

`npm run prettier` (Apex, XML, LWC) antes de entregar; `printWidth` 120.
