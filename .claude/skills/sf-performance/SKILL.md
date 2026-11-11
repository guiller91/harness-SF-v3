---
name: sf-performance
description: Rendimiento y límites de gobierno en Salesforce — selectividad de SOQL, patrones bulk, coste de automatización, bloqueos, volumen de datos y rendimiento de LWC. Guía para diseñar y lista de comprobación para revisar.
user-invocable: false
---

# Rendimiento y límites

En Salesforce el rendimiento no es una optimización: superar un límite **tumba la transacción
entera**. Piensa siempre en el peor caso realista: 200 registros por lote, integraciones masivas,
el objeto dentro de dos años.

## Límites por transacción (comprueba los vigentes)

100 consultas SOQL (200 asíncrono) · 150 sentencias DML · 50.000 filas leídas · 10.000 filas de DML ·
10 s CPU (60 s asíncrono) · 100 callouts · heap según versión de API. Verifica en la documentación
de "Execution Governors and Limits" de la release actual; no bases un diseño en cifras de memoria.

Todo lo que corre en la misma transacción **comparte** el presupuesto: tu trigger, los flows del
objeto, validation rules, roll-ups, y las automatizaciones de los objetos que tú actualizas.

## SOQL

- **Selectiva**: filtra por campos indexados (Id, Name, External Id, lookups/master-detail,
  campos únicos, CreatedDate/SystemModstamp). Un filtro no selectivo sobre un objeto grande acaba
  en error en triggers y en lentitud en todo lo demás.
- Evita lo que impide usar índices: `!=`, `NOT IN`, comodín inicial en `LIKE '%x'`, filtros sobre
  fórmulas no deterministas, comparaciones con `null` en campos no indexados.
- Trae **solo** los campos y filas necesarios; `LIMIT` cuando el caso lo permite.
- Agrega en la base de datos (`COUNT()`, `GROUP BY`) en vez de contar en Apex.
- Subconsultas padre-hijo con cabeza: un padre con miles de hijos revienta filas y heap.
- Recorre resultados grandes con SOQL for-loop (`for (List<Account> lote : [SELECT …])`) o con Batch.

## Apex

- Consultas y DML **fuera de bucles**; también los que están escondidos en métodos llamados desde un bucle.
- Cruza con `Map<Id, …>` / `Set<Id>`; un bucle anidado sobre dos listas de 200 son 40.000 iteraciones.
- En triggers: filtra pronto (¿cambió el campo que me importa?) y sal si no hay nada que hacer.
- Evita la recursión: guard estático por Ids ya procesados.
- No serialices ni copies colecciones grandes sin necesidad; cuidado con `String +=` en bucles.
- Trabajo pesado → asíncrono (Queueable/Batch) con tamaño de lote razonado.
- Configuración que se lee a menudo → Custom Metadata (no gasta SOQL) o Platform Cache.

## Automatización declarativa

- Before-save flow para tocar el mismo registro (sin DML extra). After-save solo si hace falta.
- Sin Get/Create/Update dentro de Loops. Condiciones de entrada estrictas.
- Cuenta lo que ya hay en el objeto (`org-context.md`): cada flow y trigger añadido se paga en
  **todas** las transacciones del objeto.

## Bloqueos y volumen

- Actualizar hijos bloquea al padre en master-detail y roll-ups: cargas en paralelo sobre hijos del
  mismo padre producen `UNABLE_TO_LOCK_ROW`. Ordena por padre o serializa.
- Desbalance (skew): un Account con decenas de miles de hijos, un propietario con cientos de miles
  de registros, un lookup al que apuntan casi todos. Degrada sharing y provoca bloqueos.
- `FOR UPDATE` solo cuando haya una condición de carrera real y por el menor tiempo posible.

## LWC

- LDS y `cacheable=true` para lecturas; no repitas la misma llamada en varios componentes.
- Evita cascadas de wires dependientes; trae lo relacionado en una llamada.
- Pagina / scroll infinito; debounce en búsquedas; no renderices cientos de filas con componentes
  pesados; carga perezosa de pestañas y secciones.

## Lista de comprobación del revisor

Hallazgos con `ruta:línea` y **el escenario que lo rompe** (p. ej. "con 200 Opportunities de 200
Accounts distintos son 200 consultas").

- [ ] ¿Alguna consulta, DML, callout o encolado dentro de un bucle — directo o vía método?
- [ ] Para cada consulta: ¿por qué campo filtra?, ¿es selectiva con el volumen previsto?, ¿cuántas
      filas puede devolver en el peor caso?
- [ ] ¿Cuántas SOQL y DML consume la transacción con 200 registros? (cuéntalas)
- [ ] ¿Bucles anidados sobre colecciones que crecen con los datos?
- [ ] ¿El trigger/flow actúa sobre registros que no han cambiado en lo relevante? ¿Hay recursión?
- [ ] ¿Qué otra automatización se dispara por los DML de esta feature y cuánto cuesta?
- [ ] ¿Lo síncrono debería ser asíncrono (o al revés)? ¿Tamaño de lote del Batch razonado?
- [ ] ¿Riesgo de bloqueo de filas o de skew con el modelo de datos propuesto?
- [ ] ¿Los tests incluyen el caso de 200 registros **y** asertan que funciona (no solo que no explota)?
- [ ] LWC: ¿llamadas duplicadas, listas sin paginar, wires en cascada?

BLOQUEANTE: superará un límite en un escenario realista; consulta no selectiva sobre objeto grande
en un trigger; recursión no controlada. MAYOR: consumo de límites innecesariamente alto, riesgo de
bloqueos. MENOR: micro-optimizaciones.
