---
name: sf-testing
description: Cómo se escriben tests en este harness — Apex (TestDataFactory, bulk, negativos, permisos con runAs, mocks de callout) y Jest para LWC. Cobertura mínima 85 % por clase, con aserciones reales.
user-invocable: false
---

# Tests

Un test existe para **fallar cuando el comportamiento se rompe**. La cobertura es una consecuencia,
no el objetivo: el gate exige ≥ 85 % **por clase** (configurable), pero un test sin aserciones se
rechaza en revisión aunque cubra el 100 %.

Escribe los tests **desde los criterios de aceptación y el diseño**, no copiando la implementación:
si el código tiene un bug, un test calcado de él lo da por bueno.

## Apex

```apex
@IsTest
private class PedidoServiceTest {

    @TestSetup
    static void datos() {
        TestDataFactory.crearCuentas(200);          // los datos salen SIEMPRE de la factoría
    }

    @IsTest
    static void confirmar_marcaLosPedidosYActualizaLaCuenta() {
        List<Pedido__c> pedidos = TestDataFactory.crearPedidos([SELECT Id FROM Account], 'Borrador');

        Test.startTest();                            // límites nuevos; lo asíncrono se ejecuta en stopTest
        PedidoService.confirmar(new Map<Id, Pedido__c>(pedidos).keySet());
        Test.stopTest();

        Assert.areEqual(200, [SELECT COUNT() FROM Pedido__c WHERE Estado__c = 'Confirmado'],
            'Los 200 pedidos deben quedar confirmados');
    }

    @IsTest
    static void confirmar_sinStock_lanzaErrorDeNegocio() {
        try {
            PedidoService.confirmar(new Set<Id>{ TestDataFactory.crearPedidoSinStock().Id });
            Assert.fail('Debía lanzar PedidoException');
        } catch (PedidoException e) {
            Assert.isTrue(e.getMessage().contains('stock'), 'El mensaje debe explicar el motivo');
        }
    }

    @IsTest
    static void confirmar_usuarioSinPermiso_noPuede() {
        User u = TestDataFactory.crearUsuarioEstandar();          // sin el permission set
        System.runAs(u) {
            // con modo usuario, la operación debe fallar o no devolver datos
        }
    }
}
```

Reglas:
- **Nunca `SeeAllData=true`.** Todo dato lo crea el test (excepción real: Pricebook estándar vía
  `Test.getStandardPricebookId()`).
- **`TestDataFactory`**: una clase `@IsTest` con métodos estáticos que crean registros válidos con
  los campos obligatorios y aceptan cantidad/overrides. Si falta un método, añádelo ahí.
- Cada unidad con lógica necesita, como mínimo: **camino feliz**, **bulk (200 registros)**,
  **negativo/errores**, y **permisos** (`System.runAs` con y sin el permission set) si expone datos.
- Triggers: prueba insert, update (con y sin cambio del campo relevante), delete/undelete si aplican.
- **Callouts**: `Test.setMock(HttpCalloutMock.class, new MiMock())`; cubre éxito, 4xx/5xx y timeout.
- **Asíncrono**: Queueable/Batch/future se ejecutan al llegar a `Test.stopTest()`; aserta después.
- **Platform Events**: `Test.getEventBus().deliver()` para forzar la entrega.
- Nombres que cuentan la historia: `metodo_condicion_resultadoEsperado`.
- Un test, un comportamiento. Mensaje en cada aserción.
- No dependas del orden de los registros, de la fecha de hoy ni de datos de la org.
- Tests privados (`private class`), sin lógica condicional dentro del test.

Si algo no se puede probar sin trucos (método gigante, dependencias ocultas), **el problema es el
diseño**: dilo en tu informe; no lo tapes con un test que solo "pasa por encima".

## Jest (LWC)

Cada componente con lógica lleva `lwc/<componente>/__tests__/<componente>.test.js`.

```js
import { createElement } from 'lwc';
import ListaPedidos from 'c/listaPedidos';
import getPedidos from '@salesforce/apex/PedidoController.getPedidos';

jest.mock('@salesforce/apex/PedidoController.getPedidos',
    () => ({ default: jest.fn() }), { virtual: true });

const flush = () => Promise.resolve();

describe('c-lista-pedidos', () => {
    afterEach(() => {
        while (document.body.firstChild) { document.body.removeChild(document.body.firstChild); }
        jest.clearAllMocks();
    });

    it('pinta una fila por pedido', async () => {
        getPedidos.mockResolvedValue([{ Id: '1', Name: 'P-001' }]);
        const el = createElement('c-lista-pedidos', { is: ListaPedidos });
        document.body.appendChild(el);
        await flush();
        expect(el.shadowRoot.querySelectorAll('[data-id="fila"]').length).toBe(1);
    });

    it('muestra el error si Apex falla', async () => {
        getPedidos.mockRejectedValue({ body: { message: 'boom' } });
        const el = createElement('c-lista-pedidos', { is: ListaPedidos });
        document.body.appendChild(el);
        await flush();
        expect(el.shadowRoot.querySelector('[data-id="error"]')).not.toBeNull();
    });
});
```
- Para `@wire`: importa el adaptador y emite con `adaptador.emit(datos)` / `adaptador.error()`.
- Cubre: render inicial, estados de carga / vacío / error, eventos que emite (`CustomEvent`) y los
  que recibe, y la accesibilidad básica (etiquetas presentes).
- Selecciona por `data-id`, no por clases CSS ni por posición.
- Ejecuta: `npx sfdx-lwc-jest -- --ci` (o `./hx gate run lwc-tests`).
