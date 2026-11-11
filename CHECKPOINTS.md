# CHECKPOINTS.md — Qué significa "hecho"

Una feature no está `done` porque alguien lo diga: lo está cuando `./hx close` la acepta. Este
documento describe los criterios de cada puerta. Los marcados con ⚙ los **comprueba la CLI o un
gate** (no se pueden saltar); los marcados con 👁 los comprueba un revisor, que deja veredicto.

> Protegido: los agentes no pueden editar este fichero. Cambiar el listón es decisión humana.

## Puerta 0 — Entrada (`draft → approved → design`)

- ⚙ Título, descripción, tipo, tamaño y al menos un criterio de aceptación.
- ⚙ Aprobación humana explícita (`./hx approve`).
- ⚙ Ninguna otra feature activa; dependencias cerradas.

## Puerta 1 — Diseño (`design → build`)

- ⚙ Existen los artefactos de diseño que exige el plan, con sus secciones:
  `requirements.md` (M, L) · `org-context.md` (M, L) · `design.md` (siempre).
- ⚙ `scope.files` fijado a partir del mapa de archivos del diseño.
- ⚙ Tamaño L: diseño aprobado por el humano.
- 👁 Cada criterio de aceptación se rastrea hasta un componente y un test (plan de pruebas).

## Puerta 2 — Construcción (`build → verify`)

- ⚙ Hay cambios de producto y **todos** están dentro del scope.
- ⚙ Cada implementer que exige el cambio ha dejado su informe (Resumen · Archivos · Verificación ·
  Pendiente).
- ⚙ Cada fichero lo escribió su rol dueño (propiedad aplicada por hook en cada escritura).

## Puerta 3 — Verificación (`verify → release`)

Gates, sobre el árbol de fuente **actual**:

- ⚙ **static** — Code Analyzer v5 sin violaciones de severidad ≤ umbral (Apex, LWC, Flows).
- ⚙ **apex-tests** — todos los tests en verde y cobertura **≥ 85 % por cada clase y trigger que
  toca la feature** (no la media de la org).
- ⚙ **lwc-tests** — Jest en verde y cada componente cambiado tiene tests.
- ⚙ **agent-validate** — cada authoring bundle de Agentforce compila.

Reviews con veredicto PASS sobre el árbol actual (según lo que toque el cambio):

- 👁 **qa-verifier** — cada `AC-n` verificado con evidencia y trazado en `acceptance.md`
  (⚙ todos los criterios aparecen; ninguno en FAIL ni NO VERIFICADO).
- 👁 **code-reviewer** — corrección frente al diseño, capas, bulk, errores, calidad de los tests.
- 👁 **security-reviewer** — sharing, modo usuario, inyección, mínimo privilegio, secretos.
- 👁 **performance-reviewer** — cuentas de SOQL/DML con 200 registros, selectividad, bloqueos.
- 👁 **accessibility-reviewer** — nombre accesible, teclado, foco, estados (si hay LWC).
- ⚙ Un informe con hallazgos BLOQUEANTES no puede registrar PASS.

Mínimos de producto que los revisores exigen siempre:

| Ámbito | Mínimo |
|---|---|
| Apex | Sharing declarado · modo usuario (`WITH USER_MODE`, `as user`) salvo excepción en el diseño · sin SOQL/DML en bucles · un trigger por objeto sin lógica · sin Ids ni secretos a fuego |
| Tests | Aserciones con mensaje · camino feliz, bulk de 200, negativo y permisos (`runAs`) · datos por `TestDataFactory` · nunca `SeeAllData=true` |
| Flows | Solo Flow · condiciones de entrada estrictas · sin operaciones en bucles · fault path real |
| LWC | LDS antes que Apex · estados de carga/vacío/error · accesible · sin `innerHTML` |
| Acceso | Permission sets de mínimo privilegio · nunca perfiles · nada de permisos de sistema amplios sin justificación en el diseño |
| Integración | Named/External Credentials · timeout y tratamiento de errores · reintentos asíncronos · idempotencia |

## Puerta 4 — Entrega (`release → done`)

- ⚙ `manifest/<id>/package.xml` con el contenido de la feature.
- ⚙ `release.md` con Contenido · Orden de despliegue · Pasos manuales · Rollback.
- ⚙ **deploy-validate** — validación check-only del manifest, con tests, en verde.
- ⚙ Gates y reviews de la puerta 3 siguen vigentes (el árbol no ha cambiado desde que se verificó).
- ⚙ Informe de `docs-writer` (arquitectura, ADR y changelog al día).
- ⚙ Cierre confirmado por el humano (`./hx close`), que añade la entrada a `progress/history.md`.

## Rework

Un gate en rojo o una review rechazada devuelven la feature a `build` (`./hx rework`). Tras la
corrección **se repiten gates y reviews**: la evidencia está atada al código exacto que se verificó.
Al superar `workflow.maxReworkLoops` la feature se bloquea y se escala al humano: iterar más no
arregla un diseño o unos criterios equivocados.

## Lo que el harness no garantiza

Los gates demuestran que el código compila, pasa sus tests, cumple las reglas estáticas y despliega
en una org de desarrollo. No sustituyen a las pruebas de aceptación de usuario, a la verificación
contra sistemas externos reales ni al criterio de quien aprueba. Lo no comprobado debe constar como
`NO VERIFICADO` en los informes y en `release.md`.
