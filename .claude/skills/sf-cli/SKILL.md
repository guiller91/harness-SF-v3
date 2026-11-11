---
name: sf-cli
description: Comandos de Salesforce CLI (sf v2) verificados para este harness — deploy, retrieve, tests, consultas, Code Analyzer y manifests — con las reglas de seguridad de orgs. Úsala antes de ejecutar cualquier comando sf.
user-invocable: false
---

# Salesforce CLI en el harness

`<ORG>` = `org.targetOrgAlias` de `harness.config.json` (míralo con `./hx status`). **Siempre
explícito**: el harness bloquea los comandos que dependen de la org por defecto.

Si dudas de un flag: `sf <comando> --help`. No inventes flags; la CLI cambia cada semana.
`sfdx force:*` y `sf scanner` están retirados: no existen.

## Desplegar a la org de desarrollo (solo implementers, solo en build)

```bash
# Lo que acabas de escribir (rápido, sin tests)
sf project deploy start --source-dir force-app/main/default/classes/MiClase.cls --target-org <ORG>
sf project deploy start --source-dir force-app/main/default/objects/Mi_Objeto__c --target-org <ORG>
# Varios tipos a la vez
sf project deploy start --metadata ApexClass:MiClase --metadata ApexTrigger:MiTrigger --target-org <ORG>
# Ensayo sin guardar (permitido a cualquier rol)
sf project deploy start --source-dir force-app --dry-run --target-org <ORG>
```
Un deploy que falla deja la org como estaba. Lee el error completo: casi siempre es una
dependencia que falta (despliega antes el objeto/campo) o un nombre de API mal escrito.

## Traer metadata de la org

```bash
sf project retrieve start --metadata Flow:Mi_Flow --target-org <ORG>
sf project retrieve start --metadata "CustomObject:Account" --target-org <ORG>
sf org list metadata --metadata-type Flow --target-org <ORG>          # qué hay
sf org list metadata-types --target-org <ORG>
```

## Inspeccionar (solo lectura)

```bash
sf sobject describe --sobject Account --target-org <ORG>               # campos, relaciones, record types
sf sobject list --sobject custom --target-org <ORG>
sf data query --query "SELECT Id, Name FROM Account LIMIT 5" --target-org <ORG>
# Tooling API: triggers, flows activos, clases, validation rules…
sf data query --use-tooling-api --target-org <ORG> \
  --query "SELECT Name, TableEnumOrId, Status FROM ApexTrigger"
sf data query --use-tooling-api --target-org <ORG> \
  --query "SELECT DeveloperName, ActiveVersion.VersionNumber, ProcessType, TriggerType FROM FlowDefinition"
sf org list limits --target-org <ORG>
```

## Tests

```bash
./hx gate run apex-tests        # el gate oficial: todos los tests + cobertura por clase de lo cambiado
# Iterar rápido sobre una clase mientras desarrollas:
sf apex run test --class-names MiClaseTest --code-coverage --result-format human --wait 20 --target-org <ORG>
sf apex run test --tests MiClaseTest.miMetodo --result-format human --wait 20 --target-org <ORG>
npx sfdx-lwc-jest -- --ci                                             # Jest (local, sin org)
npx sfdx-lwc-jest -- miComponente                                      # un componente
```

## Análisis estático (local, sin org)

```bash
./hx gate run static                                                   # el gate oficial
sf code-analyzer run --workspace force-app --target force-app/main/default/classes/MiClase.cls --view detail
sf code-analyzer rules --rule-selector pmd:Security --view table       # qué reglas hay
```
Severidad: 1 crítica … 5 informativa. El gate falla en ≤ `quality.analyzer.severityThreshold`.

## Manifests (release-manager)

```bash
sf project generate manifest --source-dir <ruta1> --source-dir <ruta2> --output-dir manifest/<id>
sf project generate manifest --metadata ApexClass:Vieja --type destroy --output-dir manifest/<id>
sf project deploy validate --manifest manifest/<id>/package.xml --test-level RunLocalTests --target-org <ORG>
```

## Prohibido a los agentes (lo bloquea el harness)

- Credenciales y sesión: `sf org login|logout`, `sf org display`, `--url-only`, `sf config set`, `sf alias`.
- Cualquier org que no sea la de desarrollo (y la de validación, solo en check-only). Alias de producción: nunca.
- Modificar la org fuera de build o desde un rol que no sea implementer.
- Instalar paquetes o plugins, crear o refrescar sandboxes, crear usuarios.
