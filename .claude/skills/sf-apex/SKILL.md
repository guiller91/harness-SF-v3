---
name: sf-apex
description: Patrones de Apex para este harness — trigger handler, capas service/selector, bulkificación, modo usuario (CRUD/FLS), asíncrono y manejo de errores. Para quien escribe o revisa clases y triggers.
user-invocable: false
---

# Apex

Las convenciones del proyecto (`docs/conventions.md`) mandan sobre esta guía si difieren.

## Estructura

- **Un trigger por objeto**, sin lógica: `new AccountTriggerHandler().run();`. Si el proyecto ya
  tiene un framework de triggers, úsalo; si no, el diseño debe decir cuál se introduce.
- **Capas**
  - `XxxSelector` — todas las consultas SOQL/SOSL de un objeto. Devuelve listas/mapas tipados.
  - `XxxService` — lógica de negocio, transacciones. No consulta directamente: usa el selector.
  - `XxxController` — `@AuraEnabled` fino; valida entrada y delega en el service.
  - `XxxTriggerHandler` — enruta contextos del trigger a services.
- Clases pequeñas, un motivo para cambiar. Nada de "Utils" cajón de sastre.

## Bulkificación (no negociable)

Todo método se escribe para N registros (200 por lote de trigger; miles en batch).

```apex
// MAL: una consulta y un DML por registro
for (Opportunity o : opps) {
    Account a = [SELECT Id, Rating FROM Account WHERE Id = :o.AccountId];
    a.Rating = 'Hot';
    update a;
}
// BIEN: una consulta, un DML
Set<Id> accountIds = new Set<Id>();
for (Opportunity o : opps) { accountIds.add(o.AccountId); }
Map<Id, Account> accounts = new Map<Id, Account>(AccountSelector.byIds(accountIds));
List<Account> toUpdate = new List<Account>();
for (Opportunity o : opps) {
    Account a = accounts.get(o.AccountId);
    if (a != null && a.Rating != 'Hot') { a.Rating = 'Hot'; toUpdate.add(a); }
}
update as user toUpdate;
```
- Mapas por Id para cruzar colecciones; nunca bucles anidados sobre listas grandes.
- En triggers, actúa solo sobre los registros cuyo campo relevante **ha cambiado**
  (`Trigger.oldMap`), y evita la recursión con un guard estático por conjunto de Ids.
- Un mismo registro no puede ir dos veces en una lista de DML: deduplica con un `Map<Id, SObject>`.

## Seguridad: modo usuario por defecto

- Declara siempre el sharing: `public with sharing class …`. `inherited sharing` en utilidades y
  selectors reutilizables. `without sharing` solo con `// JUSTIFICACIÓN: …` y reflejado en el diseño.
- CRUD/FLS se aplica con **modo usuario**, no con comprobaciones manuales:
  ```apex
  List<Account> accs = [SELECT Id, Name FROM Account WHERE Id IN :ids WITH USER_MODE];
  insert as user nuevos;
  Database.update(registros, AccessLevel.USER_MODE);
  List<SObject> r = Database.queryWithBinds(soql, binds, AccessLevel.USER_MODE);
  ```
- Modo sistema (`WITH SYSTEM_MODE`, `as system`) solo cuando el diseño lo exige (p. ej. un contador
  interno que el usuario no puede editar), justificado y con la superficie mínima.
- `Security.stripInaccessible` cuando hay que devolver al cliente solo lo accesible sin fallar.
- SOQL dinámico: **bind variables** siempre. Nunca concatenes entrada del usuario.
- Todo `@AuraEnabled` es una puerta pública para cualquier usuario con acceso a la clase: valida
  parámetros y no confíes en que "el componente ya lo filtra".

## Asíncrono

| Necesidad | Herramienta |
|---|---|
| Trabajo en segundo plano, encadenable, con estado | `Queueable` (+ `Finalizer` para errores) |
| Callout tras un trigger | `Queueable` con `Database.AllowsCallouts` |
| Volumen alto (decenas de miles de registros o más) | `Batchable` (con `Database.Stateful` si acumulas) |
| Programado | `Schedulable` que lanza un Batch/Queueable |
| Desacoplar de la transacción / notificar a otros sistemas | Platform Events |

`@future` es legado: no para código nuevo. No encoles dentro de bucles.

## Errores

- Excepciones propias por dominio (`class PedidoException extends Exception {}`).
- Nunca `catch (Exception e) {}` vacío ni un simple `System.debug`. O se resuelve, o se relanza con contexto.
- DML parcial (`Database.insert(lista, false)`) solo si vas a tratar **cada** `SaveResult`.
- En `@AuraEnabled`, lanza `AuraHandledException` con un mensaje útil para el usuario, sin filtrar
  detalles internos.
- En triggers, `record.addError('mensaje')` sobre el registro culpable en vez de reventar el lote.

## Límites que condicionan el diseño

Por transacción: 100 SOQL (200 en asíncrono) · 150 DML · 50.000 filas leídas · 10.000 filas de DML ·
10 s de CPU (60 s asíncrono) · 100 callouts. El heap depende de la versión de API. **No los cites de
memoria en un diseño**: compruébalos en la documentación vigente o con `sf org list limits`.

## Estilo

- `Assert.areEqual(esperado, real, 'mensaje')` (clase `Assert`), no `System.assert*`.
- Navegación segura `?.` y `??` en vez de cadenas de `if != null`.
- Nada de Ids, nombres de perfil ni URLs en el código: Custom Metadata, Custom Labels, Named Credentials.
- Constantes con nombre; sin números mágicos. ApexDoc en clases y métodos públicos.
- `System.debug` no es logging: no lo dejes en el código final.
- Cada `.cls` lleva su `.cls-meta.xml` con la `apiVersion` del proyecto (`sfdx-project.json`).
