# Reporte de Excel por ODBC: la vista `reportes.seguimiento_proyectos`

El equipo tiene un reporte en Excel conectado por ODBC a la base de datos de Supabase, para
verlo actualizado sin exportar nada del aplicativo. Esta carpeta guarda las consultas de ese
reporte, para que queden versionadas junto con el código y se actualicen cuando cambien los
modelos.

## Archivos

| archivo | para qué |
|---|---|
| `vista_seguimiento_proyectos.sql` | **La que se usa.** La consulta de la vista `reportes.seguimiento_proyectos`: una fila por proyecto con los nombres de columna del reporte. Su encabezado resume cómo crearla. |
| `auditoria_consulta_original.sql` | La consulta que escribió el equipo en el SQL editor de Supabase, con correcciones menores y una nota de lo que se cambió y lo que no. Es de referencia (auditoría): no se usa para la vista. |
| `README.md` | Este documento. |

La prueba `seguimiento_poai/siifweb/tests/test_sql_reportes.py` lee los dos scripts y falla si
nombran una tabla o una columna que ya no existe en los modelos, o si la vista repite un nombre
de columna o tiene uno de más de 63 bytes.

## Por qué una vista

Al principio el reporte unía las tablas en Power Query y cada actualización tomaba unos 10
minutos: Power Query trae las tablas completas y hace las uniones en el computador. Con la vista,
la base hace todo el trabajo y Excel solo recibe el resultado: unos 5 segundos para los 706
proyectos.

La vista no guarda datos: es una consulta guardada con nombre. Cada vez que Excel la lee, la
base la calcula con los datos del momento.

## Qué trae la vista

Una fila por proyecto (`siifweb_proyecto`). Cada bloque de información se suma o se agrupa por
proyecto **antes** de unirlo, así ninguna unión multiplica las filas.

| columnas | de dónde sale |
|---|---|
| DEPENDENCIA, BPIN, NOMBRE DEL PROYECTO | el proyecto y su dependencia responsable (POAI) |
| META VIGENCIA PROGRAMADA | la programación física del aplicativo: una línea por vigencia, meta del PDD y valor |
| META VIGENCIA FICHA PIIP | las metas por vigencia de la ficha PIIP (solo las distintas de cero): vigencia, indicador y meta |
| PROGRAMACIÓN FINANCIERA | la programación financiera del aplicativo: una línea por vigencia, fuente, meta del PDD y valor |
| VALOR PROGRAMADO | el total de la programación financiera, todas las vigencias |
| CLASIFICACIÓN | las clasificaciones del proyecto (POAI 2026, Recursos del Balance...) |
| VALOR CDP / RP / OBLIGACIÓN / PAGADO | la suma de las imputaciones del proyecto en todas las vigencias |
| ... VIGENCIA ACTUAL | lo mismo, solo los documentos de la vigencia del año en curso (hora de Colombia); cambia sola el 1 de enero |
| RADICADO, REGISTRADO y los 10 pasos del trámite | la casilla (verdadero/falso), su fecha y **SOPORTE ...: Sí / No** |
| TIEMPO DE EJECUCIÓN, MEDIDA DE TIEMPO, CONTRATACIÓN DIRECTA | campos del proyecto |
| CONTRATOS SIIFWEB | los contratos del historial de orden de gasto con imputación al proyecto |
| PROCESOS CONTRACTUALES SECOP II, CONTRATOS SECOP II | lo del reporte de SECOP II para el BPIN; los cancelados se incluyen con su estado |
| OBSERVACIONES | las observaciones del proyecto, con su fecha |
| AVISO LÍMITE DE CARACTERES DE EXCEL | qué columnas de texto pasan de 32.767 caracteres en ese proyecto |

Detalles que conviene saber:

- **Los valores totales mezclan vigencias** (2022 en adelante); por eso cada uno tiene al lado
  el de la vigencia actual. Lo que se le atribuye al proyecto sale de las imputaciones, no del
  valor de los documentos (ver `docs/CONCEPTOS_PRESUPUESTALES.md`).
- **Los soportes salen como Sí / No.** El archivo está en el almacenamiento privado del
  aplicativo y no se abre desde Excel.
- **Límite de Excel:** una celda admite máximo 32.767 caracteres. En los proyectos con muchos
  contratos o procesos (por ejemplo el 202500000028880, con más de 600 registros en SECOP II) la
  lista no se ve completa en Excel. La columna de aviso dice cuáles. Para ver el detalle completo,
  conviene una consulta aparte por BPIN.
- **Líneas:** en las listas cada elemento va en su línea; en contratos y procesos, separados por
  una línea en blanco. En Excel hay que tener **Ajustar texto** en esas columnas.
- **Uniones:** lo de SIIFWEB, la programación, la ficha PIIP y las observaciones se une por el id
  del proyecto. Lo de SECOP II se une por el texto del BPIN, porque la tabla de SECOP guarda
  siempre el BPIN pero a veces no tiene el proyecto enlazado.
- **Nombres de columna:** Postgres corta los nombres de más de 63 bytes y cada letra con tilde
  ocupa 2. Por eso dos nombres van sin el "DE" después de "ASIGNACIÓN".

## Crear la vista (primera vez)

En Supabase: **SQL Editor → New query**, con el usuario del panel.

1. Copie de `vista_seguimiento_proyectos.sql` todo lo que va **desde la línea que empieza con
   `with` hasta el final** (sin el encabezado de comentarios).
2. Ejecute, pegando la consulta donde se indica:

   ```sql
   create schema if not exists reportes;

   drop view if exists reportes.seguimiento_proyectos;

   create view reportes.seguimiento_proyectos as
   <la consulta>;
   ```

   El aviso de "security definer view" es normal: la vista lee las tablas con los permisos de
   quien la creó, y así el usuario de Excel no necesita permiso sobre las tablas.
3. Pruebe:

   ```sql
   select count(*) from reportes.seguimiento_proyectos;
   select * from reportes.seguimiento_proyectos limit 5;
   ```

## Usuario de solo lectura para Excel (una sola vez)

```sql
create role reporte_excel login password 'UNA-CLAVE-LARGA';
grant usage on schema reportes to reporte_excel;
grant select on reportes.seguimiento_proyectos to reporte_excel;
```

Ese usuario solo puede leer la vista: no ve las tablas del aplicativo ni puede cambiar nada.
Aunque alguien tenga el archivo de Excel con la conexión, no puede dañar la base. La clave no va
en este repositorio.

El esquema `reportes` no debe aparecer en **Project Settings → Data API → Exposed schemas**
(por defecto solo están `public` y `graphql_public`), para que la vista no quede publicada en la
API de Supabase.

## Conectar Excel

1. En Supabase, botón **Connect** → conexión **Session pooler**: anote el host y el puerto
   (5432).
2. Conexión ODBC con el controlador **PostgreSQL Unicode** (con el ANSI las tildes de los
   nombres se ven mal):
   - Server: el host del Session pooler
   - Port: 5432
   - Database: `postgres`
   - User: `reporte_excel.<id del proyecto>` (el id es lo que va después de `postgres.` en la
     cadena del Session pooler)
   - Password: la del usuario de solo lectura
   - SSL Mode: `require`
3. Excel: **Datos → Obtener datos → Desde otras fuentes → ODBC** → la conexión → **reportes →
   seguimiento_proyectos** → **Cargar**. Para actualizar: **Datos → Actualizar todo**.

La red debe permitir el puerto 5432: algunas redes (oficinas, wifi públicos) lo bloquean.

En Excel se puede renombrar, calcular, filtrar o quitar columnas (Power Query o fórmulas en la
tabla) sin tocar la vista; también escribir un SELECT propio sobre la vista en las opciones
avanzadas del ODBC. Si un paso de Power Query usa una columna y esa columna cambia de nombre en
la vista, el paso falla con "no se encontró la columna".

## Actualizar la vista

**Si el cambio solo altera el contenido** de las columnas (no su nombre, orden ni tipo de dato):

```sql
create or replace view reportes.seguimiento_proyectos as
<la consulta nueva>;
```

El permiso del usuario de Excel se mantiene.

**Si el cambio renombra, reordena, quita columnas o cambia su tipo**, Postgres no deja usar
`create or replace`. Hay que borrar y crear, en un solo bloque para que, si algo falla, la vista
anterior quede intacta (en ese caso, ejecutar `rollback;`):

```sql
begin;
drop view if exists reportes.seguimiento_proyectos;
create view reportes.seguimiento_proyectos as
<la consulta nueva>;
grant select on reportes.seguimiento_proyectos to reporte_excel;
commit;
```

Excel no se entera: mientras la vista se llame igual, la conexión sigue funcionando.

## Cuidado con las migraciones del aplicativo

La vista depende de columnas de las tablas del aplicativo. Si una migración de Django cambia o
borra una de esas columnas, el `migrate` que corre Railway al desplegar falla ("cannot alter ...
because other objects depend on it") y el despliegue no termina. Cuando una migración toque esas
columnas:

1. Actualizar `vista_seguimiento_proyectos.sql` (la prueba `test_sql_reportes.py` avisa).
2. Antes de subir, borrar la vista en Supabase: `drop view reportes.seguimiento_proyectos;`.
3. Subir y esperar a que Railway termine.
4. Volver a crear la vista y dar el permiso (sección "Actualizar la vista", segundo bloque).

Agregar tablas o columnas nuevas no afecta la vista.

## Historial

- **24/11/2026:** revisión de la consulta original del equipo. Se corrigió la fecha de última
  publicación de SECOP II (mostraba la de recepción de respuestas), los contratos sin tercero o
  sin centro de costo (desaparecían por un `inner join`), el orden de las listas y la hora de las
  observaciones. La vista nueva usa columnas explícitas (el `select *` repetía `bpin` once veces y
  no se podía guardar como vista), valores total y de la vigencia actual, soportes Sí / No y el
  aviso del límite de Excel.
- **25/11/2026:** nombres y orden de columnas del reporte; programación financiera con el detalle
  por vigencia, fuente, meta y valor; línea en blanco entre contratos y procesos.
