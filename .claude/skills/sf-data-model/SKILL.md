---
name: sf-data-model
description: Modelo de datos como metadata en formato source — objetos, campos, relaciones, validation rules, record types, Custom Metadata — con convenciones de nombres y decisiones que no tienen vuelta atrás fácil.
user-invocable: false
---

# Modelo de datos

## Estructura en source format

```
objects/Pedido__c/
  Pedido__c.object-meta.xml
  fields/Estado__c.field-meta.xml
  validationRules/Importe_Positivo.validationRule-meta.xml
  recordTypes/Mayorista.recordType-meta.xml
objects/Account/fields/Segmento__c.field-meta.xml      # campo custom en objeto estándar
customMetadata/Regla_Descuento.Mayorista.md-meta.xml   # registros de Custom Metadata
```
List views, compact layouts y botones (carpetas dentro de `objects/`) son de `admin-configurator`.
Platform Events (`__e`) son de `integration-developer`.

## Antes de crear nada

- **¿Ya existe?** Revisa `docs/specs/<id>/org-context.md` y la org
  (`sf sobject describe --sobject <Objeto> --target-org <ORG>`). Reutiliza campos y objetos
  estándar antes de crear custom.
- Lo que cuesta deshacer se decide en el diseño, no aquí: tipo de relación, tipo de campo,
  sharing model del objeto, nombres de API. Si el diseño no lo fija, **pregunta en tu informe**.

## Decisiones

| Decisión | Criterio |
|---|---|
| Master-detail vs Lookup | MD si el hijo no tiene sentido sin el padre (hereda propietario y sharing, permite roll-ups, borrado en cascada; máx. 2 por objeto). Lookup si es una asociación opcional. |
| Picklist vs objeto de referencia | Picklist si son pocos valores estables; objeto o Custom Metadata si tienen atributos o cambian a menudo. Valores compartidos → Global Value Set. |
| Custom Metadata vs Custom Setting vs Label | Configuración desplegable y consultable sin gastar SOQL → **Custom Metadata**. Valor por usuario/perfil → Custom Setting jerárquico. Texto traducible → Custom Label. |
| Fórmula vs campo calculado por automatización | Fórmula si se deriva del propio registro o del padre; no si hay que filtrar, indexar o agregar por él. |
| Record types | Solo si cambian proceso, picklists o layout. No como etiqueta. |
| External Id | Todo objeto que se integre o se cargue desde fuera necesita uno (único). |

## Reglas

- **Nombres de API**: `PascalCase_Con_Guiones__c`, sin abreviaturas crípticas, en el idioma que fije
  `docs/conventions.md`. El nombre de API es para siempre; el label se puede cambiar.
- **Todo campo lleva `description`** (para qué sirve, quién lo alimenta) y, si lo ve un usuario,
  `inlineHelpText`.
- `required` a nivel de campo solo si es verdad en **todos** los procesos e integraciones; si no,
  validation rule o layout.
- **Sharing model** del objeto (`sharingModel`, `externalSharingModel`) explícito y según diseño:
  por defecto el más restrictivo que permita el caso.
- **Validation rules**: mensaje claro y accionable, asociado al campo; nombre descriptivo; `active`.
  Prevé un bypass controlado para cargas e integraciones mediante **Custom Permission**
  (`NOT($Permission.Bypass_Validaciones)`), nunca por nombre de perfil o de usuario.
- No cambies el tipo de un campo con datos ni reduzcas longitudes sin que el diseño lo contemple.
- Borrar un campo u objeto no es borrar su fichero: requiere `destructiveChanges` — avisa a
  `release-manager` en tu informe.
- Volumen: si un objeto va a superar cientos de miles de registros, que el diseño indique qué campos
  se filtran (candidatos a índice / External Id) y evita lookups con desbalance extremo (un padre
  con decenas de miles de hijos).

## El acceso no es tuyo

Crear un campo no da acceso a nadie. Los permisos (objeto, campo, record type) los concede
`security-admin` en permission sets. En tu informe (Pendiente) lista **cada objeto y campo nuevo**
y quién debería leerlo o editarlo según el diseño. Sin FLS, los tests con `runAs` y el modo usuario
fallarán.

## Verificación

```bash
sf project deploy start --source-dir force-app/main/default/objects/Pedido__c --target-org <ORG>
sf sobject describe --sobject Pedido__c --target-org <ORG>
```
Pega en tu informe el resultado del deploy y confirma que campos y relaciones existen en la org.
