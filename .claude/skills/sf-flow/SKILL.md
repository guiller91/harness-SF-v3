---
name: sf-flow
description: Cómo construir Flows como metadata en este harness — elegir tipo y momento (before/after save), condiciones de entrada, bulk, rutas de fallo, nombres, y cómo editar el XML sin romperlo.
user-invocable: false
---

# Flows

Solo **Flow**. Process Builder y Workflow Rules son legado: no se crean ni se amplían.

## Qué tipo de flow

| Necesidad | Tipo |
|---|---|
| Rellenar/corregir campos del **mismo** registro al guardar | Record-triggered **before save** (rápido, sin DML) |
| Crear/actualizar **otros** registros, enviar correos, llamar acciones | Record-triggered **after save** |
| Trabajo diferido o con callout tras guardar | Ruta asíncrona / programada del record-triggered |
| Interacción con el usuario | Screen flow |
| Lógica reutilizable llamada desde otros flows, Apex o agentes | Autolaunched (subflow) |
| Reaccionar a eventos | Platform-event-triggered |

Si necesita bucles complejos sobre grandes volúmenes, lógica con muchas ramas, control fino de
transacción o callouts con reintentos → **Apex**. No fuerces un flow imposible: dilo en tu informe
para que el arquitecto lo reconsidere.

## Reglas

- **Condiciones de entrada estrictas** y "solo cuando el registro se actualiza para cumplir las
  condiciones" cuando aplique. Un flow que se dispara en cada guardado es un coste para toda la org.
- **Nunca Get Records / Create / Update / Delete dentro de un Loop.** Recoge en una colección dentro
  del bucle y haz una sola operación fuera.
- **Ruta de fallo (fault path) en cada elemento que toca datos o llama acciones**, con un tratamiento
  real: registrar el error y/o informar al usuario. Nunca un fault path al vacío.
- Comprueba nulos y colecciones vacías antes de usarlas.
- Sin Ids ni nombres escritos a mano: Custom Metadata, Custom Labels o búsquedas por DeveloperName.
- Antes de crear un record-triggered flow, mira qué automatización existe ya en ese objeto
  (`docs/specs/<id>/org-context.md`). Fija el **orden de ejecución** (trigger order) si conviven
  varios; mejor pocos flows por objeto y momento, bien delimitados por su condición de entrada.
- Contexto de ejecución: un record-triggered corre en **contexto de sistema**. Si expone o modifica
  datos sensibles, que conste en el diseño y lo vea `security-reviewer`.
- Subflows para lo que se repite. Descripción en el flow y en cada elemento no trivial.

## Nombres

- Flow: `Objeto_Momento_Proposito` → `Case_AfterSave_EscaladoPorSLA`, `Account_BeforeSave_Normalizar`.
  Screen/autolaunched: `Dominio_Proposito`.
- Elementos: verbo + objeto (`Obtener_Contactos`, `Decidir_EsPrioritario`). Variables en `camelCase`,
  colecciones en plural.

## Trabajar con el XML (`flows/<ApiName>.flow-meta.xml`)

El XML de un flow es estricto y frágil. Procedimiento:

1. **No lo escribas de memoria.** Parte de un flow existente del mismo tipo: recupéralo
   (`sf project retrieve start --metadata Flow:<Nombre> --target-org <ORG>`) o usa otro del repo
   como plantilla.
2. Los elementos del **mismo tipo van juntos** (`<decisions>` con `<decisions>`, `<recordUpdates>`
   con `<recordUpdates>`…). Intercalarlos provoca errores de parseo al desplegar.
3. Cada elemento necesita `name` único, `label`, `locationX/Y` y un `connector` (o ser final).
   Revisa que no queden conectores apuntando a elementos que no existen.
4. `apiVersion` = la del proyecto. `status`: `Draft` mientras construyes, `Active` cuando funciona
   (salvo que el diseño diga otra cosa). Cada despliegue crea una **nueva versión**.
5. **Despliega a la org de desarrollo cada pocos cambios**: es la única validación real del XML.
   ```bash
   sf project deploy start --source-dir force-app/main/default/flows/Mi_Flow.flow-meta.xml --target-org <ORG>
   ```
6. Compruébalo funcionando: crea/actualiza un registro con `sf data` o Apex anónimo y consulta el
   resultado. Pega la evidencia en tu informe.

## Pruebas

- Los flows record-triggered se prueban con **tests Apex** que provocan el DML y asertan el efecto
  (los escribe `test-engineer`; dile en tu informe qué casos cubrir, incluido el bulk de 200).
- Code Analyzer incluye reglas de Flow: `./hx gate run static` antes de entregar.
- Activar flows al desplegar en producción puede exigir cobertura de tests de flow: anótalo como
  paso de release si aplica.
