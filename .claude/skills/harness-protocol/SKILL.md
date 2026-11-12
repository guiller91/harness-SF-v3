---
name: harness-protocol
description: Protocolo de trabajo dentro del harness — qué leer antes de empezar, qué puede tocar cada rol, cómo se escribe el informe de traspaso y cómo se demuestra que algo funciona. Lo cargan todos los agentes.
user-invocable: false
---

# Protocolo del harness

Trabajas dentro de un harness: un sistema de reglas que se **aplican con hooks**, no que se
recomiendan. Si intentas saltarte una, la acción se bloquea y te dice por qué. No busques rodeos:
un bloqueo es información — o estás fuera de tu rol, o falta un paso previo.

## 1. Antes de escribir nada

1. `./hx status` — feature activa, fase y siguiente paso.
2. Lee `docs/specs/<id>/design.md` (y `requirements.md`, `org-context.md` si existen). El diseño manda.
3. Lee los informes previos en `progress/<id>/` — sobre todo las secciones **Pendiente**.
4. Lee `docs/conventions.md` si vas a escribir código o metadata.

Tu contexto empieza vacío: todo lo que necesitas saber está en disco. Si no está, es un hueco
del diseño — anótalo en tu informe en vez de inventártelo.

## 2. Qué puedes tocar

| Clase de rol | Escribe | Cuándo |
|---|---|---|
| Diseño | su artefacto en `docs/specs/<id>/` | design (y build, para aclarar) |
| Implementer | **solo** su tipo de metadata, **dentro del scope** de la feature | build |
| Revisor | nada de producto; su informe y su veredicto | verify |
| Entrega | `manifest/<id>/`, documentación | release |

- La matriz exacta está en `harness/roles.json`. Un fichero que no es tuyo **no se edita**: se
  apunta en tu informe para su dueño.
- Fuera del scope aprobado no se escribe. Si hace falta más alcance, lo decide el orquestador.
- Nadie toca el propio harness (`.claude/`, `harness/`, `hx`, `CHECKPOINTS.md`, `feature_list.json`…).
- El estado de la feature solo lo cambia el orquestador con `./hx`.

## 3. La única org

Solo existe para ti la org de desarrollo (`org.targetOrgAlias` en `harness.config.json`).
Todo comando `sf` que toque una org lleva `--target-org <ese alias>` explícito. Nunca credenciales,
nunca `sf org display` (imprime el token), nunca otra org.

## 4. Evidencia, no opiniones

- "Debería funcionar" no es un resultado. Ejecuta el comando y pega la salida relevante.
- Si no pudiste ejecutar algo, escríbelo tal cual: **NO VERIFICADO: <motivo>**. Jamás lo des por bueno.
- Los gates oficiales se ejecutan con `./hx gate run <gate>`; dejan evidencia atada al hash del
  árbol de fuente. Si el código cambia, la evidencia caduca sola.
- Puedes usar `./hx gate run static` (y los demás) para autocomprobarte antes de entregar.

## 5. Informe de traspaso (obligatorio)

Escribe `progress/<id>/<tu-rol>.md`. El harness no te deja terminar sin él. Si ya existe de una
vuelta anterior, **añade** una sección nueva arriba con la fecha; no borres el historial.

**Implementers y entrega**
```markdown
# <rol> — <id>
## Resumen
Qué se ha construido y por qué así (2-5 líneas). Desviaciones respecto al diseño, si las hay.
## Archivos
- `ruta` — creado/modificado/borrado — qué contiene
## Verificación
Comandos ejecutados y su resultado real (deploy a la org de desarrollo, tests, gate estático…).
## Pendiente
Lo que queda para otros roles, riesgos, dudas, falsos positivos de la revisión rápida, peticiones
de ampliación de scope. Si no hay nada: "Nada."
```

**Revisores**
```markdown
# <rol> — <id>
## Veredicto
PASS | FAIL — una frase.
## Hallazgos
- [BLOQUEANTE] `ruta:línea` — qué está mal — por qué importa — cómo se arregla
- [MAYOR] …
- [MENOR] …
(Sin hallazgos: "Ninguno." y explica qué comprobaste.)
```
Severidades: **BLOQUEANTE** = no puede salir así (fallo funcional, seguridad, límite de gobierno,
pérdida de datos, criterio de aceptación incumplido). **MAYOR** = debe corregirse en esta feature
salvo decisión explícita del humano. **MENOR** = mejora; no bloquea.
Con algún BLOQUEANTE el veredicto es FAIL (la CLI lo comprueba). Después:
`./hx verdict <tu-rol> pass|fail --note "resumen en una línea"`.

## 6. Cómo lanzar comandos (menos interrupciones al humano)

Cada comando "raro" le abre al humano un prompt de permiso. Para no hacerlo perder tiempo:

- **Nunca antepongas `cd`.** El directorio de trabajo ya es la raíz del proyecto; `cd "…" && comando` dispara
  una confirmación de seguridad de Claude Code.
- **Un comando por llamada**, sin cadenas largas con `;` o `&&` que mezclen lecturas y listados.
- **Para leer ficheros usa la herramienta Read**, no `cat`/`head`/`grep` en Bash. Para buscar, Grep y Glob.
- **Usa solo Bash.** La herramienta PowerShell está denegada en este proyecto.
- **No hagas `sf`/`git` "por curiosidad"**: lo que necesitas saber del estado sale de `./hx status` y `./hx plan`.

## 7. Cuando algo no encaja

- **Bloqueado por un hook** → lee el motivo; suele decir qué hacer. No lo esquives.
- **El diseño es imposible o está mal** → para, explícalo en tu informe (Pendiente) y termina. No
  rediseñes por tu cuenta.
- **Falta información de negocio** → no la supongas: pregunta vía informe; el orquestador habla
  con el humano.
- **Un comando falla y no sabes por qué** → pega el error literal. No reintentes a ciegas más de
  dos veces.
