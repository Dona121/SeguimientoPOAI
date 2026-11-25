-- ============================================================================================
-- VISTA reportes.seguimiento_proyectos: una fila por proyecto, para el reporte de Excel (ODBC)
-- ============================================================================================
-- Version para la vista de la consulta revisada el 24/11/2026 (la original corregida, para
-- auditoria, es auditoria_consulta_original.sql). Probada en produccion en solo lectura.
--
-- CREARLA O ACTUALIZARLA, en el SQL editor de Supabase (con el usuario principal):
--
--   create schema if not exists reportes;
--   drop view if exists reportes.seguimiento_proyectos;
--   create view reportes.seguimiento_proyectos as
--   <todo lo que va desde "with" hasta el final de este archivo>;
--
--   Una sola vez, el usuario de solo lectura para el ODBC de Excel (cambie la clave):
--   create role reporte_excel login password 'CAMBIAR';
--   grant usage on schema reportes to reporte_excel;
--   grant select on reportes.seguimiento_proyectos to reporte_excel;
--   (al volver a crear la vista hay que repetir el grant select)
--
--   En el ODBC por el pooler de Supabase el usuario va como reporte_excel.<id del proyecto>.
--   Con el controlador "PostgreSQL Unicode" los nombres con tilde se ven bien.
--
-- OJO CON LAS MIGRACIONES: si una migracion de Django cambia o borra una columna que usa esta
-- vista, el migrate de Railway falla ("cannot alter ... because other objects depend on it").
-- Antes de subir esa migracion: borrar la vista, subir, y volver a crearla con este archivo
-- actualizado. La prueba siifweb/tests/test_sql_reportes.py avisa si este archivo nombra una
-- tabla o columna que ya no existe.
--
-- QUE TRAE:
-- - Lo de SIIFWEB, la programacion y la ficha PIIP se agrega por proyecto_id; lo de SECOP II
--   por el texto del BPIN (BpinProceso guarda siempre el BPIN, pero su proyecto puede quedar
--   vacio). Cada bloque se suma antes de unirlo: no se multiplican filas.
-- - VALOR CDP / RP / OBLIGACION / PAGADO: total de todas las vigencias, y al lado el de la
--   vigencia actual (el anio en curso en Colombia), por la vigencia del documento.
-- - PROGRAMACION FINANCIERA: una linea por vigencia, fuente, meta del PDD y valor (como
--   fuentes_programadas_por_proyecto de la consulta original). VALOR PROGRAMADO: el total de
--   todas las vigencias (Proyecto.valor_programado).
-- - META VIGENCIA PROGRAMADA: la programacion fisica, una linea por vigencia y meta del PDD.
-- - SOPORTE ...: Si / No (el archivo esta en el almacenamiento privado, no se abre desde Excel).
-- - Los procesos y contratos de SECOP II cancelados se incluyen: el estado va en el texto.
-- - En CONTRATOS SIIFWEB, PROCESOS CONTRACTUALES SECOP II y CONTRATOS SECOP II cada elemento
--   va separado por una linea en blanco, para que no se vea apilado en Excel.
-- - Un cambio que solo altera el contenido de las columnas (no su nombre, orden ni tipo) se
--   aplica con CREATE OR REPLACE VIEW, sin borrar la vista ni repetir el grant.
-- - AVISO LIMITE DE CARACTERES DE EXCEL: dice que columnas de texto pasan de 32.767 caracteres
--   (el maximo de una celda de Excel): en ese proyecto Excel no las muestra completas.
-- - Dos nombres de columna se acortaron (sin el "DE" despues de ASIGNACION) porque Postgres
--   corta los nombres de mas de 63 bytes y cada tilde cuenta doble.
-- ============================================================================================
with
vigencia_actual as (
  select extract(year from (now() at time zone 'America/Bogota'))::int as anio
),
programacion_financiera as (                 -- vigencia - fuente - meta PDD - valor
  select spf.proyecto_id,
         string_agg(concat(spf.vigencia, ' - ', sf.nombre, ' - ', smi.codigo, ' - ', round(spf.valor, 2)), E'\n'
                    order by spf.vigencia, sf.nombre, smi.codigo) as texto
  from siifweb_programacionfinanciera spf
  join siifweb_fuente sf on sf.id = spf.fuente_id
  join siifweb_metaindicador smi on smi.id = spf.meta_id
  group by spf.proyecto_id
),
programacion_fisica as (                     -- vigencia - meta PDD - meta fisica
  select spf.proyecto_id,
         string_agg(concat(spf.vigencia, ' - ', smi.codigo, ' - ', round(spf.valor, 2)), E'\n'
                    order by spf.vigencia, smi.codigo) as texto
  from siifweb_programacionfisica spf
  join siifweb_metaindicador smi on smi.id = spf.meta_id
  group by spf.proyecto_id
),
metas_piip as (                              -- metas por vigencia de la ficha PIIP
  select sf.proyecto_id,
         string_agg(concat(smvi.vigencia, ' - ', sic.codigo, ' - ', sic.nombre, ' - ', round(smvi.meta, 2)), E'\n'
                    order by smvi.vigencia, sic.codigo) as texto
  from siifweb_metavigenciaindicador smvi
  join siifweb_indicadorproyecto sip on sip.id = smvi.indicador_proyecto_id
  join siifweb_indicadorcatalogo sic on sic.id = sip.indicador_id
  join siifweb_formulacionproyecto sf on sf.id = sip.formulacion_id
  where smvi.meta <> 0 and sf.proyecto_id is not null
  group by sf.proyecto_id
),
clasificaciones as (
  select spc.proyecto_id, string_agg(sc.nombre, ', ' order by sc.nombre) as texto
  from siifweb_proyecto_clasificaciones spc
  join siifweb_clasificacion sc on sc.id = spc.clasificacion_id
  group by spc.proyecto_id
),
cdp as (
  select i.proyecto_id,
         sum(i.valor_disponibilidad_def) as total,
         sum(i.valor_disponibilidad_def) filter (where d.vigencia = (select anio from vigencia_actual)) as vigencia
  from siifweb_cdpimputacion i
  join siifweb_cdp d on d.id = i.cdp_id
  where i.proyecto_id is not null
  group by i.proyecto_id
),
rp as (
  select i.proyecto_id,
         sum(i.valor_compromiso_def) as total,
         sum(i.valor_compromiso_def) filter (where d.vigencia = (select anio from vigencia_actual)) as vigencia
  from siifweb_compromisoimputacion i
  join siifweb_compromiso d on d.id = i.compromiso_id
  where i.proyecto_id is not null
  group by i.proyecto_id
),
obligaciones as (
  select i.proyecto_id,
         sum(i.valor_obligacion) as total,
         sum(i.valor_obligacion) filter (where d.vigencia = (select anio from vigencia_actual)) as vigencia,
         sum(i.pagos) as pagado_total,
         sum(i.pagos) filter (where d.vigencia = (select anio from vigencia_actual)) as pagado_vigencia
  from siifweb_obligacionimputacion i
  join siifweb_obligacion d on d.id = i.obligacion_id
  where i.proyecto_id is not null
  group by i.proyecto_id
),
contratos_siifweb as (
  select c.proyecto_id,
         string_agg(concat('Tipo de contrato: ', c.tipo_contrato,
                           ', Valor del contrato: ', coalesce(c.valor_contrato::text, 'Sin valor'),
                           ', Número del contrato: ', c.nro_contrato,
                           ', Fecha de firma: ', coalesce(c.fecha_firma::text, 'Sin fecha'),
                           ', Nit: ', coalesce(c.nit, 'Sin nit'),
                           ', Contratista: ', coalesce(c.contratista, 'Sin nombre'),
                           ', Centro costo/dependencia en siifweb: ', coalesce(c.dependencia, 'Sin centro de costo')),
                    E'\n\n' order by c.fecha_firma nulls last, c.nro_contrato) as texto
  from (
    select distinct sci.proyecto_id, sc.id, sc.tipo_contrato, sc.valor_contrato, sc.nro_contrato, sc.fecha_firma,
           st.codigo as nit, st.nombre as contratista, scc.nombre as dependencia
    from siifweb_contratoimputacion sci
    join siifweb_contrato sc on sc.id = sci.contrato_id
    left join siifweb_tercero st on st.id = sc.tercero_id
    left join siifweb_centrocosto scc on scc.id = sc.dependencia_id
    where sci.proyecto_id is not null
  ) c
  group by c.proyecto_id
),
procesos_secop as (
  select x.bpin, string_agg(x.texto, E'\n\n' order by x.texto) as texto
  from (
    select distinct sbp.bpin,
           concat('Id proceso: ', sps.id_proceso,
                  ', Estado del procedimiento: ', coalesce(nullif(sps.estado_procedimiento, ''), 'Sin estado'),
                  ', Fecha de publicación: ', coalesce(sps.fecha_publicacion::text, 'Sin fecha'),
                  ', Fecha de última publicación: ', coalesce(sps.fecha_ultima_publicacion::text, 'Sin fecha'),
                  ', Fecha de recepción de respuestas: ', coalesce(sps.fecha_recepcion_respuestas::text, 'Sin fecha'),
                  ', Fecha de apertura de respuestas: ', coalesce(sps.fecha_apertura_respuestas::text, 'Sin fecha'),
                  ', Fecha de apertura efectiva: ', coalesce(sps.fecha_apertura_efectiva::text, 'Sin fecha'),
                  ', Contrato -> ', coalesce(nullif(scs.referencia, ''), 'Sin contrato')) as texto
    from siifweb_bpinproceso sbp
    join siifweb_procesosecop sps on sps.id = sbp.proceso_id
    left join siifweb_contratosecop scs on scs.id = sbp.contrato_secop_id
    where lower(sps.id_proceso) <> 'no definido'
  ) x
  group by x.bpin
),
contratos_secop as (
  select x.bpin, string_agg(x.texto, E'\n\n' order by x.texto) as texto
  from (
    select distinct sbp.bpin,
           concat('Id contrato: ', scs.id_contrato,
                  ', Referencia: ', coalesce(nullif(scs.referencia, ''), 'Sin referencia'),
                  ', Estado: ', coalesce(nullif(scs.estado, ''), 'Sin estado'),
                  ', Valor: ', coalesce(scs.valor::text, 'Sin valor'),
                  ', Fecha de Firma: ', coalesce(scs.fecha_firma::text, 'Sin fecha de firma'),
                  ', Fecha de inicio: ', coalesce(scs.fecha_inicio::text, 'Sin fecha de inicio'),
                  ', Fecha de fin: ', coalesce(scs.fecha_fin::text, 'Sin fecha de fin'),
                  ', Nit: ', coalesce(nullif(st.codigo, ''), 'Sin nit'),
                  ', Proveedor: ', coalesce(nullif(st.nombre, ''), 'Sin nombre proveedor')) as texto
    from siifweb_bpinproceso sbp
    join siifweb_contratosecop scs on scs.id = sbp.contrato_secop_id
    left join siifweb_tercero st on st.id = scs.proveedor_id
    where lower(scs.id_contrato) <> 'no definido'
  ) x
  group by x.bpin
),
observaciones as (
  select proyecto_id,
         string_agg(concat((fecha_actualizacion at time zone 'America/Bogota')::date, ': ', texto), E'\n'
                    order by fecha_creacion) as texto
  from siifweb_observacionproyectosiifweb
  group by proyecto_id
)
select
  sd.nombre                                                   as "DEPENDENCIA",
  sp.bpin                                                     as "BPIN",
  sp.nombre                                                   as "NOMBRE DEL PROYECTO",
  pfs.texto                                                   as "META VIGENCIA PROGRAMADA",
  mp.texto                                                    as "META VIGENCIA FICHA PIIP",
  pfn.texto                                                   as "PROGRAMACIÓN FINANCIERA",
  sp.valor_programado                                         as "VALOR PROGRAMADO",
  ccp.texto                                                   as "CLASIFICACIÓN",
  coalesce(cdp.total, 0)                                      as "VALOR CDP",
  coalesce(cdp.vigencia, 0)                                   as "VALOR CDP VIGENCIA ACTUAL",
  coalesce(rp.total, 0)                                       as "VALOR RP",
  coalesce(rp.vigencia, 0)                                    as "VALOR RP VIGENCIA ACTUAL",
  coalesce(ob.total, 0)                                       as "VALOR OBLIGACIÓN",
  coalesce(ob.vigencia, 0)                                    as "VALOR OBLIGACIÓN VIGENCIA ACTUAL",
  coalesce(ob.pagado_total, 0)                                as "VALOR PAGADO",
  coalesce(ob.pagado_vigencia, 0)                             as "VALOR PAGADO VIGENCIA ACTUAL",
  sp.radicado                                                 as "RADICADO",
  sp.fecha_radicacion                                         as "FECHA DE RADICACIÓN",
  case when coalesce(sp.soporte_radicacion, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE RADICACIÓN",
  sp.registrado                                               as "REGISTRADO",
  sp.fecha_registro                                           as "FECHA DE REGISTRO",
  case when coalesce(sp.soporte_registro, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE REGISTRO",
  sp.tiempo_ejecucion                                         as "TIEMPO DE EJECUCIÓN",
  sm.nombre                                                   as "MEDIDA DE TIEMPO",
  sp.decreto_liquidacion_inicial                              as "DECRETO DE LIQUIDACIÓN INICIAL",
  sp.fecha_decreto_liquidacion_inicial                        as "FECHA DECRETO DE LIQUIDACIÓN INICIAL",
  case when coalesce(sp.soporte_decreto_liquidacion_inicial, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE DECRETO DE LIQUIDACIÓN INICIAL",
  sp.contratacion_directa                                     as "CONTRATACIÓN DIRECTA",
  sp.gestion_recursos_piip                                    as "GESTIÓN DE RECURSOS EN PIIP",
  sp.fecha_gestion_recursos_piip                              as "FECHA GESTIÓN DE RECURSOS EN PIIP",
  case when coalesce(sp.soporte_gestion_recursos_piip, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE GESTIÓN DE RECURSOS EN PIIP",
  sp.asignacion_ajuste_decreto_et                             as "ASIGNACIÓN DE RECURSOS (AJUSTE A DECRETO ET)",
  sp.fecha_asignacion_ajuste_decreto_et                       as "FECHA DE ASIGNACIÓN DE RECURSOS (AJUSTE A DECRETO ET)",
  case when coalesce(sp.soporte_asignacion_ajuste_decreto_et, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE ASIGNACIÓN DE RECURSOS (AJUSTE A DECRETO ET)",
  sp.solicitud_concepto_traslado                              as "SOLICITUD CONCEPTO DE TRASLADO",
  sp.fecha_solicitud_concepto_traslado                        as "FECHA DE SOLICITUD CONCEPTO DE TRASLADO",
  case when coalesce(sp.soporte_solicitud_concepto_traslado, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE SOLICITUD CONCEPTO DE TRASLADO",
  sp.decreto_traslado                                         as "DECRETO DE TRASLADO",
  sp.fecha_decreto_traslado                                   as "FECHA DECRETO DE TRASLADO",
  case when coalesce(sp.soporte_decreto_traslado, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE DECRETO DE TRASLADO",
  sp.asignacion_ajuste_tramite_presupuestal                   as "ASIGNACIÓN DE RECURSOS (AJUSTE CON TRÁMITE PRESUPUESTAL)",
  sp.fecha_asignacion_ajuste_tramite_presupuestal             as "FECHA ASIGNACIÓN RECURSOS (AJUSTE CON TRÁMITE PRESUPUESTAL)",
  case when coalesce(sp.soporte_asignacion_ajuste_tramite_presupuestal, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE ASIGNACIÓN RECURSOS (AJUSTE CON TRÁMITE PRESUPUESTAL)",
  sp.cargado_siifweb                                          as "CARGADO SIIFWEB",
  sp.fecha_cargue_siifweb                                     as "FECHA DE CARGUE SIIFWEB",
  case when coalesce(sp.soporte_cargue_siifweb, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE CARGUE SIIFWEB",
  sp.estudios_previos                                         as "ESTUDIOS PREVIOS",
  sp.fecha_estudios_previos                                   as "FECHA DE ESTUDIOS PREVIOS",
  case when coalesce(sp.soporte_estudios_previos, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE ESTUDIOS PREVIOS",
  sp.radicado_contratacion                                    as "RADICADO EN CONTRATACIÓN",
  sp.fecha_radicado_contratacion                              as "FECHA DE RADICACIÓN EN CONTRATACIÓN",
  case when coalesce(sp.soporte_radicado_contratacion, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE RADICACIÓN EN CONTRATACIÓN",
  cs.texto                                                    as "CONTRATOS SIIFWEB",
  ps.texto                                                    as "PROCESOS CONTRACTUALES SECOP II",
  cse.texto                                                   as "CONTRATOS SECOP II",
  obs.texto                                                   as "OBSERVACIONES",
  nullif(concat_ws(', ',
    case when length(pfs.texto) > 32767 then 'Meta vigencia programada' end,
    case when length(mp.texto) > 32767 then 'Meta vigencia ficha PIIP' end,
    case when length(pfn.texto) > 32767 then 'Programación financiera' end,
    case when length(cs.texto) > 32767 then 'Contratos SIIFWEB' end,
    case when length(ps.texto) > 32767 then 'Procesos contractuales SECOP II' end,
    case when length(cse.texto) > 32767 then 'Contratos SECOP II' end,
    case when length(obs.texto) > 32767 then 'Observaciones' end), '')
                                                              as "AVISO LÍMITE DE CARACTERES DE EXCEL",
  sp.terminado                                                as "TERMINADO",
  sp.fecha_terminacion                                        as "FECHA DE TERMINACIÓN",
  case when coalesce(sp.soporte_terminacion, '') <> '' then 'Sí' else 'No' end
                                                              as "SOPORTE TERMINACIÓN"
from siifweb_proyecto sp
left join siifweb_dependenciaresponsable sd on sd.id = sp.dependencia_responsable_id
left join siifweb_medidatiempo sm on sm.id = sp.medida_tiempo_id
left join clasificaciones ccp on ccp.proyecto_id = sp.id
left join programacion_financiera pfn on pfn.proyecto_id = sp.id
left join programacion_fisica pfs on pfs.proyecto_id = sp.id
left join metas_piip mp on mp.proyecto_id = sp.id
left join cdp on cdp.proyecto_id = sp.id
left join rp on rp.proyecto_id = sp.id
left join obligaciones ob on ob.proyecto_id = sp.id
left join contratos_siifweb cs on cs.proyecto_id = sp.id
left join observaciones obs on obs.proyecto_id = sp.id
left join procesos_secop ps on ps.bpin = sp.bpin
left join contratos_secop cse on cse.bpin = sp.bpin
