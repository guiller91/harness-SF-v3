---
name: sf-release
description: Preparar la entrega de una feature — manifest (package.xml) con exactamente lo que cambió, destructive changes, validación check-only, pasos manuales, orden de despliegue y plan de rollback.
user-invocable: false
---

# Entrega

En este harness los agentes **no promocionan** a entornos superiores. Tu trabajo es dejar un
artefacto que un pipeline o una persona pueda desplegar sin preguntar nada: `manifest/<id>/` y
`docs/specs/<id>/release.md`. El gate `deploy-validate` valida exactamente ese manifest.

## 1. Inventario del cambio

```bash
./hx status                                   # tipos de cambio y árbol verificado
git diff --name-status <base_commit>          # A/M/D/R respecto al commit base de la feature
git status --porcelain                         # lo que aún no está commiteado
```
El `base_commit` está en `feature_list.json`. Cruza el resultado con la sección **Archivos** de los
informes de `progress/<id>/`: si algo cambió y nadie lo declaró, o al revés, es un hallazgo.

## 2. Manifest

```bash
sf project generate manifest \
  --source-dir force-app/main/default/classes/PedidoService.cls \
  --source-dir force-app/main/default/objects/Pedido__c \
  --output-dir manifest/<id>
```
- Una `--source-dir` por fichero o carpeta **cambiado** (añadido o modificado). No metas el
  packageDir entero: el manifest de una feature contiene la feature.
- Revisa el `package.xml` resultante: miembros con nombre (sin `*`), versión de API del proyecto,
  tests incluidos, y nada que no sea de la feature.
- Incluye las dependencias que el destino no tendrá (campos de los que depende una clase, etc.).

## 3. Borrados

Los ficheros eliminados o renombrados no se borran solos en el destino:
```bash
sf project generate manifest --metadata ApexClass:ClaseVieja --metadata CustomField:Pedido__c.Viejo__c \
  --type destroy --output-dir manifest/<id>
```
Genera `destructiveChanges.xml`. El gate lo aplica como **post**-destructive (primero despliega lo
nuevo, luego borra). Borrar campos u objetos **destruye datos**: debe estar pedido en el diseño y
aparecer destacado en `release.md`.

## 4. Validar

```bash
./hx gate run deploy-validate
```
Check-only con tests contra la org de validación (`org.validationOrgAlias`; si no hay, la de
desarrollo). Si falla, **no lo arregles tú**: es código de producto → informa; el orquestador hará
rework. Un job validado puede desplegarse después con quick deploy; eso lo hace el pipeline/humano.

## 5. `docs/specs/<id>/release.md`

```markdown
# Release — <id> <título>
## Contenido
Tabla: componente · tipo · acción (nuevo/modificado/borrado). Manifest: manifest/<id>/package.xml
## Orden de despliegue
Pre-requisitos en destino (features activadas, paquetes, datos de referencia) y orden si hay
dependencias con otras features.
## Pasos manuales
Antes y después del despliegue, numerados y con responsable: asignar permission sets, introducir
secretos de Named/External Credentials, activar flows o agentes, cargar datos, programar jobs…
Si no hay: "Ninguno."
## Rollback
Cómo se vuelve atrás **de verdad**: qué se redespliega (versión anterior desde git), qué se
desactiva (flow, permission set, custom permission), qué pasa con los datos creados o migrados,
y qué NO tiene vuelta atrás.
## Riesgos y verificación post-despliegue
Qué comprobar en destino y cómo (consulta, pantalla, test) para dar el despliegue por bueno.
```

Reglas:
- Nada de "rollback: revertir el commit". Un campo borrado, datos transformados o un correo
  enviado no se revierten con git: dilo.
- Los secretos no se escriben: se indica dónde se introducen.
- Si la feature toca perfiles, layouts asignados por perfil o ajustes de la org que no viajan bien
  por metadata, va como paso manual explícito.
