# Notas para cruzar las tablas SIIFWEB

Consideraciones verificadas empíricamente (datos 2022-2026, Gobernación de Sucre).
Complementa el esquema en `esquema/esquema_siifweb.dbml` y la suite `conciliaciones.py`.

## Reglas generales (aplican a todo cruce)

1. **VIGENCIA va en toda llave.** La numeración de CDP, RP, obligación y orden de pago
   reinicia en 1 cada año: el 97% de los números se repiten entre vigencias. Sin la
   vigencia, el 86% de los "documentos" muestran fechas múltiples porque son documentos
   distintos fusionados.
2. **Agregar antes de cruzar.** El grano de los consolidados es documento × rubro × fondo
   × proyecto, y un documento puede tener **varias líneas sobre la misma imputación**
   (ej.: CDP 514 de 2025 tiene dos líneas sobre el mismo rubro/fondo). Ambos lados del
   join deben agregarse al mismo grano; nunca cruzar tabla agregada contra tabla cruda.
3. **Identificadores como texto (Utf8), sin sufijo `.0`.** Solo son numéricos: VIGENCIA
   (Int, participa en aritmética v−1), valores en pesos (Float64) y fechas (Date).
   Los valores vienen en los xlsx como texto con coma decimal: `str.replace(",", ".")`.
4. **Comparar valores con tolerancia de 1 peso** (`.abs() >= 1`), nunca con `==`:
   el parseo de comas deja residuos flotantes de e-8.
5. **`full` join + `fill_null(0)` para conciliaciones** (el `left` convierte la ruptura
   de llaves en un falso "todo cuadra"); `left` para enriquecer; `anti` para huérfanas.
6. **Los acumulados se arrastran hacia atrás** (cdp trae compromisos/obligado/pagado;
   compromisos trae obligado/pagado). Para totales, usar UNA tabla — la más cercana al
   hecho — o se cuenta lo mismo varias veces.
7. **Los saldos son la foto a la fecha de descarga**, no al cierre de la vigencia.
   Descargar juntas las bases que se vayan a conciliar entre sí.
8. **La fecha es atributo del documento, no llave**: recuperarla con `.first()`.

## Cruce por cruce

### compromisos → cdp
- Llave: `(VIGENCIA, NRODOC_CDP, IDENTIFICACION_PRESUPUESTAL, FONDO, PROYECTO)`
  → `(VIGENCIA, NRO_CDP, rubro, fondo, proyecto)`.
- Cuadra al peso al 100% en las 5 vigencias: `sum(VALOR_COMPROMISO_DEF)` por llave
  == `cdp.VALOR_COMPROMISOS`.
- `NRO_INTERNO_CDP` NO es llave (id interno que no cruza entre exportes).

### obligaciones → compromisos
- Llave: `(VIGENCIA, NRO_RP, rubro, fondo, PROYECTO)`.
- **Excepción 2023**: 35 obligaciones ($7.613M) son ejecución de reservas — sus RP
  (7189-7463) pertenecen a 2022. Regla de clasificación: RP ausente en compromisos de
  su vigencia y presente en v−1 = reserva; ausente en ambas = anomalía (hoy: cero).
  Desde 2024 las reservas tienen circuito propio y no llegan a este consolidado.
- **24 imputaciones huérfanas conocidas** (0,06%): la combinación rubro/fondo de la
  obligación no existe en su RP. Tolerarlas; si crecen, investigar.
- La columna `RP` es un rótulo constante ("COMPROMISO"), no una llave.

### obligaciones → orden de gasto
- Llave precisa: `(VIGENCIA, NRO_RP, NRO_ORDEN_GASTO)` → `(VIGENCIA, COMPROMISO,
  NRO_CONTRATO)`. Cubre el 96%.
- **NUNCA cruzar por `(VIGENCIA, NRO_CONTRATO)` solo**: el número de contrato es
  ambiguo en el 49% de los casos (la numeración reinicia por tipo de contrato; el
  "contrato 2 de 2023" son cuatro contratos de cuatro terceros distintos).
- Solo el 53% de las obligaciones tienen orden de gasto: nómina, transferencias y
  órdenes directas no pasan por esa base — es diseño, no error.
- En ordengasto, `TOTAL` y `VALOR_CDP` se repiten en cada fila del contrato:
  deduplicar por contrato antes de sumar (`TOTAL` → `.max()` por las adiciones).
- `VALOR_ART1` = obligado acumulado del compromiso al corte (sigue al obligado, no al
  girado). No incluye ejecución vía reserva. Desfase en ~19% de filas: para cifras
  oficiales usar el consolidado de obligaciones.

### ordengasto → cdp / compromisos
- `(VIGENCIA, CDP)` y `(VIGENCIA, COMPROMISO)`: 100% de existencia, excluyendo los
  ~260 registros con COMPROMISO nulo (contratos sin RP en esa fila) y 1 huérfano
  conocido (contrato 1/2024 V.P. GLOBAL).

### historial_contratos_imputaciones → compromisos
- Su `NRODOC` **es el número del RP** (verificado contra bitácora y compromisos).
- Llave: `(PREFIJO, NRODOC, RUBRO, RECURSO, PROYECTO)` → `(VIGENCIA, NRO_RP, rubro,
  fondo, proyecto)`. Cruza al 99,4% sin multiplicar filas.
- Es el vínculo contrato → BPIN directo, e incluye los 189 convenios que ordengasto
  no trae. Ancla también a la bitácora por `NRO_COMPROBANTEPPTAL` (100%).

### reservas → cdp / compromisos (salto temporal −1)
- El archivo de la vigencia v documenta el cierre de v−1. Llave: `(VIGENCIA − 1,
  NUMERO_CDP, rubro, fondo)` → cdp. Verificado sin excepciones: toda reserva apunta
  a la vigencia inmediatamente anterior.
- **Llaves falsas**: `NRODOC` y `NRO_RESERVA` parecen apuntar a los RP pero son
  numeración propia; los ids internos (`NROMOV_RAIZ`, etc.) no cruzan entre exportes.
- Contra compromisos no hay igualdad sino **cota**: reserva ≤ saldo RP del CDP en esa
  imputación (la constitución es selectiva: en el cierre 2025 solo se reservaron
  $29.873M de $108.299M sin obligar).
- Para llegar al RP exacto cuando el CDP tiene varios: desambiguar con el beneficiario
  (`NIT` de reservas ↔ `TERCERO` de ordengasto).
- La ejecución de la reserva vive SOLO en esta base (el compromiso de v−1 no se
  actualiza).

### cxp → obligaciones / compromisos (salto temporal −1)
- `NRO_CXP` hereda el número de la obligación de origen: `(VIGENCIA − 1, NRO_CXP)` →
  `(VIGENCIA, NRO_OBLIGACION)`, 99% (3 conocidas sin origen).
- Los pagos de la CxP viven SOLO aquí; obligaciones de v−1 no se actualiza.
- Caso abierto: 3 CxP con pagos duplicados exactos (2× y 3×), comprobantes reales
  distintos sin reversión visible — pendiente reporte de órdenes de pago de
  vigencias expiradas para resolver.

### bitácora (comprobantes) ↔ todo
- Llave **polimórfica**: `(VIGENCIA, TIPO_COMPPTAL, NRODOC)` apunta a la tabla del
  tipo (DISPONIBILIDAD → NRO_CDP, COMPROMISO → NRO_RP, OBLIGACION → NRO_OBLIGACION,
  PAGO → orden de pago...). No modelar como FK dura.
- Cuadra AL PESO con todos los consolidados (mismas filas y totales).
- Única fuente de: fechas de pago, solicitudes (etapa previa al CDP), traslados
  (CREDITO/CONTRACREDITO) y ejecución fechada de reservas y CxP
  (tipos `PAGO_CXP`, `PAGO_RESERVA`, `OBLIGACION_RESERVA`).

### ordenes_pago_estado → obligaciones
- `(VIGENCIA, ORDEN)` → `(VIGENCIA, ORDEN_PAGO)`: 92% (las 12.937 órdenes
  referenciadas por obligaciones cruzan todas; 22 órdenes tienen 2 proyectos).
- Lo que no cruza es diseño: 581 EXTRAPRESUP (sin cadena presupuestal) + anuladas
  y reemplazadas.
- **NO cubre las órdenes de pago de CxP ni reservas** (otro espacio de numeración).

### ingresos ↔ gasto
- No hay llave transaccional. El puente es la **fuente**: `ingresos.RECURSO` =
  `gasto.FONDO` (mismo dominio de códigos, 70/82 en 2025). Análisis a nivel de
  fuente, no de documento.
- Rubros de ingreso empiezan por `1.x`; de gasto por `2.x` (2.1 funcionamiento,
  2.2 deuda, 2.3 inversión).

### PROYECTO (llave transversal)
- Presente en cdp, compromisos, obligaciones, reservas, cxp, bitácora e historial de
  imputaciones. `0` = funcionamiento / sin proyecto.
- Forma parte del grano: un CDP puede amparar 2+ proyectos sobre el mismo rubro+fondo.
- Incluirla en las llaves de cruce NO pierde emparejamientos (verificado): la
  obligación y el contrato heredan el proyecto de su RP.
- Ojo: en 2025 hay $207.700M de inversión (rubros 2.3) con PROYECTO = 0 — el 17% de
  la inversión no es rastreable por BPIN. Declararlo en los informes.
- El indicador físico cruza por `BPIN + VIGENCIA` (archivo IndicadoresProyectos:
  91% de sus BPINes tienen ejecución; cubren el 49% de los códigos de SIIFWEB).
