-- ============================================================================================
-- CONSULTA ORIGINAL DEL REPORTE DE PROYECTOS, CON CORRECCIONES MENORES (para auditoria)
-- ============================================================================================
-- Es la consulta escrita en el SQL editor de Supabase para el reporte de Excel (ODBC), revisada
-- el 24/11/2026. Se conserva su estructura; la que se usa para la vista es
-- vista_seguimiento_proyectos.sql.
--
-- Correcciones hechas (numeradas como en la revision):
--   3. Procesos SECOP II: "Fecha de ultima publicacion" mostraba la fecha de recepcion de
--      respuestas; ahora muestra fecha_ultima_publicacion.
--   4. Contratos SIIFWEB: tercero y centro de costo con LEFT JOIN (con INNER JOIN un contrato sin
--      alguno de los dos desaparecia del reporte). Se corrige "Nit" -> "Nit: " y la columna,
--      que salia como "string_agg", pasa a llamarse contratos_siifweb.
--   7. Todas las listas (string_agg) llevan ORDER BY: sin el, el orden cambia en cada consulta.
--   8. Observaciones: la fecha se pasa a la hora de Colombia con AT TIME ZONE 'America/Bogota'
--      en lugar de restar 5 horas.
--
-- Notas (no se cambian aqui; se resuelven en vista_seguimiento_proyectos.sql):
--   1. El SELECT * final trae la columna bpin una vez por cada bloque (once en total). Sirve
--      como consulta, pero no se puede guardar como vista: Postgres no admite columnas repetidas.
--   6. Los bloques se agregan y se unen por el texto del BPIN y no por el id del proyecto
--      (proyecto_id). Hoy no hay proyectos sin BPIN, asi que el resultado es el mismo; con un
--      proyecto sin BPIN, sus valores quedarian fuera (null no cruza con null). Por id ademas no
--      hace falta unir cada bloque con siifweb_proyecto. SECOP II si va por BPIN: BpinProceso
--      guarda siempre el BPIN, pero su proyecto puede quedar vacio.
--   Otras: los valores de CDP, RP y obligacion suman todas las vigencias (2022 a 2026); los
--   procesos y contratos de SECOP II cancelados se incluyen (el estado queda en el texto); las
--   columnas soporte_* traen la ruta del archivo en el almacenamiento, no un enlace.
-- ============================================================================================

with fuentes_programadas_por_proyecto as ( -- fuentes programados de forma manual desde la secciónd de programación en la sección de programación financiera
  select sp.bpin, string_agg(concat(spf.vigencia,' - ', sf.nombre, ' - ' ,smi.codigo, ' - ' , cast(round(spf.valor,2) as text) ), E'\n'
                             order by spf.vigencia, sf.nombre, smi.codigo) as prog_financiera
  from siifweb_programacionfinanciera as spf
  inner join siifweb_fuente as sf on spf.fuente_id = sf.id
  inner join siifweb_metaindicador as smi on spf.meta_id = smi.id
  inner join siifweb_proyecto as sp on spf.proyecto_id = sp.id
  group by sp.bpin
),
clasificacion_por_proyecto as ( -- clasificación en filter horizontal
  select sp.bpin, string_agg(sc.nombre,', ' order by sc.nombre) as clasificacion
  from siifweb_proyecto_clasificaciones as spc
  inner join siifweb_clasificacion as sc on spc.clasificacion_id = sc.id
  inner join siifweb_proyecto as sp on spc.proyecto_id = sp.id
  group by sp.bpin
),
valor_cdp_por_proyecto as (
  select sp.bpin, sum(sc.valor_disponibilidad_def) as valor_cdp
  from siifweb_cdpimputacion as sc
  inner join siifweb_proyecto as sp on sc.proyecto_id = sp.id
  group by sp.bpin
),
valor_rp_por_proyecto as (
  select sp.bpin, sum(srp.valor_compromiso_def) as valor_rp
  from siifweb_compromisoimputacion as srp
  inner join siifweb_proyecto as sp on srp.proyecto_id = sp.id
  group by sp.bpin
),
valor_obligacion_por_proyecto as (
  select sp.bpin, sum(sobli.valor_obligacion) as valor_obligacion
  from siifweb_obligacionimputacion as sobli
  inner join siifweb_proyecto as sp on sobli.proyecto_id = sp.id
  group by sp.bpin
),
proyecto as (
  select
    sd.nombre as dependencia_responsable, sp.bpin, sp.nombre, sp.radicado, sp.fecha_radicacion, sp.soporte_radicacion, sp.registrado,
    sp.fecha_registro, sp.soporte_registro, sp.tiempo_ejecucion, sm.nombre as medida_tiempo,
    sp.decreto_liquidacion_inicial, sp.fecha_decreto_liquidacion_inicial, sp.soporte_decreto_liquidacion_inicial, sp.contratacion_directa, sp.gestion_recursos_piip,
    sp.fecha_gestion_recursos_piip, sp.soporte_gestion_recursos_piip, sp.asignacion_ajuste_decreto_et, sp.fecha_asignacion_ajuste_decreto_et, sp.soporte_asignacion_ajuste_decreto_et,
    sp.solicitud_concepto_traslado, sp.fecha_solicitud_concepto_traslado, sp.soporte_solicitud_concepto_traslado, sp.decreto_traslado, sp.fecha_decreto_traslado, sp.soporte_decreto_traslado,
    sp.asignacion_ajuste_tramite_presupuestal, sp.fecha_asignacion_ajuste_tramite_presupuestal, sp.soporte_asignacion_ajuste_tramite_presupuestal, sp.cargado_siifweb, sp.fecha_cargue_siifweb, sp.soporte_cargue_siifweb, sp.estudios_previos, sp.fecha_estudios_previos, sp.soporte_estudios_previos, sp.radicado_contratacion, sp.fecha_radicado_contratacion, sp.soporte_radicado_contratacion,
    sp.terminado, sp.fecha_terminacion, sp.soporte_terminacion
  from siifweb_proyecto as sp
  left join siifweb_medidatiempo as sm on sp.medida_tiempo_id = sm.id
  left join siifweb_dependenciaresponsable sd on sp.dependencia_responsable_id = sd.id
),
vigencia_meta_proyecto as (
  select sf.bpin, string_agg(concat(smvi.vigencia, ' - ' ,concat(sic.codigo,' - ',sic.nombre), ' - ' , cast(round(smvi.meta,2) as text) ), E'\n'
                             order by smvi.vigencia, sic.codigo) as vigencia_meta_proyecto
  from siifweb_metavigenciaindicador as smvi
  inner join siifweb_indicadorproyecto as sip on smvi.indicador_proyecto_id = sip.id -- indicadores amarrados a proyectos
  inner join siifweb_indicadorcatalogo as sic on sip.indicador_id = sic.id
  inner join siifweb_formulacionproyecto as sf on sip.formulacion_id = sf.id -- aqui voy a encontrar la información general de los proyectos de PIIP
  -- left join siifweb_indicadormga as sim on sic.indicador_pdd_id = sim.id -- lo voy a dejar sin join por lo pronto, IndicadorMGA son solo los indicadore del PDD, si hago inner join podria exluir muchos indicadores que proyectos
  where smvi.meta <> 0
  group by sf.bpin
),
observaciones_proyecto as (
  select sp.bpin, string_agg( concat( cast( (sos.fecha_actualizacion at time zone 'America/Bogota') as date), ': ', texto ), E'\n'
                              order by sos.fecha_creacion) as observaciones
  from siifweb_observacionproyectosiifweb as sos
  inner join siifweb_proyecto as sp on sos.proyecto_id = sp.id
  group by sp.bpin
),
contratos_siifweb_proyectos as (
  select bpin, string_agg( concat( 'Tipo de contrato: ', tipo_contrato, ', Valor del contrato: ' , valor_contrato, ', Número del contrato: ' ,nro_contrato, ', Fecha de firma: ' ,fecha_firma, ', Nit: ' ,nit, ', Centro costo/dependencia en siifweb: ' , dependencia), E'\n'
                           order by fecha_firma, nro_contrato ) as contratos_siifweb
  from (
    select distinct sp.bpin, cast( sc.valor_contrato as text) as valor_contrato ,sc.tipo_contrato, sc.nro_contrato, cast( sc.fecha_firma as text) as fecha_firma, st.codigo as nit ,st.nombre, scc.nombre as dependencia
    from siifweb_contratoimputacion as sci
    inner join siifweb_proyecto as sp on sci.proyecto_id = sp.id
    inner join siifweb_contrato as sc on sci.contrato_id = sc.id
    left join siifweb_tercero as st on sc.tercero_id = st.id
    left join siifweb_centrocosto as scc on sc.dependencia_id = scc.id
  ) as subconsulta_proyectoscontratos
  group by bpin
),
procesos_contractuales_secop_por_proyecto as (
  select bpin, string_agg(procesos_contracturales, E'\n' order by procesos_contracturales) as procesos_contractuales_secop_ii
  from (
    select
      distinct sbp.bpin,
      concat('Id proceso: ', sps.id_proceso, ', Estado del procedimiento: ',sps.estado_procedimiento,
      ', Fecha de publicación: ' , case when cast( sps.fecha_publicacion as text ) is null then 'Sin fecha' else cast( sps.fecha_publicacion as text ) end,
      ', Fecha de última publicación: ' , case when cast( sps.fecha_ultima_publicacion as text) is null then 'Sin fecha' else cast( sps.fecha_ultima_publicacion as text) end,
      ', Fecha de recepción de respuestas: ' , case when cast( sps.fecha_recepcion_respuestas as text) is null then 'Sin fecha' else cast( sps.fecha_recepcion_respuestas as text) end,
      ', Fecha de apertura de respuestas: ' , case when cast( sps.fecha_apertura_respuestas as text) is null then 'Sin fecha' else cast( sps.fecha_apertura_respuestas as text) end,
      ', Fecha de apertura efectiva: ' , case when cast( sps.fecha_apertura_efectiva as text) is null then 'Sin fecha' else cast( sps.fecha_apertura_efectiva as text) end ,
      ', Contrato -> ' ,scs.referencia) as procesos_contracturales
    from siifweb_bpinproceso as sbp
    inner join siifweb_procesosecop as sps on sbp.proceso_id = sps.id
    left join siifweb_contratosecop as scs on sbp.contrato_secop_id = scs.id
    where lower(sps.id_proceso) <> 'no definido'
  ) as procesos_contratacion_secop_ii
  group by bpin
),
contratos_secop_por_proyecto as (
  select bpin, string_agg(contratos_secop_ii, E'\n' order by contratos_secop_ii) as contratos_secop_ii
  from (
    select distinct sbp.bpin,
    concat(
      'Id contrato: ',scs.id_contrato,
      ', Referencia: ', case when scs.referencia is null or scs.referencia = '' then 'Sin referencia' else scs.referencia end,
      ', Estado: ', case when scs.estado is null or scs.estado = '' then 'Sin estado' else scs.estado end,
      ', Valor: ', case when cast(scs.valor as text) is null then 'Sin valor' else cast(scs.valor as text) end,
      ', Fecha de Firma: ', case when cast(scs.fecha_firma as text) is null then 'Sin fecha de firma' else cast(scs.fecha_firma as text) end,
      ', Fecha de inicio: ', case when cast(scs.fecha_inicio as text) is null then 'Sin fecha de inicio' else cast(scs.fecha_inicio as text) end,
      ', Fecha de fin: ', case when cast(scs.fecha_fin as text) is null then 'Sin fecha de fin' else cast(scs.fecha_fin as text) end,
      ', Nit: ', case when st.codigo is null or st.codigo = '' then 'Sin nit' else st.codigo end,
      ', Proveedor: ', case when st.nombre is null or st.nombre = '' then 'Sin nombre proveedor' else st.nombre end
    ) as contratos_secop_ii
    from siifweb_bpinproceso as sbp
    inner join siifweb_contratosecop as scs on sbp.contrato_secop_id = scs.id
    left join siifweb_tercero as st on scs.proveedor_id = st.id
    where lower(scs.id_contrato) <> 'no definido'
  ) as contratacion_proyectos_secop_ii
  group by bpin
)
select *
from proyecto
left join vigencia_meta_proyecto as vmp on proyecto.bpin = vmp.bpin
left join fuentes_programadas_por_proyecto as fpp on proyecto.bpin = fpp.bpin
left join clasificacion_por_proyecto as ccp on proyecto.bpin = ccp.bpin
left join valor_cdp_por_proyecto as vcp on proyecto.bpin = vcp.bpin
left join valor_rp_por_proyecto as vrp on proyecto.bpin = vrp.bpin
left join valor_obligacion_por_proyecto as vop on proyecto.bpin = vop.bpin
left join contratos_siifweb_proyectos as csp on proyecto.bpin = csp.bpin
left join observaciones_proyecto as op on proyecto.bpin = op.bpin
left join procesos_contractuales_secop_por_proyecto as pcsp on proyecto.bpin = pcsp.bpin
left join contratos_secop_por_proyecto as csps on proyecto.bpin = csps.bpin;
