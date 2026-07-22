# -*- coding: utf-8 -*-
"""Valida la migracion: totales por tabla y conciliacion padre-hijo.

    uv run python manage.py validar --vigencia 2025

La conciliacion se hace con agregacion en bloque (una consulta por relacion),
no fila por fila: sobre 15.000 imputaciones eso serian 30.000 consultas.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from siifweb.models import (Cdp, CdpImputacion, Compromiso, CompromisoImputacion, Obligacion,
                            ObligacionImputacion, Proyecto, Reserva, ReservaImputacion, Tercero)

TOL = Decimal("1")


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
        self.stdout.write("")
