---
name: sf-security
description: Modelo de seguridad de Salesforce aplicado al harness — modo usuario (CRUD/FLS), sharing, permission sets de mínimo privilegio, inyección SOQL, XSS, secretos e integraciones. Guía para construir y lista de comprobación para revisar.
user-invocable: false
---

# Seguridad

Principio: **el código nunca da más acceso del que el usuario ya tiene**, salvo decisión explícita,
justificada y acotada en el diseño.

## 1. Acceso a datos en Apex

- **Sharing declarado** en toda clase: `with sharing` por defecto; `inherited sharing` en
  utilidades; `without sharing` solo con `// JUSTIFICACIÓN:` y en el diseño, en la clase más
  pequeña posible (no en el controller entero).
- **CRUD/FLS en modo usuario**: `WITH USER_MODE` en SOQL, `insert as user` / `AccessLevel.USER_MODE`
  en DML y en `Database.query*`. El modo sistema es la excepción documentada.
- Lo que cruza al cliente (`@AuraEnabled`, REST, acciones invocables) devuelve **solo** los campos
  necesarios y accesibles (`Security.stripInaccessible` cuando corresponda).
- Cada `@AuraEnabled`, `@RestResource`, `@InvocableMethod` y `global` es **superficie de ataque**:
  valida tipos, rangos y pertenencia (¿este usuario puede operar sobre *este* registro?). No te
  fíes de Ids que llegan del cliente.

## 2. Inyección

- **SOQL/SOSL dinámico**: bind variables (`:var`, `Database.queryWithBinds`). Si de verdad hay que
  componer nombres de campo u objeto, valídalos contra `Schema` (lista blanca), no los escapes.
- **XSS en LWC**: nada de `innerHTML` ni HTML construido con datos. En Visualforce/Aura heredados,
  codifica la salida.
- **Open redirect**: no navegues a URLs que vienen de parámetros sin validarlas.

## 3. Permisos: mínimo privilegio

- El acceso se concede con **permission sets** (agrupados en permission set groups por función),
  **nunca** editando perfiles. No se versionan perfiles.
- Un permission set por capacidad (`Pedidos_Gestion`, `Pedidos_Lectura`), con lo justo: objetos
  (CRUD), campos (FLS), clases Apex, record types, custom permissions, tabs.
- Prohibido sin justificación explícita en el diseño: `ModifyAllData`, `ViewAllData`,
  `viewAllRecords` / `modifyAllRecords`, `AuthorApex`, `CustomizeApplication`, `ManageUsers`.
- Lectura ≠ edición: no des `editable` donde basta `readable`.
- **Custom Permissions** para capacidades y bypass controlados
  (`FeatureManagement.checkPermission('Nombre')`, `$Permission.Nombre`), no nombres de perfil.
- Acceso a registros: OWD lo más restrictivo posible y abre con sharing rules / equipos / jerarquía.
  Sharing manual o Apex managed sharing solo si el diseño lo pide.
- Usuario invitado (sitios públicos): acceso mínimo, siempre `with sharing`, sin datos sensibles.

## 4. Secretos e integraciones

- **Ningún secreto en el repo**: ni en Apex, ni en Custom Settings/Labels/Metadata sin proteger, ni
  en tests. Endpoints y credenciales → **Named Credentials + External Credentials**.
- No registres (`System.debug`, logs, mensajes de error) tokens, contraseñas ni datos personales.
- Callouts solo a hosts declarados; TLS; valida y limita lo que entra de fuera.
- Los mensajes de error al usuario no revelan internos (consultas, stack traces, nombres de clase).

## 5. Datos personales

Identifica campos con datos personales o sensibles en el diseño; minimiza lo que se copia, muestra
o exporta. Considera cifrado (Shield) y field history solo si el diseño lo pide.

## Lista de comprobación del revisor

Para **cada** fichero cambiado; hallazgos con `ruta:línea`:

- [ ] ¿Toda clase declara sharing? ¿Cada `without sharing` está justificado y acotado?
- [ ] ¿Toda consulta y DML alcanzable desde un punto de entrada (`@AuraEnabled`, REST, invocable,
      trigger con datos de usuario) va en modo usuario o tiene excepción documentada?
- [ ] ¿Hay SOQL dinámico con concatenación? ¿De dónde viene cada fragmento?
- [ ] ¿Los puntos de entrada validan parámetros y pertenencia del registro?
- [ ] ¿Se devuelven al cliente campos innecesarios o sensibles?
- [ ] LWC: ¿`innerHTML`, `eval`, URLs sin validar, datos sensibles en el cliente?
- [ ] Permission sets: ¿algún permiso de sistema amplio? ¿más CRUD/FLS del que pide el diseño?
      ¿todo lo nuevo (objetos, campos, clases, tabs) tiene acceso concedido a quien debe y **solo** a
      quien debe?
- [ ] ¿Hay perfiles en el cambio? (No debe haberlos.)
- [ ] Flows en contexto de sistema: ¿pueden exponer o modificar datos que el usuario no debería?
- [ ] ¿Secretos, endpoints, Ids o usuarios escritos a mano? ¿Datos sensibles en logs?
- [ ] ¿Los tests prueban el acceso **negativo** (`System.runAs` sin el permission set)?
- [ ] Ejecuta `sf code-analyzer run --rule-selector Security --workspace force-app --target <ficheros>`
      y revisa también lo que el umbral del gate deja pasar.

BLOQUEANTE: exposición o modificación de datos sin autorización, inyección, secreto en el repo,
permiso de sistema amplio sin justificar. MAYOR: modo sistema evitable, validación de entrada
ausente, falta el test negativo. MENOR: endurecimientos opcionales.
