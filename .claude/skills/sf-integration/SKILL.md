---
name: sf-integration
description: Integraciones en Salesforce para este harness — Named/External Credentials, callouts fiables (timeouts, reintentos, idempotencia), Platform Events, Apex REST y cómo probarlas con mocks.
user-invocable: false
---

# Integraciones

## Elegir el patrón

| Necesidad | Patrón |
|---|---|
| Salesforce llama a un sistema externo y necesita la respuesta ya | Callout síncrono desde una acción del usuario (LWC → Apex) |
| Salesforce avisa a otro sistema tras guardar | Trigger → `Queueable` con `Database.AllowsCallouts`, o Platform Event |
| Otros sistemas reaccionan a cambios de datos | Change Data Capture / Platform Events (que se suscriban) |
| Un sistema externo llama a Salesforce | APIs estándar (REST/Bulk/GraphQL) antes que Apex REST a medida |
| API externa con OpenAPI | External Services (sin código) |
| Volumen alto | Bulk API / Batch, no un callout por registro |

Desde un **trigger no se puede hacer un callout síncrono**: siempre asíncrono.

## Configuración (metadata)

- **Named Credential + External Credential** para todo endpoint: URL, autenticación y secretos
  viven ahí, no en el código. El principal (Named Principal o por usuario) y el permission set que
  da acceso al External Credential los concede `security-admin` — pídelo en tu informe.
- El **secreto en sí nunca va al repo**: la metadata lleva la estructura; los valores los introduce
  un humano en cada org. Anótalo como **paso manual de release**.
- Código: `req.setEndpoint('callout:Nombre_NC/ruta');`. Nada de Remote Site Settings para endpoints
  nuevos si puedes usar Named Credentials.

## Callouts fiables

```apex
public with sharing class StockClient {
    public class StockException extends Exception {}

    public static StockResponse consultar(String sku) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:ERP_Stock/v1/stock/' + EncodingUtil.urlEncode(sku, 'UTF-8'));
        req.setMethod('GET');
        req.setTimeout(10000);                         // explícito; nunca dejes el valor por defecto sin pensar
        HttpResponse res = new Http().send(req);
        if (res.getStatusCode() == 200) {
            return (StockResponse) JSON.deserialize(res.getBody(), StockResponse.class);
        }
        throw new StockException('ERP respondió ' + res.getStatusCode());   // sin volcar el body entero
    }
}
```
- **Timeout explícito** y presupuesto total de la transacción en mente.
- **Trata cada resultado**: 2xx, 4xx (no reintentar, es nuestro error), 429/5xx y timeout
  (reintentable). Los reintentos van en asíncrono, con límite y espera creciente
  (Queueable re-encolado con contador), nunca en un bucle dentro de la transacción.
- **Idempotencia**: toda operación que crea o modifica en el otro lado lleva una clave idempotente
  (External Id, cabecera `Idempotency-Key`) para que un reintento no duplique.
- **Callout antes que DML**: después de un DML sin commit no se puede hacer callout en la misma
  transacción. Ordena: callout → DML, o sepáralo en asíncrono.
- Bulk: agrupa registros en una llamada cuando la API lo permita; respeta el máximo de callouts por
  transacción.
- Registra el fallo de forma consultable (objeto de log o Platform Event de error), sin secretos ni
  datos personales, y deja el registro en un estado que permita reprocesar.
- Deserializa a **clases tipadas**; valida lo que llega antes de usarlo.

## Platform Events

- Define el evento (`objects/Nombre__e/`) con campos explícitos; es un contrato: versiona, no rompas.
- Publicación: "publish after commit" si el evento refleja datos guardados; "publish immediately"
  solo para logging que debe sobrevivir a un rollback.
- Comprueba el resultado de `EventBus.publish`. Los suscriptores (trigger/flow) deben ser
  idempotentes y tolerar reentregas; usa `EventBus.RetryableException` con criterio.

## Apex REST entrante (si no hay más remedio)

`@RestResource(urlMapping='/pedidos/v1/*')` con versión en la URL, `with sharing`, modo usuario,
validación estricta de entrada, códigos HTTP correctos y respuestas de error sin internos.

## Pruebas (con `test-engineer`)

- `Test.setMock(HttpCalloutMock.class, …)`: éxito, error de cliente, error de servidor, timeout
  (lanza `CalloutException`), cuerpo malformado.
- Asíncrono entre `Test.startTest()` / `Test.stopTest()`. Platform Events con
  `Test.getEventBus().deliver()`.
- En tu informe: qué contratos externos se asumen (ruta, campos, códigos) y **cómo se verificó
  contra el sistema real** — o `NO VERIFICADO` si solo hay mocks. Eso lo tiene que saber el humano.
