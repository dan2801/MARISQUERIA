from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal


def rango_ventas(args, hoy):
    periodo = args.get('periodo', 'semana')
    if periodo == 'hoy':
        inicio = fin = hoy
    elif periodo == 'semana':
        inicio, fin = hoy - timedelta(days=hoy.weekday()), hoy
    elif periodo == 'mes':
        inicio, fin = hoy.replace(day=1), hoy
    elif periodo == 'rango':
        try:
            inicio = datetime.strptime(args.get('desde', ''), '%Y-%m-%d').date()
            fin = datetime.strptime(args.get('hasta', ''), '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Selecciona las fechas inicial y final.')
    else:
        raise ValueError('Selecciona un periodo válido.')
    if inicio > fin:
        raise ValueError('La fecha inicial no puede ser posterior a la final.')
    if (fin - inicio).days > 365:
        raise ValueError('Selecciona un rango de hasta 366 días.')
    return inicio, fin


def resumir_ventas(ventas, inicio, fin, comparar=False):
    dias = (fin - inicio).days + 1
    desplazamiento = timedelta(days=dias)
    agrupacion = 'hora' if dias == 1 else ('dia' if dias <= 92 else 'mes')
    desde = datetime.combine(inicio, datetime.min.time())
    hasta = datetime.combine(fin + timedelta(days=1), datetime.min.time())
    grupos = {}
    cursor = desde
    while cursor < hasta:
        if agrupacion == 'hora':
            siguiente = cursor + timedelta(hours=1)
            etiqueta = cursor.strftime('%H:%M')
        elif agrupacion == 'dia':
            siguiente = cursor + timedelta(days=1)
            etiqueta = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][cursor.weekday()] + cursor.strftime(' %d/%m')
        else:
            siguiente = (cursor.replace(day=1) + timedelta(days=monthrange(cursor.year, cursor.month)[1])).replace(day=1)
            etiqueta = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'][cursor.month - 1] + f' {cursor.year}'
        limite = min(siguiente, hasta)
        grupos[cursor.strftime('%Y-%m-%d %H' if agrupacion == 'hora' else ('%Y-%m-%d' if agrupacion == 'dia' else '%Y-%m'))] = {
            'etiqueta': etiqueta, 'inicio': cursor, 'fin': limite,
            'actual': Decimal('0'), 'anterior': Decimal('0'), 'tickets': 0, 'tickets_anterior': 0,
        }
        cursor = siguiente
    total, anterior = Decimal('0'), Decimal('0')
    cantidad = cantidad_anterior = 0
    por_dia = {}
    for venta in ventas:
        fecha = venta.fecha_cobro
        monto = Decimal(str(venta.total or 0)).quantize(Decimal('0.01'))
        if desde <= fecha < hasta:
            campo, contador = 'actual', 'tickets'
            total += monto
            cantidad += 1
            por_dia[fecha.date()] = por_dia.get(fecha.date(), Decimal('0')) + monto
        elif comparar and desde - desplazamiento <= fecha < desde:
            campo, contador = 'anterior', 'tickets_anterior'
            anterior += monto
            cantidad_anterior += 1
            fecha += desplazamiento
        else:
            continue
        clave = fecha.strftime('%Y-%m-%d %H' if agrupacion == 'hora' else ('%Y-%m-%d' if agrupacion == 'dia' else '%Y-%m'))
        grupos[clave][campo] += monto
        grupos[clave][contador] += 1
    maximo = max([g[c] for g in grupos.values() for c in ('actual', 'anterior')] + [Decimal('1')])
    barras = []
    for grupo in grupos.values():
        grupo['alto'] = float(grupo['actual'] / maximo * 100)
        grupo['alto_anterior'] = float(grupo['anterior'] / maximo * 100)
        grupo['periodo_anterior'] = (grupo['inicio'] - desplazamiento).strftime('%d/%m/%Y %H:%M') + ' – ' + (grupo['fin'] - desplazamiento - timedelta(seconds=1)).strftime('%d/%m/%Y %H:%M')
        barras.append(grupo)
    mejor = max(por_dia, key=por_dia.get) if por_dia else None
    return dict(barras=barras, total=total, anterior=anterior, cantidad=cantidad,
                cantidad_anterior=cantidad_anterior, promedio=total / cantidad if cantidad else 0,
                mejor_dia=mejor, mejor_total=por_dia[mejor] if mejor else 0,
                cambio=float((total - anterior) / anterior * 100) if anterior else None,
                agrupacion=agrupacion, inicio_anterior=inicio - desplazamiento,
                fin_anterior=inicio - timedelta(days=1))
