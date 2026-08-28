# -*- coding: utf-8 -*-
"""Valida la migracion: totales por tabla y conciliacion padre-hijo.

    uv run python manage.py validar --vigencia 2025

La conciliacion se hace con agregacion en bloque (una consulta por relacion),
no fila por fila: sobre 15.000 imputaciones eso serian 30.000 consultas.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q, Sum

from siifweb.models import (BpinProceso, Cdp, CdpImputacion, Compromiso, CompromisoImputacion,
                            ContratoSecop, Obligacion, ObligacionImputacion, ProcesoSecop,
                            Proyecto, Reserva, ReservaImputacion, Tercero)

TOL = Decimal("1")

# Un contrato de la Gobernacion por encima de esto es un error de digitacion en la
# fuente, no un contrato: el mayor real del periodo no llega a esa cifra.
ATIPICO = Decimal("100000000000")   # 100.000 millones


class Command(BaseCommand):
    help = "Valida los datos migrados contra las identidades de SIIFWEB"

    def add_arguments(self, parser):
        parser.add_argument("--vigencia", type=int, default=2025)

    def handle(self, *args, **opciones):
        v = opciones["vigencia"]
        ok = self.style.SUCCESS("OK   ")
        mal = self.style.ERROR("FALLA")

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n1. TOTALES CARGADOS - vigencia {v}"))
        totales = [
            ("CDPs", Cdp.objects.filter(vigencia=v).count(),
             CdpImputacion.objects.filter(cdp__vigencia=v).aggregate(t=Sum("valor_certificado"))["t"]),
            ("Compromisos", Compromiso.objects.filter(vigencia=v).count(),
             CompromisoImputacion.objects.filter(compromiso__vigencia=v)
             .aggregate(t=Sum("valor_compromiso_def"))["t"]),
            ("Obligaciones", Obligacion.objects.filter(vigencia=v).count(),
             ObligacionImputacion.objects.filter(obligacion__vigencia=v)
             .aggregate(t=Sum("valor_obligacion"))["t"]),
            ("Pagos", "", ObligacionImputacion.objects.filter(obligacion__vigencia=v)
             .aggregate(t=Sum("pagos"))["t"]),
            ("Reservas", Reserva.objects.filter(vigencia=v).count(),
             ReservaImputacion.objects.filter(reserva__vigencia=v).aggregate(t=Sum("valor_reserva"))["t"]),
        ]
        for nombre, cantidad, valor in totales:
            self.stdout.write(f"  {nombre:20} {str(cantidad):>7}   {valor or 0:>22,.2f}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n2. IDENTIDADES INTERNAS DEL REPORTE"))
        # saldo_obli == valor_obligacion - pagos
        malas = 0
        for fila in ObligacionImputacion.objects.filter(obligacion__vigencia=v).values(
                "id", "valor_obligacion", "pagos", "saldo_obli").iterator(chunk_size=5000):
            if abs(fila["saldo_obli"] - (fila["valor_obligacion"] - fila["pagos"])) >= TOL:
                malas += 1
        self.stdout.write(f"  [{ok if malas == 0 else mal}] obligaciones: saldo == obligado - pagado "
                          f"({malas} filas rotas)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n3. CONCILIACION PADRE-HIJO (agregacion en bloque)"))

        # CDP: saldo reportado vs (disponibilidad - suma de compromisos de esa imputacion)
        comprometido = {
            (f["cdp_id"], f["rubro_id"], f["fuente_id"], f["proyecto_id"]): f["total"]
            for f in CompromisoImputacion.objects.filter(compromiso__vigencia=v)
            .values("cdp_id", "rubro_id", "fuente_id", "proyecto_id").annotate(total=Sum("valor_compromiso_def"))
        }
        descuadres = agregadas = 0
        for f in (CdpImputacion.objects.filter(cdp__vigencia=v)
                  .values("cdp_id", "rubro_id", "fuente_id", "proyecto_id")
                  .annotate(disponible=Sum("valor_disponibilidad_def"), saldo=Sum("saldo_certf"))):
            agregadas += 1
            llave = (f["cdp_id"], f["rubro_id"], f["fuente_id"], f["proyecto_id"])
            calculado = f["disponible"] - comprometido.get(llave, Decimal("0"))
            if abs(f["saldo"] - calculado) >= TOL:
                descuadres += 1
        self.stdout.write(f"  [{ok if descuadres == 0 else mal}] CDP: saldo reportado == disponible - "
                          f"comprometido  ({descuadres} de {agregadas} imputaciones)")

        # Compromiso: saldo reportado vs (definitivo - suma de obligaciones de esa imputacion)
        obligado = {
            (f["compromiso_id"], f["rubro_id"], f["fuente_id"], f["proyecto_id"]): f["total"]
            for f in ObligacionImputacion.objects.filter(obligacion__vigencia=v)
            .values("compromiso_id", "rubro_id", "fuente_id", "proyecto_id").annotate(total=Sum("valor_obligacion"))
        }
        descuadres = agregadas = 0
        for f in (CompromisoImputacion.objects.filter(compromiso__vigencia=v)
                  .values("compromiso_id", "rubro_id", "fuente_id", "proyecto_id")
                  .annotate(definitivo=Sum("valor_compromiso_def"), saldo=Sum("saldo_rp"))):
            agregadas += 1
            llave = (f["compromiso_id"], f["rubro_id"], f["fuente_id"], f["proyecto_id"])
            calculado = f["definitivo"] - obligado.get(llave, Decimal("0"))
            if abs(f["saldo"] - calculado) >= TOL:
                descuadres += 1
        self.stdout.write(f"  [{ok if descuadres == 0 else mal}] Compromiso: saldo reportado == definitivo - "
                          f"obligado  ({descuadres} de {agregadas} imputaciones)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n4. SALTO TEMPORAL (v-1)"))
        sin_cdp = ReservaImputacion.objects.filter(reserva__vigencia=v, cdp_origen__isnull=True).count()
        total_res = ReservaImputacion.objects.filter(reserva__vigencia=v).count()
        self.stdout.write(f"  [{ok if sin_cdp == 0 else mal}] reservas con CDP de {v-1}: "
                          f"{total_res - sin_cdp} de {total_res}")
        mal_vig = ReservaImputacion.objects.filter(reserva__vigencia=v).exclude(
            cdp_origen__vigencia=v - 1).exclude(cdp_origen__isnull=True).count()
        self.stdout.write(f"  [{ok if mal_vig == 0 else mal}] ninguna reserva apunta a un CDP que no sea "
                          f"de {v-1}  ({mal_vig} incorrectas)")


        self.stdout.write(self.style.MIGRATE_HEADING("\n5. EJECUCION DE RESERVAS EN OBLIGACIONES"))
        de_reserva = ObligacionImputacion.objects.filter(
            obligacion__vigencia=v).exclude(compromiso__vigencia=v).count()
        self.stdout.write(f"  obligaciones {v} contra RP de otra vigencia: {de_reserva} "
                          f"(esperado 0 en 2024+, 43 en 2023)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n6. COBERTURA DEL SEGUIMIENTO POR PROYECTO"))
        for etiqueta, modelo, relacion in [
            ("imputaciones de CDP", CdpImputacion, "cdp__vigencia"),
            ("imputaciones de compromiso", CompromisoImputacion, "compromiso__vigencia"),
            ("imputaciones de obligacion", ObligacionImputacion, "obligacion__vigencia"),
        ]:
            total = modelo.objects.filter(**{relacion: v}).count()
            con = modelo.objects.filter(**{relacion: v}).exclude(proyecto__isnull=True).count()
            pct = 100 * con / total if total else 0
            self.stdout.write(f"  {etiqueta:28} {con:>6} de {total:>6} con proyecto ({pct:.0f}%)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n7. CATALOGO DE PROYECTOS"))
        total_p = Proyecto.objects.count()
        con_nombre = Proyecto.objects.exclude(nombre__isnull=True).exclude(nombre="").count()
        con_dep = Proyecto.objects.exclude(dependencia__isnull=True).count()
        self.stdout.write(f"  proyectos                    {total_p:>6}")
        self.stdout.write(f"  con nombre (del historial)   {con_nombre:>6}")
        self.stdout.write(f"  con dependencia              {con_dep:>6}")
        self.stdout.write(f"  terceros con nombre          "
                          f"{Tercero.objects.exclude(nombre__isnull=True).exclude(nombre='').count():>6}")

        self.validar_secop(ok, mal)
        self.stdout.write("")

    def validar_secop(self, ok, mal):
        """SECOP II. No depende de --vigencia: el consolidado se descarga por rango
        completo, asi que se revisa todo lo cargado."""
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. CONTRATACION PUBLICA (SECOP II)"))
        if not (BpinProceso.objects.exists() or ProcesoSecop.objects.exists()):
            self.stdout.write("  sin datos de SECOP II cargados")
            return

        filas = BpinProceso.objects.count()
        con_contrato = BpinProceso.objects.filter(contrato_secop__isnull=False).count()
        self.stdout.write(f"  procesos                     {ProcesoSecop.objects.count():>6}")
        self.stdout.write(f"  contratos                    {ContratoSecop.objects.count():>6}")
        self.stdout.write(f"  filas BPIN x proceso         {filas:>6}"
                          f"   ({con_contrato} con contrato, {filas - con_contrato} en tramite)")
        self.stdout.write(f"  BPIN distintos               "
                          f"{BpinProceso.objects.values('bpin').distinct().count():>6}")
        contratado = ContratoSecop.objects.aggregate(t=Sum("valor"))["t"] or 0
        self.stdout.write(f"  valor contratado             {contratado:>22,.2f}")
        limpio = ContratoSecop.objects.filter(valor__lte=ATIPICO).aggregate(t=Sum("valor"))["t"] or 0
        if limpio != contratado:
            # Un par de valores imposibles se comen el total: el util es el otro
            self.stdout.write(f"  valor sin los atipicos       {limpio:>22,.2f}")

        # --- coherencia de lo cargado ---
        cruzadas = (BpinProceso.objects.filter(contrato_secop__isnull=False)
                    .exclude(contrato_secop__proceso=F("proceso")).count())
        self.stdout.write(f"  [{ok if cruzadas == 0 else mal}] cada fila apunta al proceso de su "
                          f"contrato  ({cruzadas} cruzadas)")

        # Todo contrato entra por una fila del consolidado: si alguno se quedo sin
        # ninguna, la carga dejo basura
        sueltos = ContratoSecop.objects.filter(bpines__isnull=True).count()
        self.stdout.write(f"  [{ok if sueltos == 0 else mal}] todo contrato tiene su fila BPIN "
                          f"({sueltos} sueltos)")

        # --- lo que el equipo tiene que resolver ---
        huerfanos = sorted(BpinProceso.objects.filter(proyecto__isnull=True)
                           .values_list("bpin", flat=True).distinct())
        self.stdout.write(f"  [{ok if not huerfanos else mal}] BPIN de SECOP que estan en el catalogo "
                          f"({len(huerfanos)} sin proyecto)")
        for bpin in huerfanos[:10]:
            cuantas = BpinProceso.objects.filter(bpin=bpin).count()
            self.stdout.write(f"        {bpin}  ({cuantas} filas) - crear el proyecto o revisar el BPIN")
        if len(huerfanos) > 10:
            self.stdout.write(f"        ... y {len(huerfanos) - 10} mas")

        no_validados = BpinProceso.objects.exclude(validacion_bpin="Validado").count()
        self.stdout.write(f"  [{ok if no_validados == 0 else mal}] BPIN validados por el DNP "
                          f"({no_validados} sin validar)")

        # --- calidad del dato de origen (se reporta, no se corrige) ---
        atipicos = ContratoSecop.objects.filter(valor__gt=ATIPICO).order_by("-valor")
        self.stdout.write(f"  [{ok if not atipicos else mal}] valores dentro de lo posible "
                          f"({atipicos.count()} por encima de {ATIPICO:,.0f})")
        for contrato in atipicos[:5]:
            self.stdout.write(f"        {contrato.referencia or contrato.id_contrato:24} "
                              f"{contrato.valor:>22,.2f}  estado={contrato.estado or '-'}")

        sin_proveedor = ContratoSecop.objects.filter(proveedor__isnull=True).count()
        sin_firma = ContratoSecop.objects.filter(fecha_firma__isnull=True).count()
        sin_razon = (ContratoSecop.objects.filter(Q(proveedor__nombre__isnull=True)
                                                 | Q(proveedor__nombre=""))
                     .values("proveedor").distinct().count())
        self.stdout.write(f"  contratos sin proveedor      {sin_proveedor:>6}")
        self.stdout.write(f"  contratos sin fecha de firma {sin_firma:>6}")
        self.stdout.write(f"  proveedores sin razon social {sin_razon:>6}"
                          f"   (los completa cualquier reporte de SIIFWEB que los traiga)")

        # --- el pipeline y el cruce con SIIFWEB ---
        estados = (ProcesoSecop.objects.filter(bpines__contrato_secop__isnull=True)
                   .values("estado_procedimiento").annotate(n=Count("id", distinct=True))
                   .order_by("-n"))
        if estados:
            self.stdout.write("  procesos sin adjudicar, por estado:")
            for estado in estados:
                self.stdout.write(f"        {estado['estado_procedimiento'] or '(sin estado)':24} "
                                  f"{estado['n']:>5}")

        con_secop = Proyecto.objects.filter(procesos_secop__isnull=False).distinct()
        con_ambos = con_secop.filter(compromisos_imputados__isnull=False).distinct().count()
        self.stdout.write(f"  proyectos con contratacion   {con_secop.count():>6}"
                          f"   ({con_ambos} tambien con compromisos en SIIFWEB)")
        self.stdout.write("  el contraste de valores contra SIIFWEB es informativo: el contrato es el")
        self.stdout.write("  total pactado y el compromiso es el RP de cada vigencia, no tienen que cuadrar")
