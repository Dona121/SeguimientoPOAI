# Contexto del proyecto SIIFWEB

Resumen para retomar el trabajo en una conversación futura. Última actualización: 2026-07-18.

## Qué es esto

Análisis de la ejecución presupuestal de la Gobernación de Sucre (vigencias 2022-2026)
a partir de los exportes Excel de SIIFWEB, para soportar el seguimiento del plan
indicativo. El trabajo se hace en polars; los exportes se convierten a Parquet.

## Estructura del proyecto (`C:\Users\Donal\Documents\Siifweb`)

- `data/parquet/` — todas las bases convertidas (llaves normalizadas como texto sin
  `.0`, valores Float64, columna VIGENCIA agregada).
- `app.py` — app Streamlit (`uv run streamlit run app.py`): cadena de gasto, ingresos,
  proyectos (con metas del plan indicativo), explorador de CDP, cierre y alertas,
  buscador transversal.
- `actualizar_datos.py` — regenera los parquet desde los xlsx de origen.
- `conciliaciones.py` — suite de validación (correr tras cada descarga; todo debe dar
  OK salvo las excepciones documentadas dentro del propio script).
- `esquema/` — modelo de datos: `esquema_siifweb.dbml` (completo, 12 tablas) y
  `esquema_siifweb_simple.dbml` (9 tablas) para dbdiagram.io; versiones mermaid,
  draw.io y PNG.
- `NOTAS_CRUCES.md` — consideraciones de llaves para cruzar cada par de tablas.
- La memoria persistente del asistente tiene el detalle en
  `siifweb-bases-presupuestales.md` (llaves verificadas, hallazgos, convenciones).

## Las bases (origen → parquet)

| Base | Origen | Descarga |
|---|---|---|
| cdp_{v} | Informes\Consolidado disponibilidades | por vigencia |
| compromisos_{v} | Documents\Consolidado compromisos | por vigencia |
| obligaciones_{v} | Documents\Consolidado obligaciones | por vigencia |
| reservas_{v} (desde 2024) | Informes\Consolidado reservas | por vigencia |
| cxp_{v} (solo 2025) | Informes\Consolidado cuentas por pagar | por vigencia |
| ordengasto_{v} | Informes\Orden de gasto | por vigencia |
| ingresos_{v} | Informes\Ingresos por rubro | por vigencia |
| comprobantes_{v} (solo 2025) | Informes\Comprobante por centro de costo (bitácora) | por vigencia |
| ordenes_pago_estado_{v} (solo 2025) | Gestión de gasto: Ordenes De Pago Por Estado | por vigencia |
| historial_contratos_{fichas,actas,imputaciones} | Gestión de gasto: Historial De Orden De Gasto 2 | rango completo 2017-2026, reemplaza |
| indicadores | IndicadoresProyectos.xlsx (plan indicativo) | — |
| contratos_maestro | descartado por el usuario (datos personales innecesarios) | — |

Regla de descarga: reportes de documento presupuestal → por vigencia; reportes de
contrato (entidad que cruza años) → rango completo. Anotar la fecha de descarga:
los saldos son la foto de ese día.

## El modelo conceptual (verificado con los datos)

Cadena: apropiación → CDP (afectación preliminar) → RP/compromiso (definitiva, con
tercero) → obligación (recibo a satisfacción) → orden de pago → giro. Al cierre:
CDP sin comprometer se libera; RP sin obligar → reserva (o debe anularse); obligación
sin pagar → cuenta por pagar. Reservas y CxP ejecutan en bases propias con salto
temporal v−1. Vigencias futuras (marginales aquí) y pasivos exigibles (crecientes)
son las dos figuras que cruzan años. El POAI es la puerta de la inversión: proyecto
(BPIN) → apropiación → cadena; la columna PROYECTO es la llave transversal y forma
parte del grano de las tablas.

Todas las bases cuadran AL PESO entre sí (mismo motor transaccional). El grano
declarado es documento × rubro × fondo × proyecto, con líneas múltiples posibles:
agregar siempre antes de cruzar.

## Hallazgos abiertos (para informes o para Hacienda)

1. **Cierre 2025**: $108.299M de RP sin obligar, solo $29.874M reservados;
   ~$78.400M ni obligados, ni reservados, ni anulados — candidatos a pasivo exigible.
2. **Pasivos exigibles crecientes**: $24.900M pagados en solo el primer semestre de
   2026 (máximo de la serie), concentrados en vías.
3. **3 CxP con pagos duplicados exactos** (11847: 2×$897M dic 9-10/2025; 11845: 2×;
   11472: 3× mismo día): comprobantes reales distintos, sin reversión visible.
   PENDIENTE: reporte de órdenes de pago con filtro de vigencias expiradas/CxP para
   ver si hay anulaciones (el de estados 2025 no las cubre).
4. **$207.700M de inversión 2025 con PROYECTO=0** (17%): no rastreable por BPIN.
5. **2023**: el consolidado de obligaciones mezcla 35 obligaciones de reservas
   (RPs de 2022, $7.613M); no existen reportes de reservas 2022-2023.
6. Anulaciones de RP 2026 atípicas: $75.211M en 9 imputaciones (15× el nivel histórico).
7. 24 imputaciones de obligación sin contraparte en su RP (0,06%, toleradas en la suite).

## Pendientes

- [HECHO 2026-07-18] Historial de contratos regenerado 2017-2026: solo +9 contratos
  pre-2022 (el modulo contractual arranca en la practica en 2022).
- Cobertura contractual actual: ordengasto 96,1% + historial por RP = 97,4%;
  quedan 257 grupos ($28.617M, convenios salud 2024 y licitaciones) sin ficha.
  Opcion pendiente de decision: recargar el maestro de contratos PODADO (sin columnas
  personales) para recuperar el 99,6%.
- Descargar bitácora (comprobantes), CxP y órdenes de pago por estado para las demás
  vigencias.
- Resolver el caso de pagos duplicados de CxP (hallazgo 3).
- Posibles mejoras de app: integrar historial de contratos (interventor, actas) al
  explorador; oportunidad de pago (días obligación→giro) con la bitácora.

## Convenciones acordadas

- Tipos: identificadores Utf8 (aunque parezcan números), VIGENCIA Int, valores
  Float64, fechas Date. Ordenar con cast en la expresión.
- Conciliaciones con `full` join + `fill_null(0)` + tolerancia de 1 peso.
- Redacción sobria: sin frases grandilocuentes ni metáforas sostenidas.
