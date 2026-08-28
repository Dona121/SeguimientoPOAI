# Cómo se cruzan las dos tablas de contratos

## Qué tiene cada una

- **Historial de orden de gasto 2** → el detalle: cada fila es un contrato cargado a un
  proyecto (con su rubro y recurso) o un pago. Es la tabla base.
- **Órdenes de gasto por fecha** → la lista de contratos con su **duración**
  (`DURACION`, `DURACION_DIAS`). De aquí se saca la duración.

## El cruce se hace con 4 campos

Es lo mismo, pero cada tabla lo llama distinto:

| Qué es | En Historial | En Órdenes de gasto |
|---|---|---|
| Número del contrato | `DOCCONTRATO` | `NRO_CONTRATO` |
| Fecha de firma | `FECHA_FIRMA` | `FECHA_FIRMA` |
| Documento del contratista | `TERCERO` | `TERCERO` |
| Número del RP | `NRODOC` | `COMPROMISO` |

## Por qué esos 4

- **Número + documento del contratista + fecha de firma** dicen de qué contrato se trata.
  El número solo no alcanza: se repite entre años y cada reporte lo numera a su manera.
- **El RP** hace que la llave no se repita del lado de órdenes de gasto (ahí un mismo
  contrato sale varias veces, una por cada recurso). Sin el RP, cada fila del historial se
  multiplicaba; con el RP, el cruce queda limpio.

## Dos cosas que hay que respetar sí o sí

1. **En el Historial hay dos "números de contrato".** El `NRO_CONTRATO` es numeración
   interna y **no cruza**. El bueno es `DOCCONTRATO`. Por eso se empareja
   `DOCCONTRATO` ↔ `NRO_CONTRATO`.
2. **El RP (`NRODOC`) solo aparece en las filas que tienen proyecto.** Por eso, antes de
   cruzar, se filtra el historial a `PROYECTO <> 0/vacío` (las filas de puro pago no traen
   RP). Y en órdenes de gasto se filtra `COMPROMISO <> vacío` y se quitan duplicados, para
   que quede un solo registro por llave.

## Resultado

Cruce **uno a uno**, sin filas repetidas, y trae la duración en el **99%** de los casos.
El 1% que no cruza son contratos de regalías, salud y convenios, que ese reporte de
órdenes de gasto no cubre.
