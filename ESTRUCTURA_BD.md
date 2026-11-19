# Estructura de base de datos — app SIIFWEB (Django)

Diccionario de tablas para migrar los reportes de SIIFWEB. Campos, tipos y relaciones.
Traducir a modelos Django. Complementa `NOTAS_CRUCES.md` (reglas de las llaves) y
`esquema/esquema_siifweb.dbml`.

## Convenciones (aplican a todas las tablas)

- **PK**: `id` autonumérico (default de Django). Las llaves naturales van como
  `UniqueConstraint`, no como PK compuesta.
- **Identificadores** (números de documento, códigos): `CharField`, aunque parezcan
  números — normalizados sin sufijo `.0`. Solo `vigencia` es `IntegerField`.
- **Dinero**: `DecimalField(max_digits=18, decimal_places=2)`. Nunca float.
- **FK**: `on_delete=PROTECT` hacia catálogos y documentos (nada se borra en cascada
  en datos fiscales).
- **Los acumulados arrastrados** (compromisos/obligado/pagado que trae el CDP, etc.)
  NO se guardan: son derivables por agregación. Se conservan solo en `CargaReporte`
  para conciliar contra lo que reportó SIIFWEB.
- **Grano de las imputaciones**: se cargan las líneas tal como llegan (puede haber
  varias sobre la misma imputación); se agrega en las consultas.
- Toda fila de datos lleva FK opcional a `CargaReporte`.

---

## 1. Catálogos (dimensiones)

Se pueden empezar como `CharField` dentro de las imputaciones y promover a tablas
después. La versión normalizada:

### Rubro
| campo | tipo | nota |
|---|---|---|
| codigo | CharField, unique | clasificador (1.x ingreso / 2.x gasto) |
| nombre | CharField | limpiar encoding aquí una sola vez |
| tipo | CharField(choices) | ingreso / gasto |

### Fuente
| campo | tipo | nota |
|---|---|---|
| codigo | CharField, unique | unifica FONDO (gasto) y RECURSO (ingreso): mismo dominio |
| nombre | CharField | |

### Proyecto
| campo | tipo | nota |
|---|---|---|
| bpin | CharField, unique | '0' o null = funcionamiento/sin proyecto |
| nombre | CharField | de historial e IndicadoresProyectos |
| dependencia | CharField, null | |
| valor_programado | Decimal(20,5), no editable | suma de su `ProgramacionFinanciera` (todas las vigencias); la recalculan las señales del modelo (sección 11) |
| fecha_radicacion, fecha_registro | DateField, null | |
| tiempo_ejecucion | Decimal(5,2), null | 3 enteros y 2 decimales, en la `medida_tiempo` |
| medida_tiempo | FK → MedidaTiempo, null, PROTECT | Días, Meses, Años |
| contratacion_directa | Boolean | |
| 10 pasos del trámite | Boolean + DateField, null | `TRAMITES` en models.py: decreto de liquidación inicial, gestión de recursos en PIIP, asignación ajuste a decreto ET, solicitud y concepto de traslado, decreto de traslado, asignación ajuste con trámite presupuestal, cargado en SIIFWEB, estudios previos, radicado en contratación, terminado. Sin la casilla, la fecha se borra al guardar |

### Tercero
| campo | tipo | nota |
|---|---|---|
| nit | CharField, unique | |
| nombre | CharField | contratistas y beneficiarios |

---

## 2. Cadena de gasto (el núcleo)

Patrón cabecera + líneas. La relación entre documentos va SIEMPRE en las líneas.

### Cdp (cabecera)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | |
| nro_cdp | CharField | |
| fecha_disp | DateField | |
| objeto_cert | TextField | |
| centro_costo | FK → CentroCosto (o CharField solicitante) | |
| — | UniqueConstraint(vigencia, nro_cdp) | |

### CdpImputacion (líneas)
| campo | tipo | nota |
|---|---|---|
| cdp | FK → Cdp | |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| valor_certificado | Decimal | |
| valor_disponibilidad_def | Decimal | certificado − anulaciones |
| saldo_certf | Decimal | = disponibilidad_def − comprometido (identidad) |

### Compromiso (cabecera)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | |
| nro_rp | CharField | |
| fecha_reg | DateField | |
| acto_admon | CharField | |
| centro_costo | FK → CentroCosto | |
| — | UniqueConstraint(vigencia, nro_rp) | |

### CompromisoImputacion (líneas)
| campo | tipo | nota |
|---|---|---|
| compromiso | FK → Compromiso | |
| cdp | FK → Cdp | **la relación RP→CDP va aquí** (un RP puede tomar de varios CDP) |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| valor_registro | Decimal | |
| valor_compromiso_def | Decimal | |
| saldo_rp | Decimal | comprometido sin obligar |

### Obligacion (cabecera)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | |
| nro_obligacion | CharField | |
| fecha_obli | DateField | |
| tipo_orden_gasto | CharField(choices) | NOMINA / TRANSFERENCIA / CONTRATO... — sirve para clasificar naturaleza |
| nro_orden_gasto | CharField, null | número de contrato asociado |
| prefijo_orden | CharField, null | vigencia del contrato |
| orden_pago | CharField, null | número de la orden de pago (tesorería) |
| estado_orden_pago | CharField, null | opcional, del reporte de estados |
| centro_costo | FK → CentroCosto | |
| — | UniqueConstraint(vigencia, nro_obligacion) | |

### ObligacionImputacion (líneas)
| campo | tipo | nota |
|---|---|---|
| obligacion | FK → Obligacion | |
| compromiso | FK → Compromiso | **la relación obligación→RP va aquí** |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| valor_obligacion | Decimal | |
| saldo_obli | Decimal | obligado sin pagar = cuenta por pagar al cierre |
| pagos | Decimal | girado |

---

## 3. Cierre (reservas y cuentas por pagar — salto de vigencia)

El salto v−1 deja de ser aritmética: se vuelve un FK normal al documento de origen.

### Reserva (cabecera)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | vigencia de constitución |
| nro_reserva | CharField | |
| fecha_reserva | DateField | |
| beneficiario | FK → Tercero | |
| objeto_reserva | TextField | |
| acto_admon | CharField | |
| — | UniqueConstraint(vigencia, nro_reserva) | |

### ReservaImputacion (líneas)
| campo | tipo | nota |
|---|---|---|
| reserva | FK → Reserva | |
| cdp_origen | FK → Cdp | el CDP de la vigencia anterior (resuelve el v−1) |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| valor_reserva | Decimal | |
| valor_reserva_def | Decimal | |
| obligaciones_reserva | Decimal | |
| pagos_reserva | Decimal | |
| saldo_reserva | Decimal | lo que fenece si no se ejecuta |

### CuentaPorPagar (cabecera)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | vigencia de constitución |
| nro_cxp | CharField | hereda el número de la obligación de origen |
| fecha_cxp | DateField | |
| beneficiario | FK → Tercero | |
| objeto_cxp | TextField | |
| — | UniqueConstraint(vigencia, nro_cxp) | |

### CxpImputacion (líneas)
| campo | tipo | nota |
|---|---|---|
| cxp | FK → CuentaPorPagar | |
| obligacion_origen | FK → Obligacion, null | la obligación de v−1 (resuelve el v−1) |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| valor_cxp | Decimal | |
| valor_cxp_def | Decimal | |
| pagos | Decimal | |
| saldo_cxp | Decimal | |

---

## 4. Ingresos

### ComprobanteIngreso (transaccional, ~1,4M filas)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | |
| nro_comprobante | CharField | |
| tipo_comppptal | CharField(choices) | DERECHOS_APROBADOS / DERECHOS_ADICIONADOS / EFECTIVO / REVERSIONES |
| rubro | FK → Rubro | clasificador 1.x |
| fuente | FK → Fuente | del RECURSO |
| fecha | DateField | |
| valor | Decimal | significado según tipo (aforo/adición/recaudo/reversa) |
| concepto | TextField | |
| — | índices en (vigencia, tipo_comppptal, fecha) | tabla grande |

---

## 5. Bitácora

### ComprobantePresupuestal (log de eventos de gasto)
| campo | tipo | nota |
|---|---|---|
| vigencia | IntegerField | |
| nro_comprobante | CharField | |
| tipo_comppptal | CharField(choices) | 19 tipos: APROPIADO, COMPROMISO, OBLIGACION, PAGO, PAGO_CXP, RESERVA... |
| nrodoc | CharField | **polimórfico**: número del documento según el tipo |
| fecha | DateField | la fuente de fechas de pago |
| concepto | TextField | |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | |
| proyecto | FK → Proyecto, null | |
| tercero | FK → Tercero, null | |
| valor | Decimal | |
| cdp / compromiso / obligacion | FK nullable a cada uno | resueltos por el proceso de carga según el tipo; evita GenericForeignKey |

---

## 6. Contractual (del histórico de orden de gasto)

`Contrato` NO lleva vigencia en la llave: el contrato cruza años. La vigencia entra
por la imputación.

### Contrato (ficha)
| campo | tipo | nota |
|---|---|---|
| tipo_contrato | CharField | |
| nro_contrato | CharField | |
| fecha_firma | DateField | |
| tercero | FK → Tercero | contratista |
| interventor | CharField | único reporte que lo trae |
| descripcion | TextField | |
| valor_contrato | Decimal | |
| fecha_inicio | DateField | |
| fecha_final | DateField | |
| dependencia | CharField | |
| — | UniqueConstraint(tipo_contrato, nro_contrato, fecha_firma, tercero) | el nro solo es ambiguo |

### ContratoActa (eventos de pago del contrato)
| campo | tipo | nota |
|---|---|---|
| contrato | FK → Contrato | |
| nro_orden | CharField | |
| tipo_orden | CharField | PARCIAL / FINAL / ANTICIPO |
| concepto | TextField | |
| fecha_pago | DateField | |
| nrodoc_acta | CharField | |
| valor_pago | Decimal | |

### ContratoImputacion (líneas del contrato → cadena)
| campo | tipo | nota |
|---|---|---|
| contrato | FK → Contrato | |
| compromiso | FK → Compromiso | el vínculo a la cadena (NRODOC = nro_rp, 99,4%) |
| comprobante | FK → ComprobantePresupuestal, null | ancla a la bitácora (100%) |
| rubro | FK → Rubro | |
| fuente | FK → Fuente | del RECURSO |
| proyecto | FK → Proyecto, null | contrato → BPIN directo |
| vigencia | IntegerField | del PREFIJO |

---

## 7. Planeación (plan indicativo)

### Indicador
| campo | tipo | nota |
|---|---|---|
| codigo | CharField, unique | |
| nombre | CharField | |
| acumula | BooleanField | |

### MetaProyecto
| campo | tipo | nota |
|---|---|---|
| proyecto | FK → Proyecto | |
| indicador | FK → Indicador | |
| vigencia | IntegerField | |
| meta_total | Decimal | |
| meta_vigencia | Decimal | |
| avance_ejecutado | Decimal | |
| obligado_vigente | Decimal | autoreporte financiero |
| obligado_reserva | Decimal | |
| indicador_ejecutado | Decimal | |
| — | UniqueConstraint(proyecto, indicador, vigencia) | grano verificado |

---

## 8. Operación

### CargaReporte
| campo | tipo | nota |
|---|---|---|
| tipo_reporte | CharField(choices) | cdp / compromisos / obligaciones... |
| archivo | CharField | nombre del xlsx origen |
| fecha_descarga | DateField | **crítico**: los saldos son la foto de este día |
| vigencia | IntegerField, null | null para el histórico (rango) |
| filas | IntegerField | |
| hash | CharField | detectar re-cargas idénticas |

---

## Mapa de relaciones (FK principales)

```
Rubro, Fuente, Proyecto, Tercero  ← (catálogos, referidos por casi todas)

Cdp ──┬── CdpImputacion
      └── (referido por) CompromisoImputacion.cdp
                         ReservaImputacion.cdp_origen

Compromiso ──┬── CompromisoImputacion ── cdp → Cdp
             └── (referido por) ObligacionImputacion.compromiso
                                ContratoImputacion.compromiso

Obligacion ──┬── ObligacionImputacion ── compromiso → Compromiso
             └── (referido por) CxpImputacion.obligacion_origen

Reserva ── ReservaImputacion ── cdp_origen → Cdp   (salto v-1)
CuentaPorPagar ── CxpImputacion ── obligacion_origen → Obligacion  (salto v-1)

Contrato ──┬── ContratoActa
           └── ContratoImputacion ──┬── compromiso → Compromiso
                                    └── comprobante → ComprobantePresupuestal

ComprobantePresupuestal ── (cdp | compromiso | obligacion) nullable  (polimórfico resuelto)
ComprobanteIngreso ── rubro, fuente

Indicador ── MetaProyecto ── proyecto → Proyecto

CargaReporte ← (referido opcionalmente por toda fila de datos)
```

## Orden de construcción sugerido

1. Catálogos (o empezar con CharField y normalizar después).
2. `Cdp` + `CdpImputacion` — internaliza el patrón cabecera+líneas.
3. `Compromiso` + `CompromisoImputacion` (con FK a Cdp) — la primera relación entre documentos.
4. `Obligacion` + `ObligacionImputacion` — cierra la cadena.
5. `Reserva` y `CuentaPorPagar` — el salto de vigencia como FK.
6. `Contrato` + actas + imputaciones — el módulo contractual (histórico).
7. Bitácora, ingresos, planeación, carga — cuando los necesites.
```

---

## 9. Catálogo PIIP y formulación de los proyectos (noviembre de 2026)

Tablas agregadas después de este diccionario. El detalle (campos, relaciones, borrados,
carga y validaciones) está en `CATALOGO_PIIP.md`.

| Tabla | Llave natural | Relaciones |
|---|---|---|
| `ProductoCatalogo` | `codigo` | → `MedidoATravesDe` |
| `IndicadorCatalogo` | `codigo` | → `ProductoCatalogo`, → `UnidadMedida`, → `IndicadorMGA` (homologación con el plan) |
| `FormulacionProyecto` | `bpin` (del PIIP) | uno a uno con `Proyecto`, opcional (SET_NULL); → `CargaReporte`, ↔ `Municipio` |
| `IndicadorProyecto` | (`formulacion`, `indicador`) | → `FormulacionProyecto`, → `IndicadorCatalogo` |
| `MetaVigenciaIndicador` | (`indicador_proyecto`, `vigencia`) | → `IndicadorProyecto` |
| `Departamento` | `nombre` | ← `Municipio.departamento` |


## 10. CUIPO: ejecución de gastos por corte (noviembre de 2026)

App `cuipo`. Insumo del reporte CUIPO; no lo usa nada de `siifweb`. Los códigos van como
texto, tal como vienen en el reporte de SIIFWEB, sin llaves a los catálogos.

| modelo | llave natural | relaciones |
|---|---|---|
| `CorteEjecucionGastos` | (`vigencia`, `fecha_inicio`, `fecha_fin`) | `fecha_descarga`, archivo, `hash`, estado y mensaje de la carga |
| `FilaEjecucionGastos` | (`corte`, `rubro_id_siifweb`, `recurso`, `centro_costo`, `proyecto`) | → `CorteEjecucionGastos` (CASCADE) |

`FilaEjecucionGastos` guarda el detalle del reporte (filas con recurso): `rubro`, `recurso`,
`centro_costo` con sus nombres, `proyecto` (BPIN, "0" sin proyecto), `de_otra_vigencia`
(cuelga de un árbol de rubros de otra vigencia) y los valores en `Decimal(20,2)`:
apropiación inicial, adición, disminución, crédito, contracrédito, aplazamientos,
desaplazamientos, apropiación definitiva, solicitud en trámite, CDP, RP, obligación y pago.
Los subtotales del árbol no se guardan; la carga verifica que cuadren con el detalle.

### Listas CHIP (app `cuipo`, fase 1 del CUIPO)

| modelo | llave natural | campos propios |
|---|---|---|
| `VersionListas` | `nombre` ("09-2026") | archivo (opcional), hash, `cargado_por` → `auth.User`, estado, mensaje |
| `ConceptoCUIPO` | `codigo` | `nivel` (S/D), `habilitado_departamentos`, `requiere_cpc`, `notas` |
| `FuenteCUIPO`, `SeccionPresupuestal`, `VigenciaGasto`, `SituacionFondos`, `PoliticaPublica`, `TerceroCUIPO` | `codigo` | — |
| `ProductoCUIPO` | `codigo` | `sector`, `programa`, `aplica_territoriales` (texto) |
| `CPC` | `codigo` (largo 1, 5 o 7) | `seccion`, `division` |
| `DetalleSectorial` | `codigo` | `grupo`, `sector` |

Todos los catálogos heredan de `CatalogoCHIP` (abstracta): `codigo` único como texto exacto,
`descripcion`, `activo` y `version` → `VersionListas` (PROTECT; la última versión que trajo el
código). Lo que deja de venir queda inactivo; nada se borra.

### Homologaciones y reglas (app `cuipo`, fase 2 del CUIPO)

| modelo | llave natural | relaciones |
|---|---|---|
| `HomologacionFuente` | (`fuente_siifweb`, `vigencia`) | → `siifweb.Fuente`, → `FuenteCUIPO`, `validado_por` → `auth.User`, `fecha_validacion` |
| `HomologacionRubro` | `rubro` | uno a uno con `siifweb.Rubro`, → `ConceptoCUIPO` |
| `ReglaSeccion` | `centro_costo` | uno a uno con `siifweb.CentroCosto`, → `SeccionPresupuestal` |
| `ReglaTercero` | `rubro` o `centro_costo` (uno de los dos) | uno a uno con `siifweb.Rubro` o con `siifweb.CentroCosto`, → `TerceroCUIPO` |
| `ReglaSituacionFondos` | (`prefijo_rubro`, `fuente_cuipo`) | → `FuenteCUIPO` (opcional), → `SituacionFondos` |

Todas con `observacion`. Las FK a catálogos son PROTECT. Los valores por defecto (sección 16.0,
situación C, tercero 1 - NO APLICA) no se guardan: los aplica `cuipo/derivacion.py`.

### Recursos CUIPO (app `cuipo`)

| modelo | llave natural | relaciones |
|---|---|---|
| `RecursoCUIPO` | — | `descripcion`, `archivo` (en `cuipo/recursos/` del bucket), `activo` y fechas. Los activos se listan en la ficha de distribución |

### Distribución (app `cuipo`, fase 3 del CUIPO)

| modelo | llave natural | relaciones |
|---|---|---|
| `DistribucionBPIN` | (`corte`, `bpin`) | → `CorteEjecucionGastos` (PROTECT), ↔ `ProductoCUIPO` (productos del BPIN), `validado_por` → `auth.User`; `periodo`, `regla`, `estado`, `observacion` |
| `AsociacionFuenteProducto` | (`distribucion`, `fila`, `producto`) | → `DistribucionBPIN` (CASCADE), → `FilaEjecucionGastos` (PROTECT), → `ProductoCUIPO` |
| `LineaCUIPO` | (`distribucion`, `fila`, `producto`, `vigencia_gasto`) | → `DistribucionBPIN` (CASCADE), → `FilaEjecucionGastos` (PROTECT), → `ProductoCUIPO`, → `VigenciaGasto`, → `CPC`, `DetalleSectorial`, `TerceroCUIPO`, `PoliticaPublica` (opcionales); C, O y P en `Decimal(20,2)`; `origen_valores` y un `origen_*` por cualitativo |

Un corte con distribuciones no se borra (PROTECT) ni se reprocesa (lo impide el importador).


## 11. Programación y seguimiento del proyecto (noviembre de 2026)

App `siifweb`. Lo diligencia el equipo desde el detalle del proyecto; no viene de ningún reporte.

| modelo | llave natural | relaciones |
|---|---|---|
| `ProgramacionFinanciera` | (`proyecto`, `vigencia`, `fuente`, `meta`) | → `Proyecto` (CASCADE), → `Fuente` (PROTECT), → `MetaIndicador` (PROTECT); `valor` Decimal(20,5) (15 enteros, 5 decimales) |
| `ProgramacionFisica` | (`proyecto`, `vigencia`, `meta`) | → `Proyecto` (CASCADE), → `MetaIndicador` (PROTECT); `valor` Decimal(20,5) |
| `MedidaTiempo` | `nombre` | ← `Proyecto.medida_tiempo` |
| `ObservacionProyectoSiifweb` | — | → `Proyecto` (CASCADE); `texto` y fechas. Pasados 3 días (`DIAS_EDITABLE`) ya no se modifica ni se borra |

- Las dos programaciones guardan solo valores distintos de cero: vacío o cero borra la fila.
- `Proyecto.valor_programado` se recalcula con las señales `post_save` y `post_delete` de
  `ProgramacionFinanciera` (también en un borrado masivo). La física no suma: cada meta tiene
  su propia unidad.
- Las metas de la programación financiera y de la física deben ser las mismas en cada
  vigencia. No es un constraint (son dos tablas, y se puede llenar primero cualquiera): lo
  avisa la pantalla (`programacion_financiera.descuadres`) y nada se borra en cascada entre
  las dos.
- `ObservacionProyectoSiifweb` es distinta de `ObservacionProyecto`, que cuelga de
  `ProgramacionProyectos` (lo que vino del Access).
