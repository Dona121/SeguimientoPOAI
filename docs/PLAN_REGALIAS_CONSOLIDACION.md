# Plan de la base de proyectos de regalías (consolidación de los reportes de GESPROY)

Documento autocontenido, redactado el 27 de noviembre de 2026 con las decisiones tomadas ese
día. Reúne lo que hace hoy el aplicativo de consolidación, cómo queda en `seguimiento_poai`, el
modelo de datos, las reglas de carga, los cálculos y el plan por fases. Sirve para continuar el
trabajo en otra conversación sin el historial.

**Origen:** `C:\Users\Donal\Documents\MEGA\Estudio\python\Consolidacion Regalias` (Streamlit,
repositorio `Dona121/ConsolidacionRegalias`, paquete `consolidacion/`). **Destino:** este
repositorio, proyecto Django `seguimiento_poai`, app nueva `regalias`.

**Prioridad.** Este plan va primero. Las pantallas de hitos, alertas, evaluación, IGPR y el
Excel global de la otra app de Streamlit ("Seguimiento Regalias") quedan para después y se
construirán sobre la tabla de proyectos de este plan.

### Estado al 28 de noviembre de 2026 y cómo retomar

El trabajo se hizo desde una sesión abierta en el repo del Streamlit
(`Estudio/python/Consolidacion Regalias`). Se sigue desde una sesión en este repo:

1. Leer este bloque y `docs/CAMBIOS_2026-10.md` §28 (regalías) y §29 (lo que cambió en `siifweb`).
2. Leer `respaldo_claude/memory/modulo-regalias.md`.

- **En producción.** Todo está en `main`, que es `regalias-base` por avance rápido.
  - Commits: `0ca566b` (fases 1 a 5), `a47307d` (`siifweb`, §29), `d9b55da` (fases 6 y 7),
    `39b0b09` (documentación), `cc90510` (entidades ejecutoras sin repetir) y el del menú con
    esta documentación.
  - Railway aplicó `siifweb/0029` y `regalias/0001` a `0013` el 28/11 a las 03:06 UTC.
- **Datos en producción** (27/11 en la noche, a pedido del usuario y después de su copia de
  Supabase):
  - se cargaron con `cargar_regalias` desde los archivos locales de `Regalias octubre/`: la
    matriz de octubre y después CG-proy, CG-cttos y CG-carga del 20/11;
  - quedan 226 proyectos (106 del departamento, 16 descentralizadas y 104 de municipios), 289
    contratos y 251 comentarios, igual que en la sqlite local;
  - las entidades ejecutoras repetidas por la tilde (SINCE y SINCÉ) se juntaron con
    `homologar_entidades_ejecutoras`; quedan 50.
- **Cómo se corrieron los comandos contra producción:** con un script de la sesión que toma la
  base de `seguimiento_poai/.env` sin mostrarla. Antes de cargar, el script verificaba que la base
  fuera PostgreSQL y que no quedaran migraciones sin aplicar. Las migraciones las aplicó Railway.
  De aquí en adelante los reportes se suben desde el admin.
- **Cambios en `siifweb`**, pedidos por el usuario el 27/11 (§29 de CAMBIOS):
  - la programación financiera y la física ya no exigen las mismas vigencias;
  - la financiera va por entidad aportante (`EntidadAportante`, migración `0029`);
  - el BPIN y el nombre van separados por un guion;
  - las casillas solo se colorean cuando tienen error.
  - "Entidades aportantes" sale una sola vez en el menú, en Configuración y parametrización.
- **Fases:**

  | Fase | Estado |
  |---|---|
  | 1. Base | Hecha |
  | 2. Cálculos | Hecha |
  | 3. Comentarios | Hecha |
  | 4. Importación de la matriz | Hecha (en producción, el 27/11) |
  | 5. Cargas de GESPROY | Hecha (en producción, los reportes del 20/11) |
  | 6. Programación | Hecha (con la entidad aportante, migraciones 0012 y 0013) |
  | 7. Descarga de la matriz | Hecha |
  | 8. Producción | En curso: desplegado y con datos; falta el ciclo en paralelo con el Streamlit |

- **Pruebas:** `manage.py test regalias` da 109; la suite completa, 740. Todas pasan.
- **Datos en la sqlite local:** los mismos proyectos y contratos que producción, más el historial
  desde marzo (§15), la programación de prueba que dejó el usuario y el usuario `prueba_regalias`
  (rol Regalías), que solo existe en la sqlite local. El servidor local está apagado.
- **Comandos** (desde `seguimiento_poai`, siempre con `DATABASE_URL` apuntando a la sqlite
  local; ver `respaldo_claude/memory/pruebas-en-sqlite-local.md`):

  ```bash
  export DATABASE_URL="sqlite:///C:/Users/Donal/Documents/MEGA/Paginas/Siifweb/seguimiento_poai/db.sqlite3"
  ../.venv/Scripts/python.exe manage.py test regalias
  ../.venv/Scripts/python.exe manage.py cargar_regalias proyectos "ruta/CG-proy.xlsx" --fecha 20/11/2026
  ../.venv/Scripts/python.exe manage.py homologar_entidades_ejecutoras    # sin --aplicar solo muestra
  DEBUG=True ../.venv/Scripts/python.exe manage.py runserver   # para revisar el admin
  ```

- **Pendiente:**
  1. Crear las entidades aportantes en producción, porque el catálogo está vacío, y asignar la
     entidad a los 2 valores de SIIFWEB que no la tienen (proyecto pk 815, vigencia 2027).
  2. Un ciclo de reportes en paralelo con el Streamlit, y comparar las dos matrices (§10, fase 8).
  3. Decidir si la búsqueda en las listas de proyectos debe encontrar también los cerrados (hoy
     respeta el filtro de estado).
  4. Preguntas 8 y 9 de §12: municipios de fuera de Sucre y EN PROCESO DE CONTRATACIÓN en los
     cálculos.
  5. Si se corrige en el Streamlit el error del contrato principal (§14), mientras corran en
     paralelo.
  6. Revisar el nombre "FundaciónBotánica yZoológica deBarranquilla", que viene así, sin
     espacios, de la matriz.

---

## 0. Decisiones tomadas (27 de noviembre de 2026)

| Tema | Decisión |
|---|---|
| App aparte | `regalias` es una **app de Django nueva**. No se modifica código de `siifweb` ni de `cuipo`: sus modelos y utilidades se importan, no se cambian. Las pantallas parecidas a las de SIIFWEB (programación, comentarios) se copian y adaptan dentro de `regalias`. Fuera de la app solo se toca `config/settings.py`: `INSTALLED_APPS` y la sección del menú |
| Tabla base | `ProyectoRegalias`: **una fila por BPIN**, como `siifweb.Proyecto`. Cada carga crea los BPIN nuevos y actualiza los existentes. No se guarda una copia de la matriz por corte |
| Clasificación | FK a `ClasificacionRegalias`: Departamento, Descentralizada, Municipio. Las tres viven en la misma tabla |
| Edición | **Todos los campos de datos se pueden editar en las tres clasificaciones.** Los calculados (días y fórmulas) son de solo lectura y se recalculan al guardar |
| Regla de carga | **General: solo se actualizan los campos de las llaves que aparecen en el reporte** (BPIN en proyectos; BPIN + número de contrato en contratos). Lo que no viene, o viene vacío, se deja como está |
| Datos del contrato principal | Los 7 campos del proyecto que salen del contrato principal se copian **cada vez que cambia un contrato**, por la carga de CG-cttos o por una edición en el admin. Guardar el proyecto no los toca: se respeta lo digitado (§5.4) |
| Qué se carga desde el sistema | **Solo los tres reportes de GESPROY** (decisión del 27/11). La matriz no se carga desde el admin: se importa **una sola vez**, con el comando `cargar_regalias matriz`, antes de los reportes (§6) |
| Contratos | Se **reemplazan por BPIN** en cada carga de CG-cttos (decisión del 27/11, §3.4) |
| Proyectos cerrados | **Todos los BPIN de CG-proy entran**, también CERRADO y DESAPROBADO. El seguimiento se filtra por estado |
| Descentralizadas y municipios | Los reportes de GESPROY no los traen. El equipo los crea y diligencia en el sistema |
| Fecha de corte | **Campo manual de cada proyecto.** Los cálculos usan la fecha de corte del proyecto |
| Valores y fuentes | **Ya no vienen de GESPROY.** Salen de la programación financiera del proyecto (vigencia, fuente SGR, producto y valor). VALOR PAGOS sí se sigue tomando de CG-proy |
| Fuentes | Modelo propio `FuenteSGR` (no las fuentes de SIIFWEB) con clasificación SGR, Nación, Otros u Otras fuentes no SUIFP. **No se migran**: las asigna el equipo |
| Productos e indicadores | Programación financiera por **producto** (`ProductoCatalogo`, catálogo PIIP); programación física por **indicador** (`IndicadorCatalogo`). No se usa el catálogo del plan de desarrollo porque muchos productos de regalías no están en él. El equipo agrega en el admin los que falten |
| Sector | FK a **`SectorMGA`** (el sector de GESPROY es el sector MGA). `SectorPDD` no sirve: cuelga de la línea estratégica del plan |
| Estado del proyecto | FK a un modelo de estados. Un reporte puede traer proyectos sin estado: la carga los crea igual, sin estado, y los lista en el mensaje. El formulario exige el estado, así que el equipo debe asignarlo después de la carga. Las listas tienen el filtro "Sin estado" |
| Municipios | ManyToMany a `siifweb.Municipio` |
| Entidad | Dos campos: `dependencia` (FK a `DependenciaResponsable`, donde ya están las descentralizadas) y `entidad_ejecutora` (modelo nuevo, para los municipios) |
| Comentarios | Modelo aparte, `ComentarioProyectoRegalias`, con FK a `ProyectoRegalias` y la lógica de las observaciones de SIIFWEB (texto y usuario; editable 5 días y solo por quien lo escribió). No se usa la tabla de SIIFWEB |
| Historial | Modelo aparte con cada cambio de campo: fecha, campo, valor anterior, valor nuevo y usuario. Se registra al cargar y al guardar |
| Rol | **Regalías**: consolida, ve y edita los modelos de regalías, con los permisos necesarios sobre los catálogos de SIIFWEB que usa (§9). Ningún otro acceso a SIIFWEB |
| Decimales | Avances e índice de eficiencia en la terminación con 6 dígitos y 3 decimales (llegan a 100). CPI y SPI con 5 dígitos y 3 decimales |
| Descarga de la matriz | **Con fórmulas**, como hoy. Las fórmulas llevan las correcciones de §7.6, así que el Excel y el sistema dan el mismo resultado |
| Enlace con SIIFWEB | No se agrega por ahora |
| Fuera | La columna FECHA DE SUSPENSIÓN DEL CONTRATO (está en la matriz de junio, pero la consolidación no la produce) |
| Polars | No entra. Lectura con openpyxl y las utilidades de `siifweb.cargas` |

---

## 1. Objetivo

Reemplazar el aplicativo de Streamlit "Consolidación de regalías". Hoy toma tres reportes de
GESPROY y la matriz del mes anterior, los cruza por BPIN y genera un Excel en el que el equipo
llena a mano las columnas manuales. En el aplicativo nuevo:

- los proyectos viven en la base, uno por BPIN;
- los reportes de GESPROY actualizan los campos que traen;
- lo manual se diligencia en el admin;
- las fórmulas del Excel se calculan en Python;
- la matriz se descarga desde el sistema.

Cuando esté validado, se apaga el Streamlit y se quita del menú el enlace "Consolidación de
regalías".

---

## 2. Lo necesario para trabajar

### 2.1 El aplicativo de origen

| Archivo | Qué tiene |
|---|---|
| `app_matriz_seguimiento.py` | Interfaz: carga de los 4 archivos, validación, consolidación, tabla de fechas conservadas y descarga |
| `consolidacion/esquemas.py` | Columnas esperadas de cada reporte y de cada hoja de la matriz, con su tipo |
| `consolidacion/lectura.py` | Lectura de los reportes (fila 1 título, fila 2 encabezados, sin espacios) y normalización de fechas |
| `consolidacion/validacion.py` | Mensajes de "qué pasó / cómo corregirlo" por columna faltante o tipo incorrecto |
| `consolidacion/procesamiento.py` | Cruces por BPIN, contrato principal, prioridad GESPROY sobre lo manual |
| `consolidacion/calculos.py` | Los 3 campos de días |
| `consolidacion/formulas.py` | Las fórmulas de Excel (§7.4) |
| `consolidacion/columnas.py`, `diseno.py`, `escritura.py` | Orden de columnas, secciones, colores y formato del Excel |
| `Contexto/MatrizSeguimientoEvaluacion_20260609_1833.xlsx` | Matriz real de junio, con los valores de las fórmulas ya calculados por Excel |

### 2.2 Los reportes de GESPROY

Muestras reales del 6 de abril de 2026 en
`C:\Users\Donal\Documents\MEGA\Reportes\plan_indicativo\Plataformas\Gesproy`. Los tres solo
traen proyectos del departamento ("DEPARTAMENTO DE SUCRE").

| Reporte | Hoja | Fila 1 (título) | Filas | Columnas que se usan |
|---|---|---|---|---|
| CG-proy | `proy` | PROYECTOS | 103 BPIN (CERRADO 37, CONTRATADO EN EJECUCIÓN 27, TERMINADO 12, DESAPROBADO 10, SIN CONTRATAR 7, PARA CIERRE 6, CONTRATADO SIN ACTA DE INICIO 4) | BPIN, NOMBRE PROYECTO, SECTOR, ESTADO PROYECTO, VALOR PAGOS. Para el aviso de §5.6: VALOR SGR, VALOR NACIÓN, VALOR OTROS, VALOR OTRAS FUENTES NO SUIFP, VALOR TOTAL PROYECTO |
| CG-cttos | `cttos` | CONTRATOS | 269 contratos de 87 BPIN | Ver §3.4 |
| CG-carga | `carga` | CARGUE INFORMACIÓN EN GESPROY-SGR | 128 BPIN (25 no están en CG-proy) | BPIN, AVANCE FISICO, AVANCE FINANCIERO, FECHA APROBACIÓN PROYECTO |

Detalles de los archivos:
- Los encabezados traen tabulaciones y espacios al inicio (`\tBPIN`, `' ESTADO CONTRATO'`).
- ESTADO CONTRATO y otros textos traen espacios al final.
- En CG-cttos, el par BPIN + CONTRATO NUMERO **es único y nunca viene vacío**. 7 contratos
  financian varios proyectos (EJECUTA VARIOS PROYECTOS = S) y aparecen una vez por cada BPIN.
- CG-carga trae FECHA_CORTE (la fecha del reporte). No se usa: la fecha de corte es manual.

### 2.3 La matriz actual

Libro con 3 tablas de Excel. Ningún BPIN se repite dentro de una tabla ni entre tablas.

| Tabla | Proyectos | Columnas |
|---|---|---|
| `MatrizSeguimientoEvaluacion` | 58 | 54 (53 + FECHA DE SUSPENSIÓN DEL CONTRATO, que no entra) |
| `OtrosEjecutoresDescentralizadas` | 16 | 42 |
| `OtrosEjecutoresMunicipios` | 102 | 19 |

Valores que importan para la importación (§6):
- **ENTIDAD O SECRETARIA:** Planeación, Salud, Desarrollo Económico, Educación, Infraestructura,
  Energía.
- **EJECUTOR de Descentralizadas:** EMPRESA AGUAS DE SUCRE S.A. E.S.P., FONDO MIXTO DE PROMOCION
  DE LA CULTURA Y LAS ARTES DE SUCRE, INSTITUTO DEPARTAMENTAL DE DEPORTES Y RECREACION DE SUCRE
  INDERSUCRE.
- **EJECUTOR de Municipios:** 49 distintos (municipios, AGROSAVIA, universidades…).
- **RESPONSABLE CARGUE EN GESPROY:** 6 personas; algunas celdas tienen dos, separadas por salto
  de línea.
- **MUNICIPIOS:** nombres separados por coma ("Morroa, Colosó").
- **Estados:** en Municipios hay un "SIN CONTRATAR " con espacio al final.
- **FUENTE e INDICADOR DE PRODUCTO MGA:** texto libre con variantes, a veces dos fuentes en una
  celda.

### 2.4 Destino: convenciones de `seguimiento_poai`

- **Cargas**: `siifweb/cargas.py` tiene `leer_filas`, `texto`, `fecha`, `decimal`;
  `siifweb/admin.py` tiene `hash_archivo`. `cuipo` los reutiliza; `regalias` también. Para los
  reportes de GESPROY se agrega en `regalias/lectura.py` la búsqueda de la fila de encabezado (la
  primera fila con una celda `BPIN`).
- **Patrón de carga**: el de `siifweb.CargaReporte` y `cuipo.CorteEjecucionGastos`:
  - archivo, tipo, fecha de descarga, hash, filas, estado (P/OK/E) y mensaje;
  - se procesa en `save_model`;
  - acción "Volver a procesar".
- **Almacenamiento**: `FileField` con el storage por defecto (`S3NombresSeguros`: sin tildes
  ni eñes en el nombre).
- **Pantallas propias**: método del `ModelAdmin` en `get_urls`, envuelto en
  `admin_site.admin_view`. Cada vista revisa su permiso y responde 403.
- **Plantillas**: extienden `admin/base_site.html`. Unfold no trae todas las clases de Tailwind:
  alineación y tamaños van en `<style>` acotado.
- **Programación**: `siifweb/programacion_financiera.py` (pantalla con pestañas financiera y
  física, un bloque por vigencia, aviso de descuadres entre pestañas). Se adapta para regalías
  (§3.3).
- **Observaciones**: `ObservacionProyectoSiifweb` (texto y usuario, migración
  `0028_observacion_con_usuario`, en `main` desde el 27/11). Se puede editar o borrar durante
  5 días, y solo quien la escribió.
- **Menú**: `UNFOLD["SIDEBAR"]` en `config/settings.py`, cada enlace con `_con_permiso(...)`.
- **Roles**: grupos creados por migración de datos; pruebas en `<app>/tests/test_roles.py`.
- **Pruebas**: `<app>/tests/` con `fabricas.py`, contra la sqlite local:
  `DATABASE_URL=sqlite:///C:/Users/Donal/Documents/MEGA/Paginas/Siifweb/seguimiento_poai/db.sqlite3`.
  Nunca contra Supabase.
- **Despliegue**: se trabaja en una rama desde `main`. Un push a `main` despliega en Railway, que
  corre las migraciones en `preDeployCommand`.

---

## 3. Modelo de datos (app `regalias`)

Todos heredan de `siifweb.models.Fechas` (creación y actualización).

### 3.1 Catálogos

| Modelo | Campos | Quién los mantiene |
|---|---|---|
| `ClasificacionRegalias` | `codigo` (departamento, descentralizada, municipio; único), `nombre` | Migración de datos. Solo lectura en el admin |
| `EstadoProyectoRegalias` | `codigo` (único), `nombre` (único), `orden` | Migración de datos con los 7 estados de GESPROY: SIN CONTRATAR, CONTRATADO SIN ACTA DE INICIO, CONTRATADO EN EJECUCIÓN, TERMINADO, PARA CIERRE, CERRADO, DESAPROBADO. Los cálculos comparan por `codigo`, no por texto |
| `FuenteSGR` | `nombre` (único), `clasificacion` (choices: SGR, Nación, Otros, Otras fuentes no SUIFP) | El equipo |
| `EntidadEjecutora` | `nombre` (único), `nit` (opcional) | El equipo (la importación crea las de la matriz) |
| `ResponsableGesproy` | `nombre` (único) | El equipo (la importación crea los de la matriz) |

De SIIFWEB se usan `SectorMGA`, `DependenciaResponsable`, `Municipio`, `ProductoCatalogo` e
`IndicadorCatalogo`.

### 3.2 `ProyectoRegalias`

"Origen" dice qué lo actualiza además de la edición manual. Todos los campos que no dicen
"calculado" se pueden editar en las tres clasificaciones.

| Campo | Tipo | Origen | Columna de la matriz |
|---|---|---|---|
| `clasificacion` | FK `ClasificacionRegalias`, PROTECT | Manual (CG-proy crea en Departamento) | (la hoja) |
| `bpin` | CharField(25), único | Llave | BPIN |
| `nombre` | TextField | CG-proy | NOMBRE PROYECTO / NOMBRE DEL PROYECTO |
| `alcance` | TextField, blank | Manual | ALCANCE DEL PROYECTO / ALCANCE |
| `sector` | FK `SectorMGA`, nulo, PROTECT | CG-proy, por nombre | SECTOR |
| `dependencia` | FK `DependenciaResponsable`, nulo, PROTECT | Manual | ENTIDAD O SECRETARIA (Departamento), EJECUTOR (Descentralizadas) |
| `entidad_ejecutora` | FK `EntidadEjecutora`, nulo, PROTECT | Manual | EJECUTOR (Municipios) |
| `municipios` | M2M `Municipio` | Manual | MUNICIPIOS |
| `responsables_cargue` | M2M `ResponsableGesproy` | Manual | RESPONSABLE CARGUE EN GESPROY |
| `estado` | FK `EstadoProyectoRegalias`, PROTECT, `null=True, blank=False`: puede estar vacío en la base (cargas), pero el formulario lo exige | CG-proy, por nombre | ESTADO PROYECTO |
| `estado_contrato` | CharField(100), blank | CG-cttos (contrato principal) | ESTADO CONTRATO |
| `tipo_contrato` | CharField(150), blank | CG-cttos (contrato principal) | TIPO CONTRATO |
| `fuentes` | TextField, calculado | Programación financiera (§7.5) | FUENTE DE FINANCIACIÓN / FUENTE |
| `valor_sgr`, `valor_nacion`, `valor_otros`, `valor_otras_no_suifp`, `valor_total` | Decimal(20,5), calculados | Programación financiera (§7.5) | VALOR SGR, VALOR NACIÓN, VALOR OTROS, VALOR OTRAS FUENTES NO SUIFP, VALOR TOTAL PROYECTO / VALOR TOTAL |
| `valor_pagos` | Decimal(20,5), nulo | CG-proy | VALOR PAGOS |
| `indicadores_mga` | TextField, calculado | Programación física (§7.5) | INDICADOR DE PRODUCTO MGA |
| `avance_fisico`, `avance_financiero` | Decimal(6,3), nulos | CG-carga | AVANCE FISICO / AVANCE FÍSICO, AVANCE FINANCIERO |
| `cpi`, `spi` | Decimal(5,3), nulos | Manual | CPI, SPI |
| `indice_eficiencia_terminacion` | Decimal(6,3), nulo (puede llegar a 100) | Manual | ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN |
| `fecha_aprobacion` | Date, nulo | CG-carga | FECHA APROBACIÓN PROYECTO |
| `fecha_apertura_primer_proceso` | Date, nulo | CG-cttos (principal) | FECHA DE APERTURA DEL PRIMER PROCESO |
| `fecha_suscripcion_principal` | Date, nulo | CG-cttos (principal) | FECHA DE SUSCRIPCIÓN DEL CONTRATO PRINCIPAL |
| `fecha_suscripcion_primer_contrato` | Date, nulo | CG-cttos (la más antigua) | FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO |
| `fecha_acta_inicio` | Date, nulo | CG-cttos (principal) | FECHA ACTA INICIO |
| `fecha_ultimo_pago` | Date, nulo | CG-cttos (principal) | ULTIMA FECHA PAGO |
| `fecha_migracion_gesproy`, `fecha_asignacion_recursos`, `fecha_incorporacion_recursos` | Date, nulos | Manual | FECHA DE MIGRACIÓN A GESPROY, FECHA DE ASIGNACIÓN DE RECURSOS, FECHA DE INCORPORACIÓN DE RECURSOS |
| `horizonte`, `fecha_finalizacion`, `fecha_para_cierre` | Date, nulos | Manual | HORIZONTE DEL PROYECTO, FECHA DE FINALIZACIÓN, FECHA EN LA QUE PASO A ESTADO PARA CIERRE |
| `fecha_corte` | Date, nulo | Manual | FECHA DE CORTE GESPROY |
| `informacion_solicitada`, `informacion_recibida` | TextField, blank | Manual | INFORMACIÓN SOLICITADA, INFORMACIÓN RECIBIDA |
| `fecha_recibo_informacion` | Date, nulo | Manual | FECHA DE RECIBO DE INFORMACIÓN |
| `control_externalidades` | PositiveSmallInteger, nulo | Manual | CONTROL EXTERNALIDADES (número de externalidades) |
| `cal_desempeno_contratacion`, `cal_calidad_informacion` | Decimal(6,3), nulos | Manual | CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN, CALIFICACIÓN CALIDAD INFORMACIÓN |
| `cal_informacion_a_tiempo` | Decimal(6,3), nulo | **Calculado en Departamento** (solo lectura ahí); manual en las otras | CALIFICACIÓN INFORMACIÓN A TIEMPO |
| `dias_aprobacion_a_apertura`, `dias_apertura_a_firma`, `dias_suscripcion_a_acta` | Integer, nulos, calculados | §7.3 | Las 3 columnas DIAS DESDE… |
| `desempeno_cronograma`, `desempeno_costo`, `columna_apoyo`, `brecha_fisico_financiera`, `columna_apoyo_2`, `cal_ejecucion` | Decimal(6,3), nulos, calculados | §7.4 | Las columnas de fórmula |
| `ejecucion_revisar` | Boolean, calculado | §7.4 | El "Revisar" de CALIFICACIÓN EJECUCIÓN DEL PROYECTO |

Los avances se guardan en porcentaje (0–100).

### 3.3 Programación

**`ProgramacionFinancieraRegalias`:**
- Campos: `proyecto` (FK, CASCADE), `vigencia` (choices `listado_vigencias_metas`),
  `entidad_aportante` (FK `siifweb.EntidadAportante`, PROTECT), `fuente` (FK `FuenteSGR`,
  PROTECT), `producto` (FK `ProductoCatalogo`, PROTECT) y `valor` (Decimal(20,5), no negativo).
- No se repite la combinación proyecto + vigencia + entidad aportante + fuente + producto.
- **Entidad aportante** (decisión del 27/11): un proyecto puede tener recursos de varias
  entidades.
  - Es el catálogo de SIIFWEB, que lleva la misma regla en su programación financiera. El rol
    Regalías lo ve y le agrega entidades (migración 0013).
  - Va con `null=True, blank=False`, como en SIIFWEB: la sqlite local tenía programación de
    prueba. En producción no hay programación de regalías.
  - La pantalla agrupa las fuentes de cada vigencia por entidad. Lo que no tiene entidad sale
    como "Sin entidad aportante", con el botón "Asignar entidad", y mientras tenga valor la
    pestaña no se guarda.

**`ProgramacionFisicaRegalias`:**
- Campos: `proyecto`, `vigencia`, `indicador` (FK `IndicadorCatalogo`, PROTECT) y `valor`
  (Decimal(20,5)).
- No se repite la combinación proyecto + vigencia + indicador.

Se diligencian en una pantalla "Programación" del proyecto, con la estructura de
`siifweb/programacion_financiera.py`:
- **Pestañas:** financiera y física, con un bloque por vigencia.
- **Financiera:** entidades aportantes y, debajo de cada una, sus fuentes en las filas;
  productos en las columnas.
- **Física:** indicadores en las filas.
- **Vigencias:** las de las dos pestañas no tienen que coincidir. Un proyecto puede tener
  fuentes en 2025 y 2027 y la meta física en 2026 (caso real, decisión del 27/11). Cada
  pestaña muestra solo sus vigencias, y la relación entre las dos es por producto en todo el
  proyecto.
- **Espejo:** una vigencia nueva de la financiera empieza con los productos de los indicadores
  de la física, de cualquier vigencia, y se pueden quitar. Al agregar un producto o un
  indicador salen primero los que tiene la otra pestaña.
- **Aviso de descuadre:** en lugar de "metas distintas entre pestañas", avisa cuando un
  producto con valor financiero no tiene ningún indicador con valor físico, o un indicador con
  valor físico no tiene valor financiero de su producto, en ninguna vigencia. Avisa pero no
  bloquea, como en SIIFWEB.
- **Código:** se copia y adapta en `regalias`. `siifweb/programacion_financiera.py` no se
  modifica.

### 3.4 `ContratoRegalias`

`proyecto` (FK, CASCADE, `related_name="contratos"`). **Sin llave propia** (decisión del 27/11,
migración 0008): los contratos de cada BPIN que viene en CG-cttos se reemplazan por las filas del
reporte; los BPIN que no vienen conservan los suyos. Se probó primero con BPIN + número + fecha
de suscripción, cargando los reportes de marzo a noviembre de 2026, y no sirvió:
- GESPROY cambió la fecha de suscripción de 12 contratos de un mes a otro, y cada cambio dejaba
  el contrato viejo guardado como otro. En 5 proyectos eso alteraba el contrato principal y en
  otros 5 la fecha del primer contrato.
- Hasta agosto, los dos CONV-RE-SDED-028-2022 de los BPIN 2021000100333 y 2021000100370 tenían
  la misma fecha de suscripción, y uno pisaba al otro.

| Campo | Tipo | Columna de CG-cttos |
|---|---|---|
| `numero` | CharField(100) | CONTRATO NUMERO |
| `numero_proceso` | CharField(100) | NO. PROCESO PRECONTRACTUAL |
| `modalidad` | CharField(150) | MODALIDAD CONTRATACION |
| `tipo` | CharField(150) | TIPO CONTRATO |
| `objeto` | TextField | CONTRATO OBJETO |
| `estado` | CharField(100) | ESTADO CONTRATO |
| `valor_total` | Decimal(20,5) | CONTRATO VALOR TOTAL |
| `valor_en_proyecto` | Decimal(20,5) | VALOR CONTRATO EN EL PROYECTO |
| `valor_fuentes_sgr` | Decimal(20,5) | VALOR TOTAL FUENTES SGR |
| `pago_ejecutado` | Decimal(20,5) | PAGO EJECUTADO VALOR |
| `nit_contratista`, `nombre_contratista` | CharField(30), CharField(255) | NIT CONTRATISTA, NOMBRE CONTRATISTA |
| `fecha_acto_apertura` | Date | FECHA ACT ADTIVO APERT |
| `fecha_suscripcion` | Date | FECHA SUSCRIPCION |
| `fecha_inicial` | Date | FECHA INICIAL |
| `fecha_final`, `fecha_final_real` | Date | FECHA FINAL, FECHA FINAL REAL |
| `fecha_primer_pago`, `fecha_ultimo_pago` | Date | PRIMERA FECHA PAGO, ULTIMA FECHA PAGO |
| `plazo`, `unidad_plazo` | Decimal(8,2) (GESPROY trae 8,27 meses), CharField(30) | PLAZO CONTRACTUAL, UNIDAD PLAZO CONTRACTUAL |
| `ejecuta_varios_proyectos` | Boolean | EJECUTA VARIOS PROYECTOS (S/N) |
| `es_principal` | Boolean, calculado | §5.4 |

Las columnas de la app de hitos (proceso, modalidad, objeto, valor, fecha final y final real)
quedan cubiertas para la etapa posterior.

### 3.5 `CargaRegalias`

| Campo | Tipo | Nota |
|---|---|---|
| `tipo` | choices: `proyectos` (CG-proy), `contratos` (CG-cttos), `cargue` (CG-carga), `matriz` (importación inicial) | El IGPR se agregará en la etapa posterior |
| `archivo` | FileField `regalias/` | |
| `fecha_descarga` | Date, por defecto `timezone.localdate` | |
| `usuario` | FK al usuario, SET_NULL | Quien sube. Es el usuario del historial de esa carga |
| `hash`, `filas`, `estado` (P/OK/E), `mensaje` | | Igual que `CargaReporte`. El mismo archivo en el mismo tipo se rechaza |

### 3.6 `CambioProyectoRegalias` (historial)

| Campo | Tipo |
|---|---|
| `proyecto` | FK, CASCADE, `related_name="cambios"` |
| `campo` | CharField(100): el nombre del campo (verbose_name) |
| `valor_anterior`, `valor_nuevo` | TextField: el valor como texto; las FK con su `str`, las M2M como lista ordenada |
| `usuario` | FK al usuario, SET_NULL |
| `origen` | choices: edición, carga, importación, programación, acción masiva |
| `carga` | FK `CargaRegalias`, nulo, SET_NULL |
| (fecha) | `fecha_creacion` de `Fechas` |

Se registran todos los campos de `ProyectoRegalias`, incluidos los calculados y los M2M. Todo lo
que escribe un proyecto pasa por un único servicio (`regalias/servicios.py:guardar_proyecto`):
1. toma la foto de los valores;
2. aplica los cambios;
3. recalcula;
4. guarda;
5. registra las diferencias.

Lo usan el admin, las cargas, la importación, las acciones masivas y las señales de la
programación. Las M2M se comparan en `save_related`.

### 3.7 Comentarios

`ComentarioProyectoRegalias`, modelo aparte con la lógica de `ObservacionProyectoSiifweb`:
- **Campos:** `proyecto` (FK a `ProyectoRegalias`, CASCADE), texto y usuario.
- **Edición:** solo quien lo escribió lo puede editar o borrar, durante 5 días.
- **Pantalla:** copia adaptada de la de SIIFWEB, dentro de `regalias`.
- **Excel:** la columna de comentarios lleva el último comentario.

---

## 4. Regla general de actualización

Para cada carga:
1. **Llave presente**: se actualizan los campos que el reporte trae **con valor**. Un valor
   vacío en el reporte no borra lo que hay.
2. **Llave ausente**: el proyecto o el contrato no se toca.
3. **Solo CG-proy crea proyectos** (en Departamento). CG-cttos y CG-carga solo actualizan BPIN
   que ya existen; los que no encuentran se listan en el mensaje.
4. Después de aplicar los cambios, los proyectos tocados se recalculan (§7) y cada cambio queda
   en el historial con la carga y su usuario.
5. Volver a procesar una carga da el mismo resultado (la regla es idempotente).

Normalización antes de comparar:
- textos sin espacios al inicio ni al final;
- BPIN con `texto()`;
- nombres de catálogo (sector, estado, municipio, dependencia) comparados en mayúscula, sin
  tildes y con espacios simples.

---

## 5. Cargas de GESPROY

### 5.1 Flujo en el admin

1. **Cargas de regalías → Añadir.** Elegir tipo (CG-proy, CG-cttos o CG-carga; la matriz no se
   ofrece), archivo y fecha de descarga. Guardar.
2. Se valida que el título de la fila 1 corresponda al tipo (PROYECTOS, CONTRATOS o CARGUE
   INFORMACIÓN EN GESPROY-SGR). Si no corresponde, se rechaza con el tipo que parece ser.
3. Se procesa al guardar. El resultado queda en `estado` y `mensaje`.
4. Acción **Volver a procesar**. Sirve, por ejemplo, para cargar CG-cttos antes de que su BPIN
   exista y reprocesarlo después de CG-proy.

Orden recomendado: CG-proy, CG-cttos, CG-carga.

### 5.2 Lectura y validación

- **Encabezado:** la primera fila con una celda `BPIN`, con los nombres sin tabulaciones ni
  espacios.
- **Columnas obligatorias faltantes:** error con la lista y el mensaje de "cómo corregirlo" de
  `consolidacion/validacion.py`.
- **Valores que no se pueden leer como fecha o número:** aviso con columna, BPIN y valor. Ese
  campo no se actualiza.

### 5.3 CG-proy

Por fila:
- **BPIN nuevo:** se crea en Departamento.
- **Campos que actualiza:** `nombre`, `sector` (SectorMGA por nombre), `estado` (por nombre) y
  `valor_pagos`.
- **Sector o estado que no se reconoce:** el campo no cambia y se avisa.
- **BPIN nuevo sin estado** (vacío o no reconocido): se crea sin estado y se lista en el mensaje
  como "pendiente de asignar estado". En un BPIN existente, un estado vacío no borra el que
  tiene.

### 5.4 CG-cttos y el contrato principal

1. Por cada BPIN que viene y existe, sus contratos se borran y se crean los de las filas del
   reporte, en el mismo orden. Los BPIN que no existen se listan. El mensaje lista los BPIN cuyo
   número de contratos cambió.
2. Por cada uno de esos BPIN se elige el principal **entre sus contratos**, con
   la prioridad de hoy (`_seleccionar_contrato_por_bpin`):
   1. tipos prioritarios: Obra pública, Consultoría, Convenios de Cooperación,
      Interadministrativos;
   2. secundarios: Suministro, Contratos o convenios con entidades sin ánimo de lucro;
   3. cualquier otro.

   Dentro del grupo, el de mayor valor de fuentes SGR.
3. Se marca `es_principal` y se actualizan en el proyecto, solo si tienen valor:
   - `estado_contrato`, `tipo_contrato`;
   - `fecha_apertura_primer_proceso` (acto de apertura del principal);
   - `fecha_suscripcion_principal`;
   - `fecha_acta_inicio` (fecha inicial del principal);
   - `fecha_ultimo_pago`;
   - `fecha_suscripcion_primer_contrato` (la fecha de suscripción más antigua entre todos los
     contratos del proyecto).
4. Lo mismo pasa cuando un contrato se crea, cambia o se borra en el admin. Pasa por
   `guardar_proyecto`, con origen "edición" y el usuario que editó el contrato. Guardar el
   proyecto no copia nada de los contratos: se respeta lo digitado hasta que cambie un contrato.

### 5.5 CG-carga

Actualiza `avance_fisico`, `avance_financiero` y `fecha_aprobacion` de los BPIN que ya existen.

### 5.6 Mensaje

Por ejemplo: "CG-proy · 103 filas · N proyectos nuevos · N actualizados · N cambiaron de
estado · N sectores no reconocidos".

El mensaje lleva además:
- las listas de BPIN no encontrados y de valores no leídos;
- los proyectos que quedaron sin estado, para que el equipo se lo asigne;
- para los proyectos que ya tienen programación, los BPIN cuyo total de CG-proy no coincide con
  el total programado.

---

## 6. Importación inicial de la matriz

Se hace **una sola vez**, con el comando `manage.py cargar_regalias matriz <ruta>`. No se carga
desde el sistema: el formulario de cargas no ofrece el tipo `matriz` (decisión del 27/11). Queda
como una carga de tipo `matriz`, sin archivo guardado. Se usa el libro de las 3 tablas, la última
matriz que tenga el equipo.

**Primero la matriz y después los reportes más recientes, nunca al revés.** La importación
escribe también los campos que traen los reportes, así que una matriz importada encima de
reportes más nuevos los devolvería a sus valores viejos (§15).

- **Crea los proyectos de las tres clasificaciones** y aplica la regla general a todos los
  campos de datos.
- **Asigna por nombre:**
  - el estado (con espacios limpios). Una fila sin estado reconocido se crea sin estado y se
    lista; en la matriz de junio todas lo tienen;
  - el sector (los de la matriz usan los mismos nombres MGA);
  - los municipios (separados por coma);
  - los responsables (separados por salto de línea; se crean los que no existan);
  - la entidad ejecutora de Municipios (se crean las que no existan).
- **Dependencia:** tabla de equivalencias en el código.

  | Matriz | `DependenciaResponsable` |
  |---|---|
  | Planeación | Secretaría de Planeación |
  | Salud | Secretaría de Salud |
  | Desarrollo Económico | Secretaría de Desarrollo Económico y Medio Ambiente |
  | Educación | Secretaría de Educación |
  | Infraestructura | Secretaría de Infraestructura |
  | Energía | Secretaría de Energías |
  | FONDO MIXTO DE PROMOCION DE LA CULTURA Y LAS ARTES DE SUCRE | Fondo Mixto de Cultura |
  | INSTITUTO DEPARTAMENTAL DE DEPORTES Y RECREACION DE SUCRE INDERSUCRE | Instituto Departamental de Deportes y Recreación |
  | EMPRESA AGUAS DE SUCRE S.A. E.S.P. | Plan Departamental de Aguas |

- **No migra** fuentes, valores ni indicadores. Para que el equipo los tenga a mano al
  programar, la importación deja un primer comentario por proyecto con lo que traía la matriz:
  "Datos de la matriz anterior: fuente …; indicador …; valor SGR …; valor otros …; valor total
  …". También pasa como comentario el texto de COMENTARIOS CALIFICACIÓN / COMENTARIOS.
- **No importa las columnas calculadas.** Se recalculan y se comparan con las de la matriz en la
  prueba de paridad (§11).
- **Mensaje:** conteos por clasificación y lo que no se pudo asignar.
- **En producción, por definir.** El asistente no corre comandos contra Supabase; las migraciones
  las aplica Railway. Hay dos caminos:
  - el usuario corre el comando con la `DATABASE_URL` de producción;
  - una migración de datos de un solo uso que lea la matriz incluida en el repositorio. Esta
    opción también correría en la base de pruebas, salvo que se excluya.

  Pregunta abierta.

---

## 7. Campos calculados

### 7.1 Cuándo

- Al guardar un proyecto (formulario o acción masiva).
- Después de cada carga, para los proyectos tocados.
- Desde la señal de la programación (§7.5).

Funciones puras en `regalias/calculos.py`: reciben el proyecto y devuelven los valores, para
probarlas sin base de datos.

### 7.2 Convención: vacíos como en Excel

Hoy son fórmulas de Excel. Para dar los mismos resultados:
- `n(x)` es el valor, o 0 si está vacío (Excel trata la celda vacía como 0 al comparar y operar).
- "Vacío" es el `""` de Excel: en la base, nulo.
- Operar con un resultado vacío es un error de Excel; la fórmula lo atrapa con SI.ERROR.
- `en_ejecucion` = estado CONTRATADO EN EJECUCIÓN.
- Resultados redondeados a 3 decimales.

**Variantes por clasificación:**
- **Departamento:** usa la variante de la hoja principal.
- **Descentralizadas y Municipios:** usan la variante de descentralizadas. En Municipios hoy no
  hay cálculos; quedan vacíos mientras no se diligencien los datos que usan.

### 7.3 Días

Coinciden con los hitos 0, 2 y 3 de la app de hitos. Si falta cualquiera de los datos (el estado
o alguna de las dos fechas), el campo queda vacío.

| Campo | Estado | Valor | Hito |
|---|---|---|---|
| `dias_aprobacion_a_apertura` | SIN CONTRATAR, tenga o no apertura | fecha de corte − fecha de aprobación | H0 |
| `dias_apertura_a_firma` | SIN CONTRATAR | fecha de corte − fecha de apertura del primer proceso | H2 |
| `dias_suscripcion_a_acta` | CONTRATADO SIN ACTA DE INICIO | fecha de corte − fecha de suscripción del contrato principal | H3 |

`dias_apertura_a_firma` cambia respecto a hoy (§7.6).

### 7.4 Fórmulas (hoy `formulas.py`, con las correcciones de §7.6)

**Desempeño en el cronograma (con SPI) y en el costo (con CPI).** Si no es `en_ejecucion`,
vacío. Con `v = n(SPI)` o `n(CPI)`:

| v | Resultado |
|---|---|
| > 1,3 | 0 |
| > 1,25 y ≤ 1,3 | 30 |
| > 1,2 y ≤ 1,25 | 90 |
| ≥ 0,84 y ≤ 1,2 | 100 |
| ≥ 0,38 y < 0,84 | (v − 0,38) / (0,84 − 0,38) × 100 |
| < 0,38 | 0 |

**Columna apoyo** (sin condición de estado). `af = n(avance financiero)`,
`b = af − n(avance físico)`:

| af | 100 si | Si no |
|---|---|---|
| < 60 | b ≤ 50 | 0 |
| ≥ 60 y < 70 | b ≤ 40 | 0 |
| ≥ 70 y < 80 | b ≤ 30 | 0 |
| ≥ 80 y < 90 | b ≤ 20 | 0 |
| ≥ 90 y ≤ 100 | b ≤ 10 | 0 |
| > 100 | vacío | |

**Brecha físico-financiera.** Si no es `en_ejecucion`, vacío. En ejecución, en este orden (con
`n()` en los avances):
1. Físico > financiero → 100.
2. Financiero > físico y b > 50 → 0.
3. Financiero > físico, b ≤ 50 y af ≤ 60 → 100.
4. Financiero > físico, b ≤ 50 y af > 60 → columna apoyo.
5. En otro caso (por ejemplo, físico = financiero) → vacío.

**Columna apoyo 2**, por `e = n(control de externalidades)`: 0 → 100, 1 → 90, 2 → 75, 3 → 60,
4 → 50, 5 → 25, 6 o más → 0.

**Calificación de información a tiempo** (solo Departamento):
- sin fecha de recibo → vacío;
- día del mes 10 → 100, 11 → 80, 12 → 50, cualquier otro → 0.

En las otras clasificaciones se digita.

**Calificación de ejecución del proyecto:**
- `hay_informacion`:
  - Departamento: `informacion_solicitada` tiene texto;
  - las otras clasificaciones: `cal_informacion_a_tiempo` tiene valor.
- `ponderado = cronograma × 0,4 + costo × 0,2 + brecha × 0,4`. Si alguno es vacío, el ponderado
  es vacío.
- `calculo` = `ponderado` si `hay_informacion`; si no, vacío.
- Si `en_ejecucion`:
  1. Horizonte y fecha de corte con valor y horizonte < fecha de corte → 0.
  2. Si no, con externalidades ≥ 1 → `calculo × columna apoyo 2 / 100`. Si `calculo` es vacío,
     es un error de Excel: en Departamento queda vacío con `ejecucion_revisar = True` (hoy
     "Revisar"); en las otras, vacío.
  3. Si no → `calculo`.
- Si el estado es CONTRATADO SIN ACTA DE INICIO:
  - si falta la fecha de corte o la de suscripción del primer contrato → vacío;
  - si no, `d = fecha de corte − fecha de suscripción del primer contrato`, y da 100 si
    0 ≤ d ≤ 30 o 0 en otro caso.
- Cualquier otro estado → vacío.

### 7.6 Diferencias con el Excel actual (decididas el 27 de noviembre de 2026)

| Qué | Hoy en el Excel | En el sistema | Efecto con la matriz de junio |
|---|---|---|---|
| SPI o CPI = 1,2 | Vacío en el desempeño, y por eso en la calificación de ejecución | 100 | Ninguno: no hay índices en 1,2 |
| Sin acta de inicio con alguna fecha faltante | 0 si falta una; 100 si faltan las dos | Vacío | Ninguno: los 4 sin acta tienen las dos fechas |
| Días desde la apertura hasta la firma | Acta de inicio − apertura, siempre vacío | Fecha de corte − apertura | 3 proyectos sin contratar con apertura pasan de vacío a 71, 37 y 91 días |
| Brecha fuera de ejecución | Las reglas 3 y 4 daban valor en cualquier estado | Vacío | 5 proyectos TERMINADO pasan de 100 a vacío. No cambia ninguna calificación |

En la fase 2 se compara primero la réplica exacta del Excel con la matriz de junio. Después se
aplican estas cuatro diferencias, cada una con sus pruebas.

### 7.5 Valores desde la programación

- **`fuentes`:** los nombres distintos de las fuentes con valor en la programación financiera,
  ordenados y unidos con ", ".
- **Valores por clasificación:** `valor_sgr`, `valor_nacion`, `valor_otros` y
  `valor_otras_no_suifp` suman los valores de las fuentes de cada clasificación, en todas las
  vigencias.
- **`valor_total`:** la suma de todo.
- **`indicadores_mga`:** "código - nombre" de los indicadores de la programación física, unidos
  con "; " (los nombres traen comas).

Se recalculan con una señal al guardar o borrar programación, como `actualizar_valor_programado`
en SIIFWEB, y quedan en el historial con origen "programación".

---

## 8. Admin

- **Proyectos:** tres entradas del menú, Departamento, Descentralizadas y Municipios (modelos
  proxy filtrados por `clasificacion.codigo`).
  - Crear desde una de ellas fija la clasificación.
  - **Columnas de la lista:** BPIN, nombre, dependencia o entidad, estado, avances, fecha de corte
    y calificación de ejecución.
  - **Al entrar** la lista no trae los CERRADO ni los DESAPROBADO (decisión del 27/11): el filtro
    de estado abre en "Sin cerrados ni desaprobados" y tiene "Todos". Siguen existiendo: se
    abren, se editan y salen en la matriz.
  - **Filtros:** estado (con las opciones "Todos" y "Sin estado"), sector, dependencia o entidad, fecha de
    corte y "Revisar".
  - **Búsqueda:** BPIN y nombre.
- **Formulario del proyecto:** grupos Identificación, Estado y contrato, Valores (solo lectura,
  con enlace a la programación), Avance, Fechas, Seguimiento, Calificaciones y Calculados (solo
  lectura). Sector, dependencia, entidad, municipios y responsables con búsqueda
  (`autocomplete_fields`). Los cinco catálogos de SIIFWEB que se usan ya tienen `search_fields`
  en sus admins, así que no hay que tocarlos.
- **Pantallas del proyecto:** botones en el formulario, como en SIIFWEB.
  - Programación (§3.3).
  - Contratos.
  - Comentarios.
  - Historial (solo lectura).
- **Acciones de la lista:**
  - **Asignar fecha de corte** a los seleccionados (y recalcular).
  - **Recalcular**.
  - **Descargar matriz** (`regalias/excel.py`): botón arriba de la lista, en las tres
    clasificaciones, sin seleccionar filas. Da el mismo Excel desde cualquiera de ellas.
    - **Estructura:** la de la matriz de octubre (`MatrizSeguimientoEvaluacion_corte_oct2026.xlsx`).
      - Las 3 hojas, con una tabla de Excel del mismo nombre desde la fila 2.
      - Las secciones combinadas en la fila 1.
      - El orden de columnas, los colores, los anchos, las alturas y los formatos de hoy
        (`consolidacion/columnas.py`, `diseno.py` y `escritura.py` del origen).
      - Las columnas de apoyo, ocultas.
      - Sin FECHA DE SUSPENSIÓN DEL CONTRATO.
    - **Proyectos:** los mismos que tiene la matriz de hoy.
      - Departamento: sin CERRADO ni DESAPROBADO, porque la consolidación los saca de CG-proy.
      - Descentralizadas y municipios: todos.
      - No usa los filtros de la lista.
    - **Columnas que salen del sistema:**
      - Comentarios: el último comentario del proyecto, sin contar la nota "Datos de la matriz
        anterior" de la importación.
      - Responsables, uno por línea.
      - Municipios, separados por coma.
      - Fuentes e indicador: los de la programación.
    - No copia los encabezados amarillos de la hoja de municipios de octubre (FUENTE y los tres
      valores): son marcas hechas a mano en ese archivo.
    - **Fórmulas:** las 7 columnas de fórmula del departamento y las 6 de descentralizadas van
      como fórmulas de Excel, igual que hoy (`consolidacion/formulas.py`), con las correcciones
      de §7.6. Municipios no tiene fórmulas.
    - **Valores:** lo demás va como valor, incluidos los días, como hoy.
    - **Librería:** se arma con openpyxl, que ya es dependencia, marcando el libro para que Excel
      recalcule al abrir.
    - **Uso:** el Excel es una salida. Lo que se cambie en el archivo no vuelve al sistema; los
      cambios se hacen en el admin.
- **Cargas de regalías:** se suben solo CG-proy, CG-cttos y CG-carga. La lista muestra también
  la importación de la matriz hecha con el comando. Tiene el estado, el mensaje y la acción
  Volver a procesar, que no sirve para las cargas del comando porque no guardan el archivo.
- **Contratos:** lista con filtros por proyecto, tipo, estado y principal.
- **Historial de cambios:** solo lectura, filtros por proyecto, campo, usuario, origen y fecha.
- **Catálogos:**
  - Fuentes SGR, Entidades ejecutoras y Responsables de cargue los edita el equipo.
  - Clasificaciones y Estados son de solo lectura.

---

## 9. Rol Regalías y menú

El grupo **Regalías** se crea con una migración de datos de la app `regalias`. Esa misma
migración le asigna los permisos sobre los catálogos de SIIFWEB, sin cambiar nada de `siifweb`.

| Modelos | Permisos |
|---|---|
| Proyectos (los tres proxy), contratos, cargas, fuentes SGR, entidades ejecutoras, responsables | Agregar, cambiar, ver |
| Programación financiera y física | Agregar, cambiar, ver, borrar (la pantalla borra los valores en cero, como en SIIFWEB) |
| Comentarios | Agregar, cambiar, ver, borrar (solo los propios y dentro de los 5 días) |
| Historial, clasificaciones, estados | Ver |
| `SectorMGA`, `DependenciaResponsable`, `Municipio` (SIIFWEB) | Ver (lo necesita la búsqueda del formulario) |
| `ProductoCatalogo`, `IndicadorCatalogo` (SIIFWEB) | Ver y agregar |

No tiene ningún otro permiso de SIIFWEB ni de CUIPO.

**Menú:** sección **Regalías** en `UNFOLD["SIDEBAR"]` con:
- Departamento, Descentralizadas y Municipios;
- Cargas;
- Contratos;
- Historial;
- Catálogos.

Cada enlace va con `_con_permiso(...)`.

---

## 10. Plan por fases

Cada fase en una rama desde `main`, con sus pruebas, y revisada antes de fusionar.

| Fase | Entrega | Cómo se valida |
|---|---|---|
| 1. Base | App `regalias` en `INSTALLED_APPS`, sin cambios en `siifweb` ni `cuipo`; catálogos con su migración de datos; `ProyectoRegalias`; `CambioProyectoRegalias` y `guardar_proyecto`; admin de las tres clasificaciones; rol Regalías y menú (la sección va antes de "Configuración y parametrización": una prueba de SIIFWEB exige que "Plan de Desarrollo" siga a "Seguimiento") | Pruebas de roles (lo que abre y lo que da 403); cada edición deja historial con usuario. **Hecha el 27/11 en la rama `regalias-base`**: 23 pruebas nuevas, suite completa en verde (647) |
| 2. Cálculos | `regalias/calculos.py`, recálculo al guardar, acciones Asignar fecha de corte y Recalcular | **Prueba de paridad**: con los datos de la matriz de junio, los calculados coinciden con los valores que Excel dejó en el archivo (tolerancia 0,001). Luego las diferencias de §7.6 y los casos de §11.2. **Hecha el 27/11** (`regalias/tests/test_calculos.py`). En los 74 proyectos del departamento y de descentralizadas solo difieren las correcciones 3 y 4 (días desde la apertura y brecha fuera de ejecución). La prueba lee la matriz desde `Consolidacion Regalias/Contexto/`, o desde `REGALIAS_MATRIZ_JUNIO`, y se salta si no está |
| 3. Comentarios | `ComentarioProyectoRegalias` y su pantalla, siguiendo la de observaciones de SIIFWEB (ya con usuario en `main`) | Editable 5 días y solo por quien lo escribió. **Hecha el 27/11**: botón "Comentarios" en el formulario de cada proyecto (copia adaptada de la pantalla de observaciones de SIIFWEB) y permisos del rol (migración 0009). Los importados de la matriz salen como "Importado de la matriz" y nadie los modifica. La lista general de comentarios es de consulta y no borra |
| 4. Importación inicial | `CargaRegalias` tipo `matriz`, equivalencias y comentario con los datos anteriores | **Hecha el 27/11** (§14): con la matriz de octubre, 58 + 16 + 104 proyectos |
| 5. Cargas de GESPROY | Tipos `proyectos`, `contratos`, `cargue`; regla general; contrato principal; mensaje; Volver a procesar | **Hecha el 27/11** (§14), con el comando `cargar_regalias` para cargar archivos locales. El principal difiere del de la consolidación en 23 BPIN por un error del Streamlit |
| 6. Programación | `FuenteSGR`, programación financiera y física, pantalla, valores calculados | Sumas por clasificación, concatenaciones y avisos de descuadre. **Hecha el 27/11** (migraciones 0010 y 0011, `regalias/programacion.py`, `regalias/tests/test_programacion.py`). Los valores del proyecto se recalculan al guardar la pantalla, en el mismo `servicios.guardar_proyecto`, y no con señales: así el historial queda con el usuario y no con un registro por casilla. Las listas de programación del admin son de consulta |
| 7. Descarga de la matriz | Acción Descargar matriz, con fórmulas | Mismas hojas, columnas y formato que el Excel de hoy. Al abrirlo en Excel, las fórmulas dan los mismos valores que el sistema. **Hecha el 27/11** (`regalias/excel.py`, `regalias/tests/test_excel.py`). Hojas, tablas, encabezados, secciones, colores, columnas ocultas y columnas de fórmula iguales a la matriz de octubre. Las fórmulas del archivo se evaluaron con pycel y dan lo mismo que el sistema: 502 con los datos locales y 564 con casos de las cuatro correcciones, sin diferencias. pycel no corre en Python 3.14 y por eso esa evaluación no está en la suite. La prueba de estructura contra la matriz de octubre se salta si el archivo no está (`REGALIAS_MATRIZ_OCTUBRE`) |
| 8. Producción | Migraciones por Railway; importación única de la matriz con el comando (§6; hecha el 27/11 con los reportes del 20/11); después, los reportes más recientes desde el admin; un ciclo de reportes en paralelo con el Streamlit | Las dos matrices coinciden proyecto por proyecto, salvo las diferencias de §7.6. Después se apaga el Streamlit y se quita el enlace del menú |

---

## 11. Casos de prueba

### 11.1 Cargas

- BPIN que no viene en el reporte: no cambia ningún campo ni deja historial.
- Valor vacío en el reporte: no borra el valor guardado.
- CG-proy con un BPIN nuevo: se crea en Departamento. Sin estado o con un estado no reconocido:
  se crea sin estado y se lista.
- El formulario no deja guardar un proyecto sin estado. Un proyecto sin estado no tiene días
  ni calificaciones calculadas. CG-cttos o CG-carga con un BPIN que no
  existe: no se crea y se lista.
- CERRADO y DESAPROBADO entran.
- Los contratos de un BPIN que viene se reemplazan por los del reporte; los de un BPIN que no
  viene (por ejemplo, una descentralizada con contratos digitados) se conservan.
- Dos filas con el mismo número y la misma fecha son dos contratos. Un cambio de fecha de
  suscripción no deja contratos sobrantes.
- Principal: un tipo prioritario de menor valor gana a uno secundario de mayor valor; empate de
  grupo, gana el de mayor valor SGR.
- Primer contrato: la suscripción más antigua entre todos los contratos del proyecto, aunque no
  sea el principal.
- Editar en el admin el estado del contrato principal: el proyecto toma el estado nuevo. Editar
  en el proyecto la fecha de acta de inicio y guardar: se conserva hasta que cambie un contrato.
- Mismo archivo en el mismo tipo: rechazado. Título de fila 1 que no corresponde: rechazado.
- Volver a procesar: mismo resultado, sin historial nuevo.

### 11.2 Cálculos

- SPI 1,3 → 30; 1,25 → 90; 1,2 → 100; 0,84 → 100; 0,61 → 50; 0,2 → 0; sin SPI y en
  ejecución → 0; otro estado → vacío.
- Columna apoyo con avance financiero 65 y brecha 40 → 100; 41 → 0; financiero 101 → vacío.
- Brecha en un proyecto TERMINADO con financiero mayor que físico → vacío.
- Días, sin contratar con aprobación y apertura: los de aprobación cuentan desde la aprobación y
  los de apertura desde la apertura, ambos hasta la fecha de corte. Sin apertura: solo los de
  aprobación. Sin fecha de corte, o en otro estado: vacíos.
- Días de suscripción a acta: sin acta de inicio con suscripción del principal → fecha de corte
  − suscripción. Sin la suscripción → vacío.
- En ejecución con horizonte vencido → 0 aunque el cálculo dé otro valor.
- En ejecución con externalidades 2 → cálculo × 0,75. Con externalidades 1 y sin información
  solicitada → vacío y "Revisar" en Departamento; vacío sin aviso en Descentralizadas.
- Sin acta de inicio con 30 días desde la suscripción del primer contrato → 100; 31 → 0; fecha
  de suscripción posterior al corte → 0; sin fecha de suscripción o sin fecha de corte → vacío.
- Información a tiempo con recibo el 10, 11, 12 y 13 de un mes → 100, 80, 50 y 0.

### 11.3 Roles e historial

- El rol Regalías abre todo lo de §9 y recibe 403 en las pantallas de SIIFWEB y CUIPO.
- Editar un campo deja una fila de historial con el valor anterior, el nuevo y el usuario. Una
  carga deja filas con la carga y su usuario.

---

## 12. Preguntas abiertas

1. **Comentarios.** Resuelta el 27/11: modelo aparte con FK a `ProyectoRegalias` (§3.7).
2. **Datos del contrato principal.** Resuelta el 27/11: se copian cada vez que cambia un
   contrato, no al guardar el proyecto (§5.4).
3. **Aguas de Sucre.** Resuelta el 27/11: corresponde a "Plan Departamental de Aguas" (§6).
4. **Excel con fórmulas.** Resuelta el 27/11: la matriz se descarga con fórmulas, con las
   correcciones de §7.6 (§8).
5. **Comportamientos de las fórmulas actuales.** Resuelta el 27/11: se corrigen los cuatro (§7.6).
   La calificación sin acta sigue usando la suscripción del primer contrato, como en el Excel de
   referencia.
6. **Índice de eficiencia en la terminación.** Resuelta el 27/11: puede llegar a 100, así que va
   con 6 dígitos y 3 decimales.
7. **Proyectos sin estado.** Resuelta el 27/11:
   - la carga puede dejarlos sin estado y los lista;
   - el formulario exige el estado, así que el equipo lo asigna después de la carga;
   - mientras no lo tengan, no se calculan sus días ni sus calificaciones.
8. **Municipios de fuera de Sucre.** La matriz de octubre trae 57 que no están en
   `siifweb.Municipio` (Barranquilla, Bogotá, Medellín…), casi todos en proyectos de municipios.
   No se crearon: quedan en el comentario "Datos de la matriz anterior" de cada proyecto.
   ¿Se agregan al catálogo de municipios de SIIFWEB?
9. **EN PROCESO DE CONTRATACIÓN en los cálculos.** Es un estado nuevo (4 proyectos en octubre).
   Las fórmulas solo miran SIN CONTRATAR, CONTRATADO SIN ACTA DE INICIO y CONTRATADO EN
   EJECUCIÓN, así que hoy no tiene días ni calificación. ¿Cuenta como SIN CONTRATAR para los
   días (hitos 0 y 2)?
10. **Importación de la matriz en producción.** Resuelta el 27/11. A pedido del usuario,
    Claude corrió el comando contra Supabase después de la copia de seguridad: la matriz de
    octubre y después los reportes del 20/11 (CAMBIOS §28).

---

## 13. Equivalencias Streamlit → Django

| Hoy (`consolidacion/`) | En `regalias` |
|---|---|
| `lectura.py` (polars) | `regalias/lectura.py` (openpyxl, `siifweb.cargas.leer_filas` y búsqueda de la fila de encabezado) |
| `esquemas.py` y `validacion.py` | Columnas obligatorias y mensajes del formulario de carga |
| `procesamiento.py` | `regalias/cargas.py`: regla general, contrato principal y primer contrato. Sin la versión anterior: lo anterior es lo que hay en la base |
| `calculos.py` y `formulas.py` | `regalias/calculos.py` (§7) |
| `columnas.py`, `diseno.py`, `escritura.py` y las fórmulas de `formulas.py` | `regalias/excel.py` (descarga de la matriz con fórmulas) |
| `app_matriz_seguimiento.py` | Admin de Unfold (§8) |
| Columnas manuales y "fechas conservadas" | Campos editables e historial |

---

## 14. Carga de octubre en la sqlite local (27 de noviembre de 2026)

**Archivos:** `Estudio/python/Consolidacion Regalias/Regalias octubre/`:
- `MatrizSeguimientoEvaluacion_corte_oct2026.xlsx`;
- `CG-proy`, `CG-cttos` y `CG-carga`, descargados el 20/11/2026.

Se cargaron con `manage.py cargar_regalias`, en orden, contra la sqlite local.

| Carga | Resultado |
|---|---|
| Matriz | 178 proyectos creados (58 del departamento, 16 descentralizadas, 104 municipios), 51 entidades ejecutoras, 6 responsables, 251 comentarios. Todos los estados, sectores y dependencias reconocidos |
| CG-proy | 106 filas: 48 proyectos nuevos (los 38 cerrados y 10 desaprobados que la matriz no trae) y 58 sin cambios |
| CG-cttos | 289 contratos de 92 BPIN; 48 proyectos tomaron los datos de su contrato principal. Volver a cargarlo no cambia nada |
| CG-carga | 106 filas: 49 proyectos actualizados |

Lo que salió de los datos reales:

- **Estado nuevo:** EN PROCESO DE CONTRATACIÓN (migración 0005). Ver la pregunta abierta 9.
- **Contratos con el mismo número:** primero se resolvió con una llave que incluía la fecha de
  suscripción. Después, con los reportes de marzo a noviembre, se cambió a reemplazar los
  contratos por BPIN (§3.4 y §15).
- **Plazo contractual con decimales:** pasa a Decimal(8,2) (migración 0007).
- **Lectura de los reportes:** declaran mal su tamaño (la hoja dice `A1:A1`). En modo read_only,
  openpyxl no ve filas sin `reset_dimensions()`, que es lo que hace `regalias/lectura.py`.
- **Dependencias:** "Oficina de innovación" se homologa con "Oficina de Innovación, Tecnología
  y Competitividad".
- **Municipios:**
  - los saltos de línea cortan nombres, así que se unen;
  - se separa por coma y por " y ";
  - Toluviejo, Sincé, Betulia y San Antonio de Palmito se homologan;
  - los 57 de fuera de Sucre quedan en el comentario (pregunta abierta 8).
- **Error del Streamlit de consolidación: el contrato principal.**
  - `preparar_contratos` lee VALOR TOTAL FUENTES SGR como texto y lo ordena alfabéticamente.
  - Ejemplo, BPIN 2023002700175: elige CPS-820-2024 ($9.000.000) en lugar de LP-002-2024
    ($19.692 millones), porque "9000000" va después de "19692001937".
  - Pasa en 23 de 92 BPIN con contratos: 15 activos en la matriz y 8 cerrados.
  - El sistema nuevo elige por valor numérico, así que en el ciclo en paralelo esas diferencias
    son esperadas, salvo que se corrija también el Streamlit.
- **Archivos en local:** el almacenamiento por defecto es el bucket de producción, y el `.env`
  de la carpeta trae sus llaves. Por eso en local se carga con el comando, que no sube el
  archivo. Subir una carga desde el admin local la mandaría al bucket.

---

## 15. Contraste de cargas de marzo a noviembre de 2026 (27 de noviembre de 2026)

Se borraron los datos de regalías de la sqlite local y se volvió a cargar todo en orden: los
reportes del 04/03, 06/04, 20/05, 10/06, 28/08 y 20/11; la matriz del 09/06 (`Contexto/`) como
importación inicial; y al final la matriz de octubre y otra vez los reportes de noviembre, para
dejar la base como la revisó el usuario. Fueron 23 cargas, ninguna con error.

| Reporte | CG-proy | Cambios de estado | CG-cttos | CG-carga |
|---|---|---|---|---|
| 04/03 | 102 BPIN | (creación) | 268 contratos, 86 BPIN | 125 filas |
| 06/04 | 103 (entra 2025000020006) | 6 | 269 contratos, 87 BPIN | 128 filas |
| 20/05 | 103 | 7 | 271 contratos, 87 BPIN | 128 filas; 1 avance físico baja |
| 10/06 | 105 (entran 2024702150036 y 2026002700007) | 1 | 273 contratos, 88 BPIN | 130 filas |
| 28/08 | 105 | 17 | 279 contratos, 91 BPIN | 130 filas; 2 avances bajan |
| 20/11 | 106 (entra 202600000027106) | 14 | 289 contratos, 92 BPIN | 106 filas |

Lo que muestra:

- **Ningún BPIN deja de venir en CG-proy.** Solo entran BPIN nuevos.
- **Un estado retrocede:** 2016000100048 pasó de TERMINADO a PARA CIERRE en junio y volvió a
  TERMINADO en noviembre. El sistema sigue lo que dice el reporte, y el historial deja ver la
  vuelta.
- **Avances que bajan** (lo reporta GESPROY): 2023002700175 (físico, 99,25 → 96,54, en mayo) y
  2013000100074 (financiero 97,17 → 92,55 y físico 95,65 → 94,25, en agosto). Puede servir como
  alerta en las pantallas de la etapa siguiente.
- **Contratos:**
  - con el reemplazo por BPIN, la base termina con los 289 contratos del reporte de noviembre;
  - cada mes el mensaje lista los BPIN cuyo número de contratos cambió (7 en noviembre), y el
    principal cambia en 1 a 6 proyectos por mes a medida que entran contratos.
- **INFLEX en CG-carga:** de marzo a agosto, CG-carga trae 25 filas con códigos `INFLEX-…` en
  lugar de BPIN. Quedan como "BPIN que no existen". El reporte de noviembre ya no las trae.
- **La matriz pisa los datos de GESPROY.**
  - Importar la matriz de octubre sobre los reportes de noviembre devolvió los campos de contrato
    a lo que decía la matriz (que arrastra el error del Streamlit de §14) y un avance a su valor
    viejo. La repetición de los reportes de noviembre lo corrigió.
  - Regla para producción: **la matriz se importa una sola vez, al inicio, y después se cargan
    los reportes más recientes**, nunca al revés.
  - En descentralizadas y municipios, que no vienen en los reportes, la matriz de octubre
    actualizó lo de junio: estados, avances, fechas de asignación, información solicitada y
    recibida, calificaciones.
