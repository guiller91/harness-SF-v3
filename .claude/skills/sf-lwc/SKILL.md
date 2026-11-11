---
name: sf-lwc
description: Patrones de Lightning Web Components para este harness — datos (LDS antes que Apex, wire vs imperativo), estados de carga y error, eventos, accesibilidad, seguridad y metadatos del componente.
user-invocable: false
---

# Lightning Web Components

## Datos: de menos a más código

1. **Componentes base y LDS**: `lightning-record-form`, `lightning-record-edit-form`,
   `getRecord` / `updateRecord` / `createRecord` de `lightning/uiRecordApi`. Respetan CRUD/FLS y
   caché sin escribir Apex.
2. **GraphQL wire adapter** para lecturas relacionadas en una sola llamada (confirma el módulo
   vigente en la documentación de LWC antes de importarlo).
3. **Apex** solo si lo anterior no llega (agregaciones, lógica de servidor, varios objetos en una
   transacción).

Con Apex:
- Lecturas: `@AuraEnabled(cacheable=true)` + `@wire`. Refresca con `refreshApex` tras modificar.
- Escrituras: llamada imperativa (`await metodo({ ... })`), nunca `cacheable`.
- Importa campos y objetos por referencia (`@salesforce/schema/Account.Name`), no como texto.
- El controller Apex va en **modo usuario** y devuelve solo lo que la pantalla necesita.

## Todo componente gestiona cuatro estados

Cargando (`lightning-spinner` con `alternative-text`) · con datos · vacío (mensaje útil) · error
(mensaje legible; nada de `[object Object]`). Reduce los errores de wire/Apex a texto con una
función común y avisa con `ShowToastEvent` cuando la acción la inició el usuario.

```js
async handleGuardar() {
    this.cargando = true;
    try {
        await guardar({ pedido: this.pedido });
        this.dispatchEvent(new ShowToastEvent({ title: 'Guardado', variant: 'success' }));
        await refreshApex(this.wiredPedidos);
    } catch (e) {
        this.error = reduceErrors(e).join(', ');
    } finally {
        this.cargando = false;
    }
}
```

## Plantilla y estado

- `lwc:if` / `lwc:elseif` / `lwc:else` (las directivas `if:true` están obsoletas).
- `for:each` con `key` estable (un Id, nunca el índice).
- `lwc:ref` o `this.template.querySelector`; jamás `document.querySelector`.
- Campos reactivos simples; no mutes objetos recibidos por `@api` ni por `@wire` (son de solo
  lectura): clónalos.
- `@api` es la interfaz pública: pocas propiedades, bien nombradas, documentadas.
- Lógica en getters o en el JS; la plantilla, tonta.

## Comunicación

- Hijo → padre: `CustomEvent` con nombre en minúsculas sin guiones y `detail` con datos simples.
  `bubbles`/`composed` solo cuando de verdad haga falta cruzar el shadow DOM.
- Padre → hijo: propiedades `@api` (o un método `@api` para acciones puntuales).
- Sin relación jerárquica: Lightning Message Service (`messageChannels/`).

## Accesibilidad (la revisa `accessibility-reviewer`)

- Usa componentes base (`lightning-*`): traen teclado, foco y ARIA de serie.
- Toda entrada con `label` visible (o `variant="label-hidden"` + `label`). Todo icono-botón con
  `alternative-text`. Toda imagen con `alt` (vacío si es decorativa).
- Todo lo que se puede hacer con ratón se puede hacer con teclado; foco visible; orden lógico.
- No transmitas información solo con color. Mensajes de error asociados a su campo.
- Tras abrir un modal o cambiar de vista, mueve el foco a donde toca.
- Textos en Custom Labels (`@salesforce/label/c.Nombre`), no escritos en la plantilla.

## Seguridad y rendimiento

- Nada de `innerHTML`, `eval`, ni HTML construido a mano. `lightning-formatted-rich-text` si hay
  que mostrar HTML de datos.
- No expongas en el cliente campos que el usuario no debería ver (también viajan en la respuesta).
- Navega con `NavigationMixin`; no con `window.location`.
- Pagina o usa scroll infinito en listas largas; aplica debounce a búsquedas; carga perezosa de lo
  que no se ve.
- Estilos con SLDS y hooks de estilo (`--slds-*`), sin estilos en línea ni colores fijos.

## Metadatos

`<componente>.js-meta.xml`: `apiVersion` del proyecto, `isExposed`, `targets` mínimos y
`targetConfigs` con propiedades documentadas (`label`, `description`). Nombre de carpeta y ficheros
en `camelCase`, idénticos entre sí.

Los tests Jest los escribe `test-engineer`: deja `data-id` en los elementos relevantes y la lógica
en métodos comprobables.
