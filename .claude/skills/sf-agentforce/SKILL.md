---
name: sf-agentforce
description: Construir agentes de Agentforce como código con Agentforce DX — Agent Script en authoring bundles, acciones (Apex invocable, Flow, prompt templates), validación, publicación y tests. Úsala para cualquier metadata de agente.
user-invocable: false
---

# Agentforce (Agentforce DX)

> Agentforce cambia en cada release y parte de lo que sabes puede estar caducado. **Antes de
> escribir**: `sf agent --help`, `sf agent generate --help` y la documentación vigente de
> Agentforce DX / Agent Script. Si un comando o una sintaxis de esta guía no coincide con lo que
> ves, manda lo que ves — y anótalo en tu informe.

## Qué es de quién

| Pieza | Dónde | Dueño |
|---|---|---|
| Definición del agente (Agent Script) | `aiAuthoringBundles/<ApiName>/` | `agentforce-developer` |
| Metadata generada al publicar (`bots/`, `genAiPlannerBundles/`, `genAiPlugins/`, `genAiFunctions/`) | sus carpetas | `agentforce-developer` (no se edita a mano si viene de un bundle) |
| Prompt templates | `genAiPromptTemplates/` | `agentforce-developer` |
| Tests del agente | `aiEvaluationDefinitions/` | `agentforce-developer` |
| Acciones Apex (`@InvocableMethod`) | `classes/` | `apex-developer` |
| Acciones Flow | `flows/` | `flow-developer` |
| Acceso del usuario del agente a objetos, campos y clases | `permissionsets/` | `security-admin` |

Tú orquestas el agente; la lógica determinista vive en Apex/Flow, que construyen otros roles **antes**
que tú. Si falta una acción, no la escribas: pídela en tu informe.

## Flujo de trabajo verificado (CLI)

```bash
sf agent generate agent-spec ...                 # spec YAML del agente (opcional, punto de partida)
sf agent generate authoring-bundle ...           # crea aiAuthoringBundles/<ApiName>/ con el .agent
# … editar el Agent Script …
sf agent validate authoring-bundle --api-name <ApiName> --target-org <ORG>   # compila; es el gate
sf agent publish authoring-bundle  --api-name <ApiName> --target-org <ORG>   # publica en la org de desarrollo
sf agent preview --api-name <ApiName> --target-org <ORG>                     # conversar con él
sf agent generate test-spec ...                  # spec de tests
sf agent test create --spec <spec> --api-name <Test> --target-org <ORG>
sf agent test run --api-name <Test> --wait 20 --result-format json --target-org <ORG>
```
Usa `--help` en cada uno para los flags exactos. `./hx gate run agent-validate` compila todos los
bundles tocados por la feature. **Activar** un agente (`sf agent activate`) lo decide el diseño;
en entornos superiores es un paso de release, no tuyo.

## Diseñar el agente

- **Topics/subagentes acotados**: cada uno, un trabajo claro con su propio alcance y sus acciones.
  Un topic que "hace de todo" enruta mal. Describe **cuándo aplica y cuándo no**.
- **Instrucciones**: concretas, en positivo, verificables. Lo que deba cumplirse siempre
  (validaciones, cálculos, permisos, orden de pasos) **no va en instrucciones**: va en la lógica
  determinista del Agent Script o en la acción.
- **Pocas acciones por topic** y bien diferenciadas; si dos se parecen, el agente las confundirá.
- **Datos**: el agente actúa con los permisos de su usuario. Mínimo privilegio; nada de dar acceso
  amplio "para que funcione".
- Define qué hace cuando **no sabe o no puede**: pedir el dato, escalar a una persona, rechazar.
- Sin datos sensibles en instrucciones ni en ejemplos.

## Acciones: el contrato es la descripción

El modelo elige y rellena una acción leyendo sus etiquetas y descripciones. Para el autor de la
acción (díselo en tu informe si no las cumple):

```apex
public with sharing class ConsultarEstadoPedido {
    public class Entrada {
        @InvocableVariable(label='Número de pedido' description='Número visible para el cliente, p. ej. P-000123' required=true)
        public String numeroPedido;
    }
    public class Salida {
        @InvocableVariable(label='Estado' description='Estado actual: Borrador, Confirmado, Enviado o Entregado')
        public String estado;
        @InvocableVariable(label='Mensaje' description='Explicación si no se encontró el pedido; vacío si todo fue bien')
        public String mensaje;
    }
    @InvocableMethod(label='Consultar estado de un pedido'
                     description='Devuelve el estado de UN pedido a partir de su número. Úsala cuando el cliente pregunta por dónde va su pedido. No modifica datos.')
    public static List<Salida> consultar(List<Entrada> entradas) { /* bulk, modo usuario */ }
}
```
- Entradas y salidas **pequeñas y con nombre de negocio**; nunca devuelvas el registro entero.
- La descripción dice qué hace, cuándo usarla, cuándo **no**, y si modifica datos.
- Errores como **salida legible** (`mensaje`), no como excepción sin contexto.
- Bulkificada, `with sharing`, modo usuario, idempotente si modifica.

## Tests del agente

- Cubre por topic: enrutado correcto, acción correcta con parámetros correctos, respuesta útil; y
  los **negativos**: fuera de alcance, datos que faltan, intento de saltarse una regla.
- Un test de agente no es determinista como uno de Apex: fija expectativas sobre topic y acción,
  y criterios claros sobre la respuesta. Si un caso es inestable, anótalo — no lo borres.
- Pega en tu informe el resultado real de `sf agent test run`. Sin ejecución: `NO VERIFICADO`.
